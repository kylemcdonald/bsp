#!/usr/bin/python3
import json
import os
import serial
import warnings
import threading
import time
import queue
import time
from enum import Enum
from pathlib import Path

import requests
import flask
from flask import Flask
from waitress import serve
from motion import DEFAULT_EPSILON_MM, plan_path
from serial.tools import list_ports

home_position = (50, 65)
limit_position = (100, 100)
camera_url = os.environ.get('BSP_CAMERA_SHUTTER_URL', 'http://localhost:8081/shutter')
tinyg_port = os.environ.get('BSP_TINYG_PORT')
predefined_button_path = (
    Path(__file__).resolve().parents[2] /
    'vectors.json'
)
predefined_button_rotate_180 = True
tinyg_motion_params = {
    'xjm': 2000,
    'yjm': 2000,
    'xvm': 3000,
    'yvm': 3000,
}
reconnect_interval = 1

State = Enum('State', 'HOME DRAWING POSTDRAW')

import sys
def log(*args):
    print(*args)
    sys.stdout.flush()

class FakeSerial:
    def __init__(self):
        self.timeout = 0
        
    def write(self, msg):
        log('serial> write', msg)

    def flush(self):
        pass

    def read_until(self):
        return b''
        
    def read(self):
        return b''

    def close(self):
        pass

def find_tinyg_port():
    if tinyg_port:
        return tinyg_port
    try:
        return next(list_ports.grep('FT230X')).device
    except StopIteration:
        return None

def clamp(x, name, min_value=None, max_value=None):
    if min_value is not None and x < min_value:
        warnings.warn(f'{name}={x} clamped to {min_value}')
        x = min_value
    if max_value is not None and x > max_value:
        warnings.warn(f'{name}={x} clamped to {max_value}')
        x = max_value
    return x

class Plotter(threading.Thread):
    def __init__(self, port=None, baudrate=115200):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.ser = FakeSerial()
        self.connected = False
        self.queue = queue.Queue()
        self.shutdown = threading.Event()
        self.clear = threading.Event()
        self.state = State.HOME
        self.ready = True

        if self.connect():
            self.initialize_position()

        self.start()

    def initialize_position(self):
        # hit limits and go home on start or reconnect
        self.clear_queue()
        self.define_position(*home_position)
        self.go(0, 0)
        self.go(*limit_position)
        self.home()

    def connect(self):
        port = self.port or find_tinyg_port()
        if port is None:
            log('plotter> TinyG serial port not available')
            return False
        try:
            log('plotter> connecting to port', port)
            ser = serial.Serial(
                port,
                self.baudrate,
                timeout=2,
                write_timeout=2,
                rtscts=True,
            )
            ser.reset_input_buffer()
            self.ser = ser
            self.port = port
            log('plotter> restarting TinyG')
            time.sleep(1)
            self.ser.write(chr(24).encode('ascii'))
            self.ser.flush()
            log('plotter> waiting for startup')
            startup = self.wait_for_startup()
            log('plotter> got startup:', startup)
            self.configure_tinyg()
            self.connected = True
            return True
        except serial.SerialException as e:
            log('plotter> serial connection failed', e)
        except OSError as e:
            log('plotter> serial connection failed', e)
        self.connected = False
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser = FakeSerial()
        return False

    def disconnect(self):
        if self.connected:
            log('plotter> disconnected from TinyG')
        self.connected = False
        self.clear_queue()
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser = FakeSerial()
        self.state = State.HOME

    def clear_queue(self):
        with self.queue.mutex:
            self.queue.queue.clear()

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
        self.go(*home_position)
        self.state = State.HOME
        
    def stop(self):
        log('plotter> stop')
        self.clear.set()

    def go(self, x, y):
        if not self.connected:
            log('plotter> ignoring go while disconnected')
            return
        x = clamp(x, 'x', 0, limit_position[0])
        y = clamp(y, 'y', 0, limit_position[1])
        self.queue.put(f'g0x{x:.4f}y{y:.4f}\n')
        self.state = State.DRAWING

    def draw(self, commands):
        if not self.connected:
            raise RuntimeError('plotter is disconnected')
        for command in commands:
            self.queue.put(f'{command}\n')
        self.state = State.DRAWING
            
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
        next_reconnect = 0
        while not self.shutdown.is_set():
            time.sleep(0.01)
            if not self.connected:
                if time.time() >= next_reconnect:
                    if self.connect():
                        self.initialize_position()
                        read_queue_size = 0
                    next_reconnect = time.time() + reconnect_interval
                continue
            try:
                if self.clear.is_set():
                    # then send hold and request tinyg queue flush
                    # https://github.com/synthetos/TinyG/wiki/TinyG-Feedhold-and-Resume
                    # the ! does not emit a response, but the % does "{rx:254}"
                    # these are both single character commands, no newline needed
                    msg = '!%'
                    log(f'plotter> clearing queue')
                    self.clear_queue()
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
            except (serial.SerialTimeoutException, serial.SerialException) as e:
                log('plotter> serial write error', e)
                read_queue_size = 0
                self.disconnect()
                time.sleep(1)
                continue
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
                self.disconnect()
                time.sleep(1)
        log('plotter> received shutdown')

app = Flask(__name__)
plotter = Plotter(tinyg_port)

def queue_planned_draw(
    path_payload,
    raw=False,
    flip_y=True,
    rotate_180=False,
    epsilon_mm=DEFAULT_EPSILON_MM,
    source='draw',
):
    planned = plan_path(
        path_payload,
        raw=raw,
        flip_y=flip_y,
        rotate_180=rotate_180,
        epsilon_mm=epsilon_mm,
    )
    stats = planned['stats']
    log(
        f'{source}> planned',
        stats['original']['point_count'], '->',
        stats['planned']['point_count'], 'points',
        'length', f"{stats['planned']['path_length_mm']:.1f}mm",
        'bbox', stats['planned']['bbox_mm']
    )
    plotter.draw(planned['commands'])
    return planned

@app.route('/')
def index():
    with open('index.html') as f:
        return f.read()

@app.route('/go')
def go():
    if not plotter.connected:
        return {'error': 'plotter is disconnected'}, 503
    req = flask.request
    x = int(req.args.get('x'))
    y = int(req.args.get('y'))
    plotter.go(x, y)
    return '',200

@app.route('/home')
def home():
    if not plotter.connected:
        return {'error': 'plotter is disconnected'}, 503
    plotter.home()
    return '',200

@app.route('/draw', methods=['POST'])
def draw():
    if not plotter.connected:
        return {'error': 'plotter is disconnected'}, 503
    req = flask.request
    body = req.get_json(silent=True)
    if not isinstance(body, dict):
        body = {'path': body}
    raw = bool(body.get('raw', False))
    try:
        planned = queue_planned_draw(
            body.get('path', body),
            raw=raw,
            flip_y=bool(body.get('flip_y', not raw)),
            rotate_180=bool(body.get('rotate_180', False)),
            epsilon_mm=float(body.get('epsilon_mm', DEFAULT_EPSILON_MM)),
        )
    except (KeyError, TypeError, ValueError, RuntimeError) as e:
        log('draw> invalid path', e)
        return {'error': str(e)}, 400
    return {
        'state': plotter.state.name,
        'stats': planned['stats'],
    }, 200

@app.route('/stop')
def stop():
    if not plotter.connected:
        return {'error': 'plotter is disconnected'}, 503
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
        log('button> predefined draw()', predefined_button_path)
        try:
            with predefined_button_path.open(encoding='utf-8') as f:
                path_payload = json.load(f)
            queue_planned_draw(
                path_payload,
                rotate_180=predefined_button_rotate_180,
                source='button',
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, RuntimeError) as e:
            log('button> predefined draw failed', e)
            return {'error': str(e)}, 500
    elif plotter.state == State.DRAWING:
        log('button> stop()')
        stop()
    elif plotter.state == State.POSTDRAW:
        log('button> home()')
        home()
    return '',200

@app.route('/status')	
def status():
    return {
        'state': plotter.state.name,
        'connected': plotter.connected,
        'port': plotter.port,
    }

serve(app, listen='*:8080')
plotter.join()
