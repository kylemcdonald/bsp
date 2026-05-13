#!/usr/bin/python3
import serial
import warnings
import threading
import time
import queue
import time
from enum import Enum

import requests
import numpy as np
import flask
from flask import Flask
from waitress import serve

home_position = (50, 65)
limit_position = (100, 100)
camera_url = 'http://localhost:8081/shutter'
tinyg_motion_params = {
    'xjm': 2000,
    'yjm': 2000,
    'xvm': 3000,
    'yvm': 3000,
}

from serial.tools import list_ports
try:
    port = next(list_ports.grep('FT230X'))
    port = port.device
except StopIteration:
    port = None

State = Enum('State', 'HOME DRAWING POSTDRAW')

import sys
def log(*args):
    print(*args)
    sys.stdout.flush()

class FakeSerial:
    def __init__(self):
        pass
        
    def write(self, msg):
        log('serial> write', msg)

    def read_until(self):
        return b''
        
    def read(self):
        return b''

# normalize a set of points to limits
def normalize(x, limit, flip_y=False):
    x = np.asarray(x).astype(float)
    if flip_y:
        x[:,1] *= -1
    x -= x.min(0)
    x *= limit / x.max()
    x += (limit - x.max(0)) / 2
    return x
    
def clamp(x, name, min_value=None, max_value=None):
    if min_value is not None and x < min_value:
        warnings.warn(f'{name}={x} clamped to {min_value}')
        x = min_value
    if max_value is not None and x > max_value:
        warnings.warn(f'{name}={x} clamped to {max_value}')
        x = max_value
    return x

def chunks(x, n):
    for i in range(0, len(x), n):
        yield x[i:i+n]

class Plotter(threading.Thread):
    def __init__(self, port=None, baudrate=115200):
        super().__init__()
        if port is None:
            log('no serial port available')
            self.ser = FakeSerial()
        else:
            log('using port', port)
            self.ser = serial.Serial(port, baudrate, timeout=2, write_timeout=2, rtscts=True)
            self.ser.reset_input_buffer()
            print('plotter> restarting')
            time.sleep(1)
            self.ser.write(chr(24).encode('ascii'))
            self.ser.flush()
            print('plotter> waiting for startup')
            startup = self.wait_for_startup()
            print('plotter> got startup:', startup)
            self.configure_tinyg()
        self.ready = True
        self.queue = queue.Queue()
        self.shutdown = threading.Event()
        self.clear = threading.Event()
        # self.need_to_go_home = False
        self.state = State.HOME

        # hit limits and go home on start
        self.define_position(*home_position)
        self.go(0, 0)
        self.go(*limit_position)
        self.home()

        self.start()

    def wait_for_startup(self, timeout=8):
        deadline = time.time() + timeout
        startup = b''
        while time.time() < deadline:
            msg = self.ser.read_until()
            if not msg:
                continue
            startup += msg
            if b'SYSTEM READY' in msg:
                break
        return startup

    def send_startup_command(self, command, timeout=2, idle_timeout=0.1):
        old_timeout = self.ser.timeout
        self.ser.timeout = min(old_timeout or timeout, 0.1)
        responses = []
        try:
            self.ser.write(f'{command}\n'.encode('ascii'))
            self.ser.flush()
            deadline = time.time() + timeout
            idle_deadline = None
            while time.time() < deadline:
                msg = self.ser.read_until()
                if msg:
                    responses.append(msg)
                    idle_deadline = time.time() + idle_timeout
                elif responses and idle_deadline is not None and time.time() >= idle_deadline:
                    break
        finally:
            self.ser.timeout = old_timeout
        return responses

    def configure_tinyg(self):
        log('plotter> configuring TinyG motion params', tinyg_motion_params)
        for name, value in tinyg_motion_params.items():
            responses = self.send_startup_command(f'${name}={value}')
            log('plotter> TinyG', name, responses)
        # Parameter commands leave JSON mode; restore it before normal G-code streaming.
        self.send_startup_command('$ej=1')
        self.send_startup_command('g21')
        self.send_startup_command('g90')

    def define_position(self, x, y):
        # https://github.com/synthetos/TinyG/wiki/Coordinate-Systems
        self.queue.put(f'g10l2p1x{-x:.4f}y{-y:.4f}\n')

    def home(self):
        if self.state == State.HOME:
            # already home
            log('plotter> already home')
            return
        log('plotter> home')
        # self.speed(homing_speed)
        # self.need_to_go_home = False
        self.go(*home_position)
        self.state = State.HOME
        
    def stop(self):
        log('plotter> stop')
        self.clear.set()

    # def speed(self, speed):
    #     speed = clamp_and_round(speed, 'speed', 1, 9999)
    #     self.queue.put(f'{speed:04d}s')

    # def smoothing(self, smoothing):
    #     smoothing = clamp_and_round(smoothing, 'speed', 1, 999)
    #     self.queue.put(f'{smoothing:03d}m')

    # def acceleration(self, acceleration):
    #     acceleration = clamp_and_round(acceleration, 'speed', 1, 99999)
    #     self.queue.put(f'{acceleration:05d}a')
        
    def go(self, x, y):
        x = clamp(x, 'x', 0, limit_position[0])
        y = clamp(y, 'y', 0, limit_position[1])
        self.queue.put(f'g0x{x:.4f}y{y:.4f}\n')
        self.state = State.DRAWING

    def draw(self, path, **args):
        for point in path:
            self.go(*point, **args)
        # self.need_to_go_home = True
            
    def join(self):
        log('plotter> sending shutdown')
        self.shutdown.set()
        super().join()
        
    # todo: write this part in a way that sends a bunch of commands quickly
    # if there are enough commands to send, and then cleans up the responses
    # when there are no more commands.
    def run(self):
        print('plotter> run')
        blast_size = 4
        read_queue_size = 0
        queue_previously_empty = True
        while not self.shutdown.is_set():
            time.sleep(0.01)
            try:
                if self.clear.is_set():
                    # then send hold and request tinyg queue flush
                    # https://github.com/synthetos/TinyG/wiki/TinyG-Feedhold-and-Resume
                    # the ! does not emit a response, but the % does "{rx:254}"
                    # these are both single character commands, no newline needed
                    msg = '!%'
                    log(f'plotter> clearing queue')
                    self.queue.queue.clear()
                    self.clear.clear()
                else:
                    msg = self.queue.get(timeout=1)
                    queue_previously_empty = False
                # log(f'msg> {repr(msg)}')
                self.ser.write(msg.encode('ascii'))
                self.ser.flush()
                read_queue_size += 1
            except queue.Empty:
                if not queue_previously_empty:
                    log('plotter> queue empty')
                queue_previously_empty = True
                pass
            try:
                if read_queue_size < blast_size and not self.queue.empty():
                    # log(f'plotter> blast-write to fill buffer', read_queue_size)
                    continue
                if read_queue_size > 0:
                    if read_queue_size >= blast_size and self.queue.empty():
                        while read_queue_size > 0:
                            # log('plotter> blast-read to empty buffer', read_queue_size)
                            msg = self.ser.read_until()
                            if not msg:
                                log('plotter> read timeout')
                                read_queue_size = 0
                                break
                            read_queue_size -= 1
                            # log(f'plotter> blast response {repr(msg)}')
                            # this message signifies that the freehold is finished
                            # and there is nothing left in the read queue, but it 
                            # doesn't necessarily come when the read_queue_size is 1
                            if msg == b'{"rx":254}\n':
                                log(f'plotter> finished at (a)', read_queue_size)
                                read_queue_size = 0
                    else:
                        msg = self.ser.read_until()
                        if not msg:
                            log('plotter> read timeout')
                            read_queue_size = 0
                            continue
                        read_queue_size -= 1
                        # log(f'plotter> single response {repr(msg)}')
                        if msg == b'{"rx":254}\n':
                            log(f'plotter> finished at (b)', read_queue_size)
                            read_queue_size = 0
                if read_queue_size == 0 and self.state == State.DRAWING:
                    log('plotter> finished drawing, waiting to go home')
                    time.sleep(4)
                    self.home()
            except serial.SerialTimeoutException:
                log('plotter> timeout')
            except serial.SerialException as e:
                log('plotter> serial error', e)
                read_queue_size = 0
                time.sleep(1)
        log('plotter> received shutdown')

app = Flask(__name__)
plotter = Plotter(port)

@app.route('/')
def index():
    with open('index.html') as f:
        return f.read()

@app.route('/go')
def go():
    req = flask.request
    x = int(req.args.get('x'))
    y = int(req.args.get('y'))
    plotter.go(x, y)
    return '',200

@app.route('/params')
def params():
    req = flask.request
    acceleration = int(req.args.get('acceleration'))
    speed = int(req.args.get('speed'))
    plotter.acceleration(acceleration)
    plotter.speed(speed)
    return '',200

@app.route('/home')
def home():
    plotter.home()
    return '',200

@app.route('/draw', methods=['POST'])
def draw():
    req = flask.request
    path = req.json['path']
    log(f'draw> path {len(path)} points')
    # speed = default_speed
    raw = False
    # try:
    #     speed = int(req.json['speed'])
    # except KeyError:
    #     pass
    try:
        raw = req.json['raw']
    except KeyError:
        pass
    if not raw:
        path = normalize(path, limit_position, flip_y=True)
    # plotter.speed(speed)
    plotter.draw(path)
    return '',200

@app.route('/stop')
def stop():
    plotter.stop()
    # plotter.home()
    return '',200

@app.route('/shutter')
def shutter():
    log('shutter> pressed')
    requests.get(camera_url)
    return '',200

@app.route('/button')
def button():
    log('button> pressed')
    if plotter.state == State.HOME:
        log('button> shutter()')
        shutter()
    elif plotter.state == State.DRAWING:
        log('button> stop()')
        stop()
    elif plotter.state == State.POSTDRAW:
        log('button> home()')
        home()
    return '',200

@app.route('/status')	
def status():
    return {'state': plotter.state.name}

serve(app, listen='*:8080')
plotter.join()
