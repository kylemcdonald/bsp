#!/usr/bin/python3
import json
import os
import serial
import warnings
import threading
import time
import queue
import time
import uuid
from collections import deque
from enum import Enum
from urllib.parse import urlparse

import requests
import flask
from flask import Flask
from waitress import serve
from motion import DEFAULT_EPSILON_MM, DEFAULT_ROTATE_180, plan_path
from serial.tools import list_ports

home_position = (50, 65)
limit_position = (100, 100)
camera_url = os.environ.get('BSP_CAMERA_SHUTTER_URL', 'http://localhost:8081/shutter')
camera_preview_url = os.environ.get('BSP_CAMERA_PREVIEW_URL', 'http://localhost:8081/preview.jpg')
camera_settings_url = os.environ.get('BSP_CAMERA_SETTINGS_URL', 'http://localhost:8081/settings')
api_base_url = (os.environ.get('BSP_VIBECHECK_URL') or 'http://vibecheck.taildd340.ts.net:8787').rstrip('/')
process_url = os.environ.get('BSP_PROCESS_URL') or f'{api_base_url}/api/process'
process_url_lock = threading.Lock()
tinyg_port = os.environ.get('BSP_TINYG_PORT')
tinyg_motion_params = {
    'xjm': 2000,
    'yjm': 2000,
    'xvm': 3000,
    'yvm': 3000,
}
post_draw_home_delay_seconds = 10
tinyg_idle_status = 3
tinyg_idle_poll_interval_seconds = 0.25
tinyg_idle_timeout_seconds = 120
tinyg_reconnect_interval_seconds = 2
tinyg_read_timeout_disconnect_count = 5
tinyg_health_poll_interval_seconds = 1
tinyg_health_fail_disconnect_count = 3
request_timeout = 120

State = Enum('State', 'HOME POSITIONED CENTERING RETURNING_HOME CAPTURING READY DRAWING POSTDRAW ERROR')

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
        self.port_override = port
        self.port = port
        self.baudrate = baudrate
        self.ser = FakeSerial()
        self.connected = False
        self.queue = queue.Queue()
        self.shutdown = threading.Event()
        self.clear = threading.Event()
        self.state = State.ERROR
        self.ready = True
        self.pending_path = None
        self.pending_capture = None
        self.last_capture_timings = None
        self.last_error = None
        self.return_home_after_clear = False
        self.active_draw = None
        self.next_reconnect_at = 0
        self.read_timeout_count = 0
        self.next_health_check_at = 0
        self.health_fail_count = 0

        if self.connect():
            self.center()

        self.start()

    def center(self):
        # Hit both physical bounds once so the logical center is calibrated.
        log('plotter> center')
        self.clear_queue()
        self.define_position(*home_position)
        self.go(0, 0, state=State.POSITIONED)
        self.go(*limit_position, state=State.POSITIONED)
        self.return_home(state=State.CENTERING)

    def connect(self):
        port = self.port_override or find_tinyg_port()
        if port is None:
            log('plotter> TinyG serial port not available')
            self.last_error = 'TinyG serial port not available'
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
            if b'SYSTEM READY' not in startup:
                raise serial.SerialException('TinyG startup banner not received')
            self.configure_tinyg()
            self.connected = True
            self.last_error = None
            self.read_timeout_count = 0
            self.health_fail_count = 0
            return True
        except serial.SerialException as e:
            log('plotter> serial connection failed', e)
            self.last_error = f'TinyG serial connection failed: {e}'
        except OSError as e:
            log('plotter> serial connection failed', e)
            self.last_error = f'TinyG serial connection failed: {e}'
        self.connected = False
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser = FakeSerial()
        if not self.port_override:
            self.port = None
        return False

    def reconnect(self):
        now = time.monotonic()
        if now < self.next_reconnect_at:
            return False
        self.next_reconnect_at = now + tinyg_reconnect_interval_seconds
        if self.connect():
            # TinyG may have reset, lost motor power, or moved while offline.
            # Re-run startup centering before accepting captures or drawings.
            self.center()
            return True
        self.state = State.ERROR
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
        if not self.port_override:
            self.port = None
        self.state = State.ERROR
        self.pending_path = None
        self.pending_capture = None
        self.last_capture_timings = None
        self.active_draw = None
        self.last_error = 'plotter disconnected'
        self.read_timeout_count = 0
        self.health_fail_count = 0

    def check_tinyg_health(self):
        if self.state not in (State.HOME, State.READY, State.POSITIONED):
            return
        now = time.monotonic()
        if now < self.next_health_check_at:
            return
        self.next_health_check_at = now + tinyg_health_poll_interval_seconds
        idle, stat = self.query_tinyg_idle(response_timeout=0.5)
        if stat is not None:
            self.health_fail_count = 0
            return
        self.health_fail_count += 1
        log('plotter> TinyG health check failed', f'count={self.health_fail_count}')
        if self.health_fail_count >= tinyg_health_fail_disconnect_count:
            log('plotter> TinyG health check failed repeatedly; reconnecting TinyG')
            self.disconnect()
            self.next_reconnect_at = 0

    def clear_queue(self):
        with self.queue.mutex:
            self.queue.queue.clear()

    def can_start_capture(self):
        return self.connected and self.state == State.HOME

    def can_start_draw(self):
        return self.connected and self.state in (State.HOME, State.READY)

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

    def return_home(self, state=State.RETURNING_HOME):
        if self.state == State.HOME:
            # already home
            log('plotter> already at home')
            return
        log('plotter> return home')
        self.go(*home_position, state=state)

    def manual_go(self, x, y):
        if self.state not in (State.HOME, State.POSITIONED):
            raise RuntimeError(f'cannot move while state is {self.state.name}')
        self.last_error = None
        self.go(x, y, state=State.POSITIONED)

    def request_return_home(self):
        if self.state == State.HOME:
            self.last_error = None
            log('plotter> already at home')
            return
        if self.state == State.POSITIONED:
            self.last_error = None
            self.return_home()
            return
        if self.state == State.READY:
            self.last_error = None
            self.pending_path = None
            self.last_capture_timings = None
            self.state = State.HOME
            log('plotter> canceled pending capture and stayed home')
            return
        if self.state in (State.DRAWING, State.POSTDRAW):
            self.reset_to_beginning()
            return
        if self.state in (State.CENTERING, State.RETURNING_HOME):
            self.last_error = None
            log(f'plotter> already {self.state.name.lower()}')
            return
        raise RuntimeError(f'cannot return home while state is {self.state.name}')
        
    def interrupt_motion(self):
        log('plotter> interrupt motion')
        self.clear.set()

    def go(self, x, y, state=State.POSITIONED):
        if not self.connected:
            log('plotter> ignoring go while disconnected')
            return
        x = clamp(x, 'x', 0, limit_position[0])
        y = clamp(y, 'y', 0, limit_position[1])
        log(f'plotter> go {x:.4f} {y:.4f}')
        self.queue.put(('~', 0, None))
        self.queue.put((f'g0x{x:.4f}y{y:.4f}\n', 1, 'go'))
        self.state = state

    def draw(self, commands, stats=None, source='draw'):
        if not self.connected:
            raise RuntimeError('plotter is disconnected')
        self.last_error = None
        self.pending_path = None
        self.pending_capture = None
        self.last_capture_timings = None
        planned_stats = (stats or {}).get('planned', {})
        self.active_draw = {
            'source': source,
            'command_count': len(commands),
            'path_length_mm': planned_stats.get('path_length_mm'),
            'estimated_feed_time_s': planned_stats.get('estimated_feed_time_s'),
            'queued_at': time.monotonic(),
            'accepted_at': None,
        }
        log(
            'plotter> draw queued',
            f'source={source}',
            f'commands={len(commands)}',
            f'length={planned_stats.get("path_length_mm", 0):.1f}mm',
            f'est_feed={planned_stats.get("estimated_feed_time_s", 0):.1f}s',
        )
        for command in commands:
            self.queue.put(f'{command}\n')
        self.state = State.DRAWING

    def begin_capture(self):
        if not self.can_start_capture():
            raise RuntimeError(f'cannot start capture while state is {self.state.name}')
        request_id = str(uuid.uuid4())
        self.pending_path = None
        self.pending_capture = request_id
        self.last_capture_timings = None
        self.last_error = None
        self.state = State.CAPTURING
        return request_id

    def finish_capture(self, request_id, path_payload, timings=None):
        if self.state != State.CAPTURING:
            raise RuntimeError(f'plotter is not waiting for capture result; current state is {self.state.name}')
        if self.pending_capture and request_id and self.pending_capture != request_id:
            raise RuntimeError('capture result request_id did not match active capture')
        self.pending_path = path_payload
        self.pending_capture = None
        self.last_capture_timings = timings
        self.last_error = None
        self.state = State.READY

    def fail_capture(self, request_id=None, error='capture failed'):
        if self.state != State.CAPTURING:
            raise RuntimeError(f'plotter is not waiting for capture result; current state is {self.state.name}')
        if self.pending_capture and request_id and self.pending_capture != request_id:
            raise RuntimeError('capture error request_id did not match active capture')
        log('plotter> capture failed', error)
        self.pending_path = None
        self.pending_capture = None
        self.last_capture_timings = None
        self.last_error = error
        self.state = State.HOME

    def reset_to_beginning(self):
        log('plotter> reset to beginning')
        self.interrupt_motion()
        self.pending_path = None
        self.pending_capture = None
        self.last_capture_timings = None
        self.active_draw = None
        self.last_error = None
        self.return_home_after_clear = True
        self.state = State.RETURNING_HOME
            
    def join(self):
        log('plotter> sending shutdown')
        self.shutdown.set()
        super().join()

    def return_home_after_tinyg_clear(self):
        if not self.return_home_after_clear:
            return
        self.return_home_after_clear = False
        self.return_home()

    def tinyg_status(self, msg):
        try:
            parsed = json.loads(msg.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if 'sr' in parsed:
            return parsed['sr']
        response = parsed.get('r')
        if isinstance(response, dict) and 'sr' in response:
            return response['sr']
        return None

    def query_tinyg_idle(self, response_timeout=2):
        old_timeout = self.ser.timeout
        self.ser.timeout = min(old_timeout or tinyg_idle_poll_interval_seconds, tinyg_idle_poll_interval_seconds)
        try:
            self.ser.write(b'{"sr":null}\n')
            self.ser.flush()
            deadline = time.monotonic() + response_timeout
            while time.monotonic() < deadline:
                msg = self.ser.read_until()
                if not msg:
                    continue
                status = self.tinyg_status(msg)
                if not status:
                    continue
                stat = status.get('stat')
                if stat is None:
                    continue
                return stat == tinyg_idle_status, stat
        finally:
            self.ser.timeout = old_timeout
        return False, None

    def wait_for_tinyg_idle(self, label, timeout=tinyg_idle_timeout_seconds):
        deadline = time.monotonic() + timeout
        next_log = 0
        last_stat = None
        while time.monotonic() < deadline:
            if self.shutdown.is_set() or self.clear.is_set():
                return False
            idle, stat = self.query_tinyg_idle()
            if stat is not None:
                last_stat = stat
            if idle:
                log(f'plotter> TinyG idle after {label}')
                return True
            if time.monotonic() >= next_log:
                log(f'plotter> waiting for TinyG idle after {label}', f'stat={last_stat}')
                next_log = time.monotonic() + 2
            if self.clear.wait(tinyg_idle_poll_interval_seconds):
                return False
        self.last_error = f'timed out waiting for TinyG idle after {label}; last stat={last_stat}'
        log('plotter>', self.last_error)
        self.state = State.ERROR
        return False

    def finish_idle_motion(self):
        if not self.connected or not self.queue.empty():
            return False
        if self.state == State.DRAWING:
            draw = self.active_draw or {}
            now = time.monotonic()
            queued_at = draw.get('queued_at', now)
            draw['accepted_at'] = now
            self.active_draw = draw
            log(
                'plotter> drawing commands accepted, waiting for TinyG idle',
                f'source={draw.get("source", "unknown")}',
                f'commands={draw.get("command_count", 0)}',
                f'queue_accept_s={now - queued_at:.1f}',
                f'est_feed={draw.get("estimated_feed_time_s", 0):.1f}s',
            )
            if self.wait_for_tinyg_idle('draw') and self.state == State.DRAWING and self.queue.empty():
                done_at = time.monotonic()
                accepted_at = draw.get('accepted_at', done_at)
                log(
                    f'plotter> finished drawing, waiting {post_draw_home_delay_seconds}s to return home',
                    f'source={draw.get("source", "unknown")}',
                    f'physical_wait_s={done_at - accepted_at:.1f}',
                    f'total_draw_s={done_at - queued_at:.1f}',
                )
                self.active_draw = None
                self.state = State.POSTDRAW
                if not self.clear.wait(post_draw_home_delay_seconds):
                    self.return_home()
                else:
                    self.state = State.POSITIONED
            return True
        if self.state in (State.CENTERING, State.RETURNING_HOME):
            if self.return_home_after_clear:
                self.return_home_after_tinyg_clear()
                return True
            label = 'centering' if self.state == State.CENTERING else 'return home'
            log(f'plotter> {label} command accepted, waiting for TinyG idle')
            if self.wait_for_tinyg_idle(label) and self.state in (State.CENTERING, State.RETURNING_HOME) and self.queue.empty():
                log(f'plotter> {label} complete')
                self.state = State.HOME
            return True
        return False
        
    # todo: write this part in a way that sends a bunch of commands quickly
    # if there are enough commands to send, and then cleans up the responses
    # when there are no more commands.
    def run(self):
        print('plotter> run')
        blast_size = 4
        read_queue_size = 0
        response_labels = deque()
        queue_previously_empty = True
        while not self.shutdown.is_set():
            time.sleep(0.01)
            if not self.connected:
                self.reconnect()
                self.shutdown.wait(0.25)
                continue
            try:
                if self.clear.is_set():
                    # then send hold and request tinyg queue flush
                    # https://github.com/synthetos/TinyG/wiki/TinyG-Feedhold-and-Resume
                    # The ! and ~ do not emit responses, but % does "{rx:254}".
                    # Resume after flushing so later jog/home commands are not left in feedhold.
                    log(f'plotter> clearing queue')
                    self.clear_queue()
                    read_queue_size = 0
                    response_labels.clear()
                    try:
                        self.ser.reset_input_buffer()
                    except AttributeError:
                        pass
                    self.ser.write(b'!')
                    self.ser.flush()
                    time.sleep(0.1)
                    self.ser.write(b'%')
                    self.ser.flush()
                    clear_deadline = time.monotonic() + 2
                    while time.monotonic() < clear_deadline:
                        msg = self.ser.read_until()
                        if not msg:
                            continue
                        log(f'plotter> clear response {msg!r}')
                        if msg == b'{"rx":254}\n':
                            break
                    self.ser.write(b'~')
                    self.ser.flush()
                    self.clear.clear()
                    self.return_home_after_tinyg_clear()
                    continue
                else:
                    if read_queue_size == 0 and self.finish_idle_motion():
                        continue
                    msg = self.queue.get(timeout=1)
                    queue_previously_empty = False
                if isinstance(msg, tuple):
                    msg, expected_responses, response_label = msg
                else:
                    expected_responses = 1
                    response_label = None
                # log(f'msg> {repr(msg)}')
                self.ser.write(msg.encode('ascii'))
                self.ser.flush()
                read_queue_size += expected_responses
                for _ in range(expected_responses):
                    response_labels.append(response_label)
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
                                response_labels.clear()
                                break
                            read_queue_size -= 1
                            response_label = response_labels.popleft() if response_labels else None
                            if response_label:
                                log(f'plotter> {response_label} response {msg!r}')
                            # log(f'plotter> blast response {repr(msg)}')
                            # this message signifies that the feedhold is finished
                            # and there is nothing left in the read queue, but it 
                            # doesn't necessarily come when the read_queue_size is 1
                            if msg == b'{"rx":254}\n':
                                log(f'plotter> finished at (a)', read_queue_size)
                                read_queue_size = 0
                                self.return_home_after_tinyg_clear()
                    else:
                        msg = self.ser.read_until()
                        if not msg:
                            log('plotter> read timeout')
                            self.read_timeout_count += 1
                            read_queue_size = 0
                            response_labels.clear()
                            if not self.queue.empty() and self.read_timeout_count >= tinyg_read_timeout_disconnect_count:
                                log('plotter> too many read timeouts while streaming; reconnecting TinyG')
                                self.disconnect()
                                self.next_reconnect_at = 0
                            continue
                        self.read_timeout_count = 0
                        read_queue_size -= 1
                        response_label = response_labels.popleft() if response_labels else None
                        if response_label:
                            log(f'plotter> {response_label} response {msg!r}')
                        # log(f'plotter> single response {repr(msg)}')
                        if msg == b'{"rx":254}\n':
                            log(f'plotter> finished at (b)', read_queue_size)
                            read_queue_size = 0
                            self.return_home_after_tinyg_clear()
                if read_queue_size == 0:
                    self.finish_idle_motion()
                    if self.connected and self.queue.empty() and read_queue_size == 0:
                        self.check_tinyg_health()
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
    rotate_180=DEFAULT_ROTATE_180,
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
    plotter.draw(planned['commands'], stats=stats, source=source)
    return planned

def draw_payload(body, source='draw'):
    if not isinstance(body, dict):
        body = {'path': body}
    raw = bool(body.get('raw', False))
    return queue_planned_draw(
        body.get('path', body),
        raw=raw,
        flip_y=bool(body.get('flip_y', not raw)),
        rotate_180=DEFAULT_ROTATE_180,
        epsilon_mm=float(body.get('epsilon_mm', DEFAULT_EPSILON_MM)),
        source=source,
    )

def planned_response(planned):
    return {
        'state': plotter.state.name,
        'stats': planned['stats'],
    }, 200

def count_points(path_payload):
    if not isinstance(path_payload, dict):
        try:
            return len(path_payload)
        except TypeError:
            return None
    if 'coordinates' in path_payload:
        return len(path_payload['coordinates'])
    if 'vector' in path_payload:
        return count_points(path_payload['vector'])
    if 'path' in path_payload:
        return count_points(path_payload['path'])
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

def button_light_on():
    return plotter.state in (State.HOME, State.READY, State.DRAWING, State.POSITIONED)

def get_process_url():
    with process_url_lock:
        return process_url

def set_process_url(next_url):
    global process_url
    if not isinstance(next_url, str):
        raise ValueError('processor endpoint must be a URL string')
    next_url = next_url.strip()
    parsed = urlparse(next_url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('processor endpoint must be an http or https URL')
    if not parsed.path or parsed.path == '/':
        next_url = next_url.rstrip('/') + '/api/process'
    with process_url_lock:
        process_url = next_url
    log('processor-endpoint> set', process_url)
    return process_url

def process_uploaded_capture(upload, request_id, source='photo-upload', initial_timings=None):
    timings = {
        'request_id': request_id,
        'upload_received_at': time.perf_counter(),
    }
    if isinstance(initial_timings, dict):
        timings.update(initial_timings)
    filename = upload.filename or 'upload.jpg'
    mimetype = upload.mimetype or 'application/octet-stream'
    try:
        log(f'{source}> post image to process api')
        timings['server_request_started_at'] = time.perf_counter()
        response = requests.post(
            get_process_url(),
            files={'image': (filename, upload.stream, mimetype)},
            timeout=request_timeout,
        )
        timings['server_response_received_at'] = time.perf_counter()
        response.raise_for_status()
        process_payload = response.json()
        vector_payload = extract_vector_payload(process_payload)
        point_count = count_points(vector_payload)
        result_timings = {
            'request_id': request_id,
            'server_round_trip_ms': (
                timings['server_response_received_at'] - timings['server_request_started_at']
            ) * 1000,
        }
        if 'photo_trigger_to_receive_ms' in timings:
            result_timings['photo_trigger_to_receive_ms'] = timings['photo_trigger_to_receive_ms']
        if 'photo_receive_to_encoded_ms' in timings:
            result_timings['photo_receive_to_encoded_ms'] = timings['photo_receive_to_encoded_ms']
        if 'photo_encoded_to_plotter_request_started_ms' in timings:
            result_timings['photo_encoded_to_plotter_request_started_ms'] = (
                timings['photo_encoded_to_plotter_request_started_ms']
            )
            result_timings['photo_encoded_to_server_request_started_ms'] = (
                timings['photo_encoded_to_plotter_request_started_ms']
                + (timings['server_request_started_at'] - timings['upload_received_at']) * 1000
            )
        plotter.finish_capture(
            request_id,
            vector_payload,
            timings=result_timings,
        )
        log(f'{source}> ready', point_count, 'points')
        return {
            'state': plotter.state.name,
            'button_light': button_light_on(),
            'request_id': request_id,
            'point_count': point_count,
        }, 200
    except requests.exceptions.ConnectionError:
        error = 'capture request connection error'
    except requests.exceptions.Timeout:
        error = 'capture request timeout'
    except requests.exceptions.HTTPError as e:
        error = f'capture request http error: {e}'
    except requests.exceptions.JSONDecodeError:
        error = 'capture response JSON error'
    except ValueError as e:
        error = str(e)
    except RuntimeError as e:
        error = str(e)

    log(f'{source}> failed', error)
    try:
        plotter.fail_capture(request_id, error)
    except RuntimeError as e:
        log(f'{source}> failed to reset capture state', e)
        return {'error': str(e), 'state': plotter.state.name, 'button_light': button_light_on()}, 400
    return {'error': error, 'state': plotter.state.name, 'button_light': button_light_on()}, 502

@app.route('/')
def index():
    with open('index.html') as f:
        response = flask.Response(f.read(), mimetype='text/html')
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.route('/min')
def min_position():
    if not plotter.connected:
        return {'error': 'plotter is disconnected'}, 503
    try:
        plotter.manual_go(0, 0)
    except RuntimeError as e:
        return {'error': str(e), 'state': plotter.state.name, 'button_light': button_light_on()}, 409
    return '',200

@app.route('/max')
def max_position():
    if not plotter.connected:
        return {'error': 'plotter is disconnected'}, 503
    try:
        plotter.manual_go(*limit_position)
    except RuntimeError as e:
        return {'error': str(e), 'state': plotter.state.name, 'button_light': button_light_on()}, 409
    return '',200

@app.route('/home')
def home():
    if not plotter.connected:
        return {'error': 'plotter is disconnected'}, 503
    try:
        plotter.request_return_home()
    except RuntimeError as e:
        return {'error': str(e), 'state': plotter.state.name, 'button_light': button_light_on()}, 409
    return '',200

@app.route('/draw', methods=['POST'])
def draw():
    if not plotter.connected:
        return {'error': 'plotter is disconnected'}, 503
    if not plotter.can_start_draw():
        return {'error': f'cannot draw while state is {plotter.state.name}', 'state': plotter.state.name}, 409
    req = flask.request
    body = req.get_json(silent=True)
    try:
        planned = draw_payload(body)
    except (KeyError, TypeError, ValueError, RuntimeError) as e:
        log('draw> invalid path', e)
        return {'error': str(e)}, 400
    return planned_response(planned)

@app.route('/draw-json', methods=['POST'])
def draw_json():
    if not plotter.connected:
        return {'error': 'plotter is disconnected'}, 503
    if not plotter.can_start_draw():
        return {'error': f'cannot draw while state is {plotter.state.name}', 'state': plotter.state.name}, 409
    upload = flask.request.files.get('json') or flask.request.files.get('file')
    if upload is None or upload.filename == '':
        return {'error': 'missing JSON upload'}, 400
    try:
        body = json.load(upload.stream)
        form = flask.request.form
        options = {}
        if 'raw' in form:
            options['raw'] = form.get('raw') == 'true'
        if 'flip_y' in form:
            options['flip_y'] = form.get('flip_y') == 'true'
        if 'epsilon_mm' in form:
            options['epsilon_mm'] = form.get('epsilon_mm')
        if options:
            body = {'path': body, **options}
        planned = draw_payload(body, source='draw-json')
    except json.JSONDecodeError as e:
        log('draw-json> invalid JSON', e)
        return {'error': 'invalid JSON upload'}, 400
    except (KeyError, TypeError, ValueError, RuntimeError) as e:
        log('draw-json> invalid path', e)
        return {'error': str(e)}, 400
    return planned_response(planned)

@app.route('/shutter')
def shutter():
    log('shutter> pressed')
    if not plotter.can_start_capture():
        return {'error': f'cannot start capture while state is {plotter.state.name}', 'state': plotter.state.name, 'button_light': button_light_on()}, 409
    request_id = plotter.begin_capture()
    try:
        response = requests.get(camera_url, params={'request_id': request_id}, timeout=5)
        response.raise_for_status()
    except requests.RequestException as e:
        log('shutter> camera request failed', e)
        plotter.reset_to_beginning()
        return {'error': str(e)}, 502
    return {'state': plotter.state.name, 'button_light': button_light_on(), 'request_id': request_id}, 202

@app.route('/camera-preview.jpg')
def camera_preview():
    try:
        response = requests.get(camera_preview_url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        log('camera-preview> camera request failed', e)
        return {'error': str(e)}, 502
    return flask.Response(response.content, mimetype=response.headers.get('Content-Type', 'image/jpeg'))

@app.route('/camera-settings', methods=['GET', 'POST'])
def camera_settings():
    try:
        if flask.request.method == 'POST':
            response = requests.post(
                camera_settings_url,
                json=flask.request.get_json(silent=True) or {},
                timeout=5,
            )
        else:
            response = requests.get(camera_settings_url, timeout=5)
        body = response.json()
    except requests.RequestException as e:
        log('camera-settings> camera request failed', e)
        return {'error': str(e)}, 502
    except ValueError as e:
        log('camera-settings> invalid camera response', e)
        return {'error': str(e)}, 502
    if response.status_code >= 400:
        return body, response.status_code
    return body, response.status_code

@app.route('/processor-endpoint', methods=['GET', 'POST'])
def processor_endpoint():
    if flask.request.method == 'POST':
        body = flask.request.get_json(silent=True) or {}
        try:
            endpoint = set_process_url(body.get('url'))
        except ValueError as e:
            log('processor-endpoint> invalid url', e)
            return {'error': str(e), 'url': get_process_url()}, 400
        return {'url': endpoint}, 200
    return {'url': get_process_url()}, 200

@app.route('/photo-upload', methods=['POST'])
def photo_upload():
    log('photo-upload> received')
    if not plotter.can_start_capture():
        return {
            'error': f'cannot start capture while state is {plotter.state.name}',
            'state': plotter.state.name,
            'button_light': button_light_on(),
        }, 409
    upload = flask.request.files.get('image') or flask.request.files.get('file')
    if upload is None or upload.filename == '':
        return {'error': 'missing image upload'}, 400
    request_id = plotter.begin_capture()
    return process_uploaded_capture(upload, request_id)

@app.route('/capture-image', methods=['POST'])
def capture_image():
    log('capture-image> received')
    request_id = flask.request.form.get('request_id')
    if not request_id:
        return {'error': 'missing request_id'}, 400
    upload = flask.request.files.get('image') or flask.request.files.get('file')
    if upload is None or upload.filename == '':
        try:
            plotter.fail_capture(request_id, 'missing capture image upload')
        except RuntimeError as e:
            log('capture-image> invalid missing-image report', e)
            return {'error': str(e), 'state': plotter.state.name, 'button_light': button_light_on()}, 400
        return {'error': 'missing capture image upload'}, 400
    raw_timings = flask.request.form.get('timings')
    try:
        timings = json.loads(raw_timings) if raw_timings else None
    except json.JSONDecodeError as e:
        log('capture-image> invalid timings JSON', e)
        timings = None
    return process_uploaded_capture(upload, request_id, source='capture-image', initial_timings=timings)

@app.route('/capture-result', methods=['POST'])
def capture_result():
    body = flask.request.get_json(silent=True) or {}
    path_payload = body.get('path') or body.get('vector') or body.get('process_response')
    request_id = body.get('request_id')
    try:
        if count_points(path_payload) is None:
            raise ValueError('capture result did not contain path points')
        plotter.finish_capture(request_id, path_payload, timings=body.get('timings'))
    except (TypeError, ValueError, RuntimeError) as e:
        log('capture-result> invalid result', e)
        return {'error': str(e)}, 400
    point_count = count_points(path_payload)
    log('capture-result> ready', point_count, 'points')
    return {'state': plotter.state.name, 'button_light': button_light_on(), 'point_count': point_count}, 200

@app.route('/capture-error', methods=['POST'])
def capture_error():
    body = flask.request.get_json(silent=True) or {}
    request_id = body.get('request_id')
    error = body.get('error') or 'capture failed'
    try:
        plotter.fail_capture(request_id, error)
    except RuntimeError as e:
        log('capture-error> invalid error report', e)
        return {'error': str(e), 'state': plotter.state.name, 'button_light': button_light_on()}, 400
    return {'state': plotter.state.name, 'button_light': button_light_on(), 'error': plotter.last_error}, 200

@app.route('/button')
def button():
    log('button> pressed')
    if plotter.state == State.HOME:
        log('button> shutter()')
        return shutter()
    elif plotter.state == State.CAPTURING:
        log('button> ignored while capture is running')
        return {'state': plotter.state.name, 'button_light': button_light_on(), 'ignored': True}, 200
    elif plotter.state == State.READY:
        log('button> draw pending capture')
        try:
            planned = draw_payload({'path': plotter.pending_path}, source='capture')
            plotter.pending_path = None
        except (KeyError, TypeError, ValueError, RuntimeError) as e:
            log('button> pending capture invalid', e)
            return {'error': str(e), 'state': plotter.state.name, 'button_light': button_light_on()}, 400
        body, status = planned_response(planned)
        body['button_light'] = button_light_on()
        return body, status
    elif plotter.state == State.DRAWING:
        log('button> reset()')
        plotter.reset_to_beginning()
    elif plotter.state == State.POSITIONED:
        log('button> return home from positioned')
        plotter.request_return_home()
    elif plotter.state == State.POSTDRAW:
        log('button> ignored while post-draw delay is running')
        return {'state': plotter.state.name, 'button_light': button_light_on(), 'ignored': True}, 200
    elif plotter.state == State.CENTERING:
        log('button> ignored while centering')
        return {'state': plotter.state.name, 'button_light': button_light_on(), 'ignored': True}, 200
    elif plotter.state == State.RETURNING_HOME:
        log('button> ignored while returning home')
        return {'state': plotter.state.name, 'button_light': button_light_on(), 'ignored': True}, 200
    return {'state': plotter.state.name, 'button_light': button_light_on()}, 200

@app.route('/pending-path')
def pending_path():
    if plotter.pending_path is None:
        return {'error': 'no pending path'}, 404
    return {'path': plotter.pending_path}, 200

@app.route('/status')	
def status():
    return {
        'state': plotter.state.name,
        'connected': plotter.connected,
        'port': plotter.port,
        'button_light': button_light_on(),
        'pending_capture': plotter.pending_capture,
        'has_pending_path': plotter.pending_path is not None,
        'last_capture_timings': plotter.last_capture_timings,
        'last_error': plotter.last_error,
        'processor_endpoint': get_process_url(),
    }

serve(app, listen='*:8080')
plotter.join()
