#!/usr/bin/python3
import serial
import warnings
import datetime
import threading
import time
import queue
import struct

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

import sys
def log(*args):
    # dt = datetime.datetime.now().replace(microsecond=0)
    print(*args)
    sys.stdout.flush()

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
    def __init__(self, port=None, baudrate=115200, timeout=0, spoon_size=512):
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
        self.queue.put('p')

    def speed(self, speed):
        speed = clamp_and_round(speed, 'speed', 1, 99)
        self.queue.put(f'{speed:02d}s')
        
    def go(self, x, y):
        x = clamp_and_round(x, 'x', 0)
        y = clamp_and_round(y, 'y', 0)
        self.queue.put(f'{x:05d}{y:05d}g')
        
    def draw(self, path, **args):
        for point in path:
            self.go(*point, **args)
            
    def join(self):
        log('plotter> sending shutdown')
        self.shutdown.set()
        super().join()
        
    def run(self):
        while not self.shutdown.is_set():
            time.sleep(0.01)
            try:
                # send (up to) spoon_size messages, if available
                qsize = self.queue.qsize()
                # if qsize > 0:
                #     log(f'plotter> remaining to send {qsize}')
                for i in range(self.spoon_size):
                    msg = self.queue.get(timeout=1)
                    self.ser.write(msg.encode('ascii'))
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

@app.route('/go')
def go():
    req = flask.request
    x = int(req.args.get('x'))
    y = int(req.args.get('y'))
    speed = int(req.args.get('speed'))
    plotter.speed(speed)
    plotter.go(x, y)
    return '',200

@app.route('/draw', methods=['POST'])
def draw():
    req = flask.request
    speed = int(req.json['speed'])
    plotter.speed(speed)
    path = req.json['path']
    plotter.draw(path)
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
