#!/usr/bin/python3
import cv2
import time
import threading
import datetime
import numpy as np
import os

import requests
import flask
from flask import Flask
from waitress import serve

gce_url = 'http://35.235.122.201:8080'
plotter_url = 'http://localhost:8080/draw'
jpeg_quality = 90

import sys
def log(*args):
    print(*args)
    sys.stdout.flush()

log('using endpoint', gce_url)

def save_to_disk(data, directory, extension):
    now = datetime.datetime.now()
    os.makedirs(directory, exist_ok=True)
    fn = now.replace(microsecond=0).isoformat() + extension
    fn = fn.replace(':', '-')
    fn = os.path.join(directory, fn)
    with open(fn, 'wb') as f:
        f.write(data)

class Camera(threading.Thread):
    def __init__(self):
        super().__init__()

        fourcc = 'MJPG'
        width = 1920*2
        height = 1080*2
        fps = 1

        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)

        self.cap = cap
        self.shutdown = threading.Event()
        self.shutter = threading.Event()
        self.start()

    def join(self):
        log('camera> sending shutdown')
        self.shutdown.set()
        super().join()
        
    def capture(self):
        log('camera> capture')
        ret, img = self.cap.read()

        # convert to jpeg
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        _, encimg = cv2.imencode('.jpg', img, encode_param)

        # send to endpoint
        data = encimg.tobytes()
        headers = {'Content-type': 'image/jpeg'}
        try:
            response = requests.post(gce_url, data=data, headers=headers)
            data = response.json()['coordinates']
            log(f'camera> gce response {len(data)} points')
            response = requests.post(plotter_url, json={'path':data})
        except ConnectionError:
            log('camera> connection error')

        # save to disk
        save_to_disk(encimg, 'images', '.jpg')

    def run(self):
        while not self.shutdown.is_set():
            # run through the buffer to stay up to date
            ret = self.cap.grab()
            if not self.shutter.is_set():
                continue
            self.shutter.clear()
            self.capture()
        log('camera> received shutdown')

app = Flask(__name__)
camera = Camera()

@app.route('/shutter')
def shutter():
    camera.shutter.set()
    return '',200

serve(app, listen='*:8081')
camera.join()