#!/usr/bin/python3
import cv2
import time
import threading
import datetime
import os

import requests
from flask import Flask
from waitress import serve

from flushed import log
from wait_for_format import wait_for_format

api_base_url = (os.environ.get('BSP_VIBECHECK_URL') or 'http://vibecheck.local:8787').rstrip('/')
process_url = os.environ.get('BSP_PROCESS_URL') or f'{api_base_url}/api/process'
plotter_url = os.environ.get('BSP_PLOTTER_DRAW_URL', 'http://localhost:8080/draw')
jpeg_quality = 90
request_timeout = 120

log('using process endpoint', process_url)

def count_points(path_payload):
    if not isinstance(path_payload, dict):
        return None
    if 'coordinates' in path_payload:
        return len(path_payload['coordinates'])
    if 'vector' in path_payload:
        return count_points(path_payload['vector'])
    try:
        return len(path_payload['continuous_path']['points'])
    except (KeyError, TypeError):
        return None

def extract_vector_payload(process_payload):
    if not isinstance(process_payload, dict):
        raise ValueError('process response must be a JSON object')
    vector_payload = process_payload.get('vector', process_payload)
    if count_points(vector_payload) is None:
        raise ValueError('process response did not contain vector.continuous_path.points')
    return vector_payload

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

        self.cap = cap
        self.shutdown = threading.Event()
        self.shutter = threading.Event()
        self.start()

    def join(self):
        log('camera> sending shutdown')
        self.shutdown.set()
        super().join()
        
    def capture(self):
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]

        log('camera> capture')
        ret, img = self.cap.read()
        if not ret:
            log('camera> capture failed')
            return

        log('camera> convert full frame to jpg for post')
        ok, encimg = cv2.imencode('.jpg', img, encode_param)
        if not ok:
            log('camera> jpg encode failed')
            return

        save_to_disk(encimg, 'images', '.jpg')

        # send to endpoint
        data = encimg.tobytes()
        files = {
            'image': ('capture.jpg', data, 'image/jpeg'),
        }
        try:
            log('camera> post jpg to process api')
            response = requests.post(
                process_url,
                files=files,
                timeout=request_timeout,
            )
            response.raise_for_status()
            process_payload = response.json()
            vector_payload = extract_vector_payload(process_payload)
            point_count = count_points(vector_payload)
            if point_count is None:
                log('camera> process response received')
            else:
                log(f'camera> process response {point_count} points')
            response = requests.post(
                plotter_url,
                json={'path': vector_payload},
                timeout=request_timeout,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            log('camera> connection error')
        except requests.exceptions.Timeout:
            log('camera> request timeout')
        except requests.exceptions.HTTPError as e:
            log('camera> http error', e)
        except requests.exceptions.JSONDecodeError:
            log('camera> JSON response error')
        except ValueError as e:
            log('camera> invalid process response', e)

    def run(self):
        while not self.shutdown.is_set():
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
