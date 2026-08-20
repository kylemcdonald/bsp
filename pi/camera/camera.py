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
from glob import glob

import requests
from flask import Flask, Response, request
from waitress import serve

from flushed import log
from wait_for_format import wait_for_format

plotter_capture_image_url = os.environ.get('BSP_PLOTTER_CAPTURE_IMAGE_URL', 'http://localhost:8080/capture-image')
plotter_error_url = os.environ.get('BSP_PLOTTER_CAPTURE_ERROR_URL', 'http://localhost:8080/capture-error')
jpeg_quality = 50
request_timeout = 120
camera_device_override = os.environ.get('BSP_CAMERA_DEVICE')
camera_fourcc = os.environ.get('BSP_CAMERA_FOURCC', 'MJPG')

def parse_env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ('1', 'true', 'yes', 'on'):
        return True
    if normalized in ('0', 'false', 'no', 'off'):
        return False
    raise RuntimeError(f'{name} must be true or false')

def parse_env_int(name, default, min_value):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        raise RuntimeError(f'{name} must be an integer')
    if parsed < min_value:
        raise RuntimeError(f'{name} must be at least {min_value}')
    return parsed

def parse_env_float(name, default, min_value):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        raise RuntimeError(f'{name} must be a number')
    if parsed < min_value:
        raise RuntimeError(f'{name} must be at least {min_value}')
    return parsed

camera_width = parse_env_int('BSP_CAMERA_WIDTH', 3840, 1)
camera_height = parse_env_int('BSP_CAMERA_HEIGHT', 2160, 1)
camera_fps = parse_env_float('BSP_CAMERA_FPS', 5, 0.1)
camera_grab_interval_seconds = parse_env_float(
    'BSP_CAMERA_GRAB_INTERVAL_SECONDS',
    1.0 / camera_fps,
    0,
)
camera_keep_open = parse_env_bool('BSP_CAMERA_KEEP_OPEN', True)

log('using plotter capture image endpoint', plotter_capture_image_url)
log('using plotter capture error endpoint', plotter_error_url)
log(
    'using camera format',
    f'{camera_fourcc} {camera_width} x {camera_height} @ {camera_fps:g}fps',
    f'idle_grab_interval={camera_grab_interval_seconds:g}s',
    f'keep_open={camera_keep_open}',
)

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
    port = camera.current_camera_port()
    if port is None:
        raise RuntimeError('camera is not connected')
    command = ['v4l2-ctl', f'--device={port}', *args]
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

def find_camera_port():
    if camera_device_override:
        return camera_device_override
    for path in sorted(glob('/dev/v4l/by-id/*')):
        # Prefer real USB camera nodes over the Pi codec/ISP virtual devices.
        if os.path.exists(path):
            return path
    return '/dev/video0'

def camera_port_available(port):
    if not isinstance(port, str):
        return True
    return os.path.exists(port)

class Camera(threading.Thread):
    def __init__(self):
        super().__init__()

        self.fourcc = camera_fourcc
        self.width = camera_width
        self.height = camera_height
        self.fps = camera_fps
        self.grab_interval_seconds = camera_grab_interval_seconds
        self.keep_open = camera_keep_open
        self.cap = None
        self.current_port = None
        self.cap_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.available = False
        self.last_error = 'camera not connected'
        self.shutdown = threading.Event()
        self.shutter = queue.Queue()

        log('camera> waiting for availability')
        if self.keep_open:
            self.reconnect()
        else:
            self.probe_available()
        self.start()

    def set_available(self, available, error=None):
        with self.status_lock:
            self.available = available
            self.last_error = error

    def status(self):
        if not self.keep_open:
            self.probe_available()
        with self.status_lock:
            return {
                'ready': self.available,
                'error': self.last_error,
            }

    def probe_available(self):
        port = find_camera_port()
        if not camera_port_available(port):
            with self.cap_lock:
                if self.cap is None:
                    self.current_port = None
            self.set_available(False, 'camera is not connected')
            return False
        with self.cap_lock:
            self.current_port = port
        self.set_available(True)
        return True

    def current_camera_port(self):
        with self.cap_lock:
            port = self.current_port
        if port is not None and camera_port_available(port):
            return port
        if self.probe_available():
            with self.cap_lock:
                return self.current_port
        return None

    def open_camera_locked(self):
        port = find_camera_port()
        if not camera_port_available(port):
            self.current_port = None
            self.set_available(False, 'camera is not connected')
            return None
        cap = wait_for_format(self.fourcc, self.width, self.height, self.fps, port=port, max_attempts=1)
        if cap is None:
            self.current_port = None
            self.set_available(False, 'camera is not connected')
            return None
        self.current_port = port
        self.set_available(True)
        return cap

    def read_frame(self):
        temporary_cap = None
        with self.cap_lock:
            cap = self.cap
            if cap is None:
                cap = self.open_camera_locked()
                temporary_cap = cap
            ret, img = cap.read() if cap is not None else (False, None)
            if temporary_cap is not None:
                temporary_cap.release()
        return ret, img

    def reconnect(self):
        port = find_camera_port()
        cap = wait_for_format(self.fourcc, self.width, self.height, self.fps, port=port)
        with self.cap_lock:
            old_cap = self.cap
            self.cap = cap
            self.current_port = port
        if old_cap is not None:
            old_cap.release()
        self.set_available(True)
        log('camera> camera is available')

    def mark_disconnected(self, error):
        with self.cap_lock:
            cap = self.cap
            self.cap = None
            self.current_port = None
        if cap is not None:
            cap.release()
        self.set_available(False, error)
        log('camera>', error)

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
        ret, img = self.read_frame()
        timings['photo_received_at'] = time.perf_counter()
        if not ret:
            log('camera> capture failed')
            self.mark_disconnected('camera capture failed')
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
        ret, img = self.read_frame()
        if not ret:
            self.mark_disconnected('camera preview capture failed')
            raise RuntimeError('camera preview capture failed')
        ok, encimg = cv2.imencode('.jpg', img, encode_param)
        if not ok:
            raise RuntimeError('camera preview jpg encode failed')
        return encimg.tobytes()

    def run(self):
        while not self.shutdown.is_set():
            if not self.keep_open:
                try:
                    request = self.shutter.get(timeout=0.2)
                    self.capture(request['request_id'], request['trigger_received_at'])
                except queue.Empty:
                    self.probe_available()
                continue

            if self.cap is None:
                self.reconnect()
                continue

            # run through the buffer to stay up to date
            with self.cap_lock:
                cap = self.cap
                ret = cap.grab() if cap is not None else False
            if not ret:
                self.mark_disconnected('camera disconnected')
                continue

            # watch for button presses
            try:
                request = self.shutter.get_nowait()
                self.capture(request['request_id'], request['trigger_received_at'])
            except queue.Empty:
                if self.grab_interval_seconds > 0:
                    time.sleep(self.grab_interval_seconds)
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
    status = camera.status()
    if not status['ready']:
        return {'ready': False, 'error': status['error']}, 503
    request_id = request.args.get('request_id') or str(uuid.uuid4())
    camera.shutter.put({
        'request_id': request_id,
        'trigger_received_at': time.perf_counter(),
    })
    return {'request_id': request_id}, 202

@app.route('/status')
def status():
    status = camera.status()
    if not status['ready']:
        return status, 503
    return status

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
