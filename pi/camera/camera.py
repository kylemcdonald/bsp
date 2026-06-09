#!/usr/bin/python3
import cv2
import time
import threading
import datetime
import os
import queue
import uuid

import requests
from flask import Flask, request
from waitress import serve

from flushed import log
from wait_for_format import wait_for_format

api_base_url = (os.environ.get('BSP_VIBECHECK_URL') or 'http://vibecheck.taildd340.ts.net:8787').rstrip('/')
process_url = os.environ.get('BSP_PROCESS_URL') or f'{api_base_url}/api/process'
plotter_result_url = os.environ.get('BSP_PLOTTER_CAPTURE_RESULT_URL', 'http://localhost:8080/capture-result')
jpeg_quality = 90
request_timeout = 120

log('using process endpoint', process_url)
log('using plotter capture result endpoint', plotter_result_url)

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
        self.shutter = queue.Queue()
        self.start()

    def join(self):
        log('camera> sending shutdown')
        self.shutdown.set()
        super().join()
        
    def capture(self, request_id, trigger_received_at):
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        timings = {
            'request_id': request_id,
            'trigger_received_at': trigger_received_at,
        }

        log('camera> capture')
        ret, img = self.cap.read()
        timings['photo_received_at'] = time.perf_counter()
        if not ret:
            log('camera> capture failed')
            return

        log('camera> convert full frame to jpg for post')
        ok, encimg = cv2.imencode('.jpg', img, encode_param)
        timings['photo_encoded_at'] = time.perf_counter()
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
            timings['server_request_started_at'] = time.perf_counter()
            response = requests.post(
                process_url,
                files=files,
                timeout=request_timeout,
            )
            timings['server_response_received_at'] = time.perf_counter()
            response.raise_for_status()
            process_payload = response.json()
            vector_payload = extract_vector_payload(process_payload)
            point_count = count_points(vector_payload)
            if point_count is None:
                log('camera> process response received')
            else:
                log(f'camera> process response {point_count} points')
            response = requests.post(
                plotter_result_url,
                json={
                    'request_id': request_id,
                    'path': vector_payload,
                    'process_response': process_payload,
                    'timings': summarize_timings(timings),
                },
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
            try:
                request = self.shutter.get_nowait()
                self.capture(request['request_id'], request['trigger_received_at'])
            except queue.Empty:
                pass
        log('camera> received shutdown')

app = Flask(__name__)
camera = Camera()

def summarize_timings(timings):
    return {
        'request_id': timings['request_id'],
        'photo_trigger_to_receive_ms': (timings['photo_received_at'] - timings['trigger_received_at']) * 1000,
        'photo_receive_to_encoded_ms': (timings['photo_encoded_at'] - timings['photo_received_at']) * 1000,
        'photo_encoded_to_transmit_started_ms': (timings['server_request_started_at'] - timings['photo_encoded_at']) * 1000,
        'server_round_trip_ms': (timings['server_response_received_at'] - timings['server_request_started_at']) * 1000,
    }

@app.route('/shutter')
def shutter():
    request_id = request.args.get('request_id') or str(uuid.uuid4())
    camera.shutter.put({
        'request_id': request_id,
        'trigger_received_at': time.perf_counter(),
    })
    return {'request_id': request_id}, 202

serve(app, listen='*:8081')
camera.join()
