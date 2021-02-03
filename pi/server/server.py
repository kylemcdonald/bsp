#!/usr/bin/python3
import serial
import warnings
import datetime
import threading
import time
import queue

import flask
from flask import Flask
from waitress import serve

try:
    from gpiozero import LED
    led = LED(4)
    led.on()
except ModuleNotFoundError:
    pass

from serial.tools import list_ports
try:
    port = next(list_ports.grep('USB Serial'))
    port = port.device
except StopIteration:
    port = None

def log(*args):
    dt = datetime.datetime.now().replace(microsecond=0)
    print(dt, *args)

class FakeSerial:
    def __init__(self, timeout):
        self.timeout = timeout
        pass
        
    def write(self, msg):
        log('serial> write', msg)
        
    def read(self):
        time.sleep(1)
        log('serial> read A')
        return 'A'
    
def clamp_and_round(x, name, min_value=None, max_value=None):
    if min_value is not None and x < min_value:
        warnings.warn(f'{name}={x} clamped to {min_value}')
        x = min_value
    if max_value is not None and x > max_value:
        warnings.warn(f'{name}={x} clamped to {max_value}')
        x = max_value
    return round(x)

def chunks(x, n):
    for i in range(0, len(x), n):
        yield x[i:i+n]

class Plotter(threading.Thread):
    def __init__(self, port=None, baudrate=115200, timeout=3, spoon_size=15):
        super().__init__()
        if port is None:
            log('no serial port available')
            self.ser = FakeSerial(timeout=timeout)
        else:
            log('using port', port)
            self.ser = serial.Serial(port, baudrate, timeout=timeout)
        self.spoon_size = spoon_size
        self.ready = True
        self.queue = queue.Queue()
        self.shutdown = threading.Event()
        self.start()
        
    def clear(self):
        log('plotter> clear')
        with self.queue.mutex:
            self.queue.queue.clear() 
        
    def jog(self, x=None, y=None):
        if x is not None and x != 0:
            key = 'X' if x > 0 else 'x'
            amt = int(abs(x))
            self.queue.put(f'{amt}{key}')
        if y is not None and y != 0:
            key = 'Y' if y > 0 else 'y'
            amt = int(abs(y))
            self.queue.put(f'{amt}{key}')

    def go(self, x, y, speed=50, smooth=True):
        x = clamp_and_round(x, 'x', 0)
        y = clamp_and_round(y, 'y', 0)
        speed = clamp_and_round(speed, 'speed', 1, 99)
        self.queue.put(f'{smooth:d}{x:05d}{y:05d}{speed:02d}g')
        
    def draw(self, path, **args):
        for point in path:
            self.go(*point, **args)
            
    def join(self):
        log('plotter> sending shutdown')
        self.shutdown.set()
        super().join()
        
    # this logic is not ideal:
    # - this will not fill the teensy buffer if spoon_size == 'A' modulo.
    #   it will just keep hitting empty.
    # - it can take up to `timeout` waiting for ser.read() until new
    #   messages are sent. `timeout` should be slightly longer than
    #   the amount of time it takes the teensy buffer to go from full to
    #   half full.
    # - the shutdown event will be ignored until a spoon is finished.
    def run(self):
        while not self.shutdown.is_set():
            try:
                time.sleep(0.3)
                # send (up to) spoon_size messages, if available
                for i in range(self.spoon_size):
                    msg = self.queue.get(timeout=1)
                    self.ser.write(msg.encode('ascii'))
                try:
                    # after sending messages, wait for a response
                    response = self.ser.read()
                    if response in [b'A', b'\r', b'\n']:
                        log(f'plotter> received {repr(response)}')
                        continue
                    warning = f'{datetime.datetime.now()} unexpected response "{response}"'
                    warnings.warn(warning)
                except serial.SerialTimeoutException:
                    # if we get a timeout waiting for a message,
                    # move on to the next loop
                    warnings.warn(f'{self.ser.timeout}s timeout')
            except queue.Empty:
                # log('plotter> no messages')
                pass
        log('plotter> received shutdown')

app = Flask(__name__)
plotter = Plotter(port)

@app.route('/')
def index():
    with open('index.html') as f:
        return f.read()

@app.route('/jog')
def jog():
    req = flask.request
    x = int(req.args.get('x'))
    y = int(req.args.get('y'))
    plotter.jog(x, y)
    return '',200

@app.route('/go')
def go():
    req = flask.request
    x = int(req.args.get('x'))
    y = int(req.args.get('y'))
    speed = int(req.args.get('speed'))
    plotter.go(x, y, speed)
    return '',200

@app.route('/draw', methods=['POST'])
def draw():
    req = flask.request
    path = req.json['path']
    speed = int(req.json['speed'])
    plotter.draw(path, speed=speed)
    return '',200

@app.route('/clear')
def clear():
    plotter.clear()
    return '',200

@app.route('/button')
def button():
    log('button> pressed')
    return '',200

serve(app, listen='*:8080')
plotter.join()
