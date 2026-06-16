#!/usr/bin/python3
import cv2
import json
import time
import threading
import datetime
import os
import queue
import subprocess
import uuid

import requests
from flask import Flask, Response, request
from waitress import serve

from flushed import log
from wait_for_format import wait_for_format

plotter_capture_image_url = os.environ.get('BSP_PLOTTER_CAPTURE_IMAGE_URL', 'http://localhost:8080/capture-image')
plotter_error_url = os.environ.get('BSP_PLOTTER_CAPTURE_ERROR_URL', 'http://localhost:8080/capture-error')
jpeg_quality = 50
request_timeout = 120
camera_device = os.environ.get('BSP_CAMERA_DEVICE', '/dev/video0')

log('using plotter capture image endpoint', plotter_capture_image_url)
log('using plotter capture error endpoint', plotter_error_url)

camera_control_specs = {
    'auto_exposure': {'min': 1, 'max': 3},
    'exposure_time_absolute': {'min': 3, 'max': 500},
    'gain': {'min': 0, 'max': 255},
}

def parse_bool(value, name):
    if isinstance(value, bool):
        return value
    raise ValueError(f'{name} must be true or false')

def parse_int(value, name, min_value, max_value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be an integer')
    if parsed < min_value or parsed > max_value:
        raise ValueError(f'{name} must be between {min_value} and {max_value}')
    return parsed

def run_v4l2_ctl(args):
    command = ['v4l2-ctl', f'--device={camera_device}', *args]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or 'v4l2-ctl failed'
        raise RuntimeError(message)
    return result.stdout

def get_camera_settings():
    names = ','.join(camera_control_specs.keys())
    output = run_v4l2_ctl([f'--get-ctrl={names}'])
    settings = {}
    for line in output.splitlines():
        if ':' not in line:
            continue
        name, value = line.split(':', 1)
        name = name.strip()
        if name not in camera_control_specs:
            continue
        settings[name] = int(value.strip().split()[0])
    settings['exposure_mode'] = 'auto' if settings.get('auto_exposure') == 3 else 'manual'
    settings['auto_exposure_enabled'] = settings.get('auto_exposure') == 3
    settings['limits'] = {
        name: {
            'min': spec['min'],
            'max': spec['max'],
        }
        for name, spec in camera_control_specs.items()
    }
    return settings

def set_camera_settings(payload):
    if not isinstance(payload, dict):
        raise ValueError('settings payload must be a JSON object')

    controls = []
    if 'auto_exposure_enabled' in payload:
        enabled = parse_bool(payload['auto_exposure_enabled'], 'auto_exposure_enabled')
        controls.append(f'auto_exposure={3 if enabled else 1}')
    elif 'exposure_mode' in payload:
        mode = payload['exposure_mode']
        if mode not in ('auto', 'manual'):
            raise ValueError('exposure_mode must be auto or manual')
        controls.append(f'auto_exposure={3 if mode == "auto" else 1}')

    for name in ('exposure_time_absolute', 'gain'):
        if name not in payload:
            continue
        spec = camera_control_specs[name]
        value = parse_int(payload[name], name, spec['min'], spec['max'])
        controls.append(f'{name}={value}')

    if controls:
        run_v4l2_ctl([f'--set-ctrl={",".join(controls)}'])

    return get_camera_settings()

def save_to_disk(data, directory, extension):
    now = datetime.datetime.now()
    os.makedirs(directory, exist_ok=True)
    fn = now.replace(microsecond=0).isoformat() + extension
    fn = fn.replace(':', '-')
    fn = os.path.join(directory, fn)
    with open(fn, 'wb') as f:
        f.write(data)

def report_capture_error(request_id, error):
    try:
        requests.post(
            plotter_error_url,
            json={'request_id': request_id, 'error': error},
            timeout=5,
        ).raise_for_status()
    except requests.RequestException as e:
        log('camera> failed to report capture error', e)

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
        self.cap_lock = threading.Lock()
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
        with self.cap_lock:
            ret, img = self.cap.read()
        timings['photo_received_at'] = time.perf_counter()
        if not ret:
            log('camera> capture failed')
            report_capture_error(request_id, 'camera capture failed')
            return

        log('camera> convert full frame to jpg for post')
        ok, encimg = cv2.imencode('.jpg', img, encode_param)
        timings['photo_encoded_at'] = time.perf_counter()
        if not ok:
            log('camera> jpg encode failed')
            report_capture_error(request_id, 'camera jpg encode failed')
            return

        save_to_disk(encimg, 'images', '.jpg')

        # Send the image to the local plotter service. The plotter owns remote
        # processing so manual uploads and camera captures share one path.
        data = encimg.tobytes()
        files = {
            'image': ('capture.jpg', data, 'image/jpeg'),
        }
        try:
            log('camera> post jpg to plotter')
            timings['plotter_request_started_at'] = time.perf_counter()
            response = requests.post(
                plotter_capture_image_url,
                data={
                    'request_id': request_id,
                    'timings': json.dumps(summarize_timings(timings)),
                },
                files=files,
                timeout=request_timeout,
            )
            timings['plotter_response_received_at'] = time.perf_counter()
            response.raise_for_status()
            log('camera> plotter accepted capture image')
        except requests.exceptions.ConnectionError:
            log('camera> connection error')
            report_capture_error(request_id, 'plotter image post connection error')
        except requests.exceptions.Timeout:
            log('camera> request timeout')
            report_capture_error(request_id, 'plotter image post timeout')
        except requests.exceptions.HTTPError as e:
            log('camera> http error', e)
            # Plotter HTTP errors are expected to include its own capture-state
            # update; avoid reporting a second failure for the same request.
            pass

    def preview_jpeg(self):
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        with self.cap_lock:
            ret, img = self.cap.read()
        if not ret:
            raise RuntimeError('camera preview capture failed')
        ok, encimg = cv2.imencode('.jpg', img, encode_param)
        if not ok:
            raise RuntimeError('camera preview jpg encode failed')
        return encimg.tobytes()

    def run(self):
        while not self.shutdown.is_set():
            # run through the buffer to stay up to date
            with self.cap_lock:
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
    summary = {
        'request_id': timings['request_id'],
        'photo_trigger_to_receive_ms': (timings['photo_received_at'] - timings['trigger_received_at']) * 1000,
        'photo_receive_to_encoded_ms': (timings['photo_encoded_at'] - timings['photo_received_at']) * 1000,
        'photo_encoded_to_plotter_request_started_ms': (
            timings['plotter_request_started_at'] - timings['photo_encoded_at']
        ) * 1000,
    }
    if 'plotter_response_received_at' in timings:
        summary['plotter_round_trip_ms'] = (
            timings['plotter_response_received_at'] - timings['plotter_request_started_at']
        ) * 1000
    return summary

@app.route('/shutter')
def shutter():
    request_id = request.args.get('request_id') or str(uuid.uuid4())
    camera.shutter.put({
        'request_id': request_id,
        'trigger_received_at': time.perf_counter(),
    })
    return {'request_id': request_id}, 202

@app.route('/status')
def status():
    return {'ready': True}

@app.route('/preview.jpg')
def preview():
    try:
        data = camera.preview_jpeg()
    except RuntimeError as e:
        log('camera> preview failed', e)
        return {'error': str(e)}, 503
    return Response(data, mimetype='image/jpeg')

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    try:
        if request.method == 'POST':
            return set_camera_settings(request.get_json(silent=True) or {})
        return get_camera_settings()
    except ValueError as e:
        log('camera> invalid settings', e)
        return {'error': str(e)}, 400
    except RuntimeError as e:
        log('camera> settings failed', e)
        return {'error': str(e)}, 502

serve(app, listen='*:8081')
camera.join()
