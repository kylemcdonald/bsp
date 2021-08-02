#!/usr/bin/python3
import cv2
import time
import threading
import datetime
import numpy as np
import os
import json
from simplejson.errors import JSONDecodeError

import requests
import flask
from flask import Flask
from waitress import serve

from flushed import log
from face_extractor import FaceExtractor
from wait_for_format import wait_for_format

gce_url = 'http://bsp-ams.kylemcdonald.net:8080'
plotter_url = 'http://localhost:8080/draw'
jpeg_quality = 90

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
        fps = 5

        log('camera> waiting for availability')
        cap = wait_for_format(fourcc, width, height, fps)
        log('camera> camera is available')

        log('camera> loading face extractor')
        self.face_extractor = FaceExtractor()
        log('camera> loaded face extractor')

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

        log('camera> extracting face')
        sub = self.face_extractor(img)

        log('camera> convert to jpg for post')
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        _, encimg = cv2.imencode('.jpg', sub, encode_param)

        save_to_disk(encimg, 'faces', '.jpg')

        # send to endpoint
        data = encimg.tobytes()
        headers = {'Content-type': 'image/jpeg'}
        try:
            log('camera> post jpg')
            response = requests.post(gce_url, data=data, headers=headers)
            log('camera> response')
            data = response.json()['coordinates']
            log(f'camera> gce response {len(data)} points')
            response = requests.post(plotter_url, json={'path':data})
        except ConnectionError:
            log('camera> connection error')
        except JSONDecodeError:
            log('camera> JSON response error')
            log(response.raw)

        log('camera> convert to jpg and save to disk')
        _, encimg = cv2.imencode('.jpg', img, encode_param)
        save_to_disk(encimg, 'images', '.jpg')

    def run(self):
        last_time = time.time()
        while not self.shutdown.is_set():
            # now = time.time()
            # if now - last_time > 5:
            #     print('camera> grabbing reference')
            #     ret, img = self.cap.read()
            #     log('camera> convert to jpg')
            #     encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
            #     _, encimg = cv2.imencode('.jpg', img, encode_param)
            #     log('camera> save to disk')
            #     save_to_disk(encimg, 'references', '.jpg')
            #     last_time = now

            # run through the buffer to stay up to date
            ret = self.cap.grab()

            # watch for button presses
            if self.shutter.is_set():
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