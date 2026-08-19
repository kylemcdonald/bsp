#!/usr/bin/python3
import datetime
import socket
import subprocess
import time
from urllib.parse import urlparse

from gpiozero import InputDevice, LED
import requests

from led_feedback import (
    PATTERNS,
    led_pattern_on,
    runpod_processor_ready,
    service_feedback_pattern,
)

# RPI enumeration is:
# pin 5 & 6 are used for the button (3 & ground)
# pin 7 & 9 are used for the LED (4 & ground)

button_pin = 3
led_pin = 4

button = InputDevice(button_pin, pull_up=True)
last_active = False
last_press = None
shutdown_requested = False
button_light_enabled = True
plotter_state = None
plotter_last_error = None
plotter_ready = False
camera_ready = False
last_status_poll = 0
last_camera_poll = 0
last_network_poll = 0
network_ready = False
processor_endpoint = None
runpod_status = None
runpod_desired_running = None
led_pattern_name = None
led_pattern_started = 0
restart_ready_logged = False
restart_requested = False
button_url = 'http://localhost:8080/button'
status_url = 'http://localhost:8080/status'
camera_status_url = 'http://localhost:8081/status'
network_probe_timeout = 0.5
restart_hold_seconds = 5
shutdown_hold_seconds = 10

led = LED(led_pin)
led.off()

def get_json(url, timeout=1, log_errors=True):
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        if response.content:
            return response.json()
    except requests.RequestException as e:
        if log_errors:
            print('button request failed', e, flush=True)
    except requests.exceptions.JSONDecodeError as e:
        if log_errors:
            print('button JSON response failed', e, flush=True)
    return None

def get(url):
    get_json(url)

def apply_status(payload):
    global button_light_enabled, plotter_last_error, plotter_ready, plotter_state, processor_endpoint
    global runpod_desired_running, runpod_status
    if not isinstance(payload, dict):
        plotter_ready = False
        return
    plotter_state = payload.get('state', plotter_state)
    plotter_last_error = payload.get('last_error', plotter_last_error)
    plotter_ready = bool(payload.get('connected', plotter_ready))
    processor_endpoint = payload.get('processor_endpoint', processor_endpoint)
    button_light_enabled = bool(payload.get('button_light', True))
    runpod = payload.get('runpod')
    runpod_status = runpod.get('status') if isinstance(runpod, dict) else None
    runpod_desired_running = runpod.get('desired_running') if isinstance(runpod, dict) else None

def services_ready():
    return (
        network_ready
        and plotter_ready
        and camera_ready
        and runpod_processor_ready(runpod_status)
    )

def has_default_route():
    try:
        with open('/proc/net/route') as f:
            for line in f.readlines()[1:]:
                fields = line.split()
                if len(fields) >= 4 and fields[1] == '00000000' and int(fields[3], 16) & 0x2:
                    return True
    except OSError:
        return False
    return False

def processor_reachable():
    if not processor_endpoint:
        return True
    parsed = urlparse(processor_endpoint)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return True
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=network_probe_timeout):
            return True
    except OSError:
        return False

def check_network():
    if not has_default_route():
        return False
    if not runpod_processor_ready(runpod_status):
        return True
    return processor_reachable()

def current_error_pattern():
    return service_feedback_pattern(
        network_ready,
        camera_ready,
        plotter_ready,
        plotter_state,
        runpod_status,
        runpod_desired_running,
    )

def update_led(now):
    global led_pattern_name, led_pattern_started
    if shutdown_requested:
        return

    if last_press is not None and button.is_active:
        held_seconds = (datetime.datetime.now() - last_press).total_seconds()
        pattern_name = 'restart_ready' if held_seconds >= restart_hold_seconds else None
    else:
        pattern_name = current_error_pattern()
        if pattern_name is None and plotter_state == 'CAPTURING':
            pattern_name = 'capturing'

    if pattern_name is not None:
        if pattern_name != led_pattern_name:
            led_pattern_name = pattern_name
            led_pattern_started = now
            print(f'button> LED pattern {pattern_name}', flush=True)
        if led_pattern_on(PATTERNS[pattern_name], now - led_pattern_started):
            led.on()
        else:
            led.off()
        return

    if led_pattern_name is not None:
        print('button> LED pattern cleared', flush=True)
        led_pattern_name = None
    if button_light_enabled and runpod_processor_ready(runpod_status):
        led.on()
    else:
        led.off()

def poll_status(now):
    global last_status_poll
    if now - last_status_poll < 0.25:
        return
    last_status_poll = now
    apply_status(get_json(status_url, timeout=0.5, log_errors=False))

def poll_camera(now):
    global camera_ready, last_camera_poll
    if now - last_camera_poll < 1:
        return
    last_camera_poll = now
    camera_ready = get_json(camera_status_url, timeout=0.5, log_errors=False) is not None

def poll_network(now):
    global network_ready, last_network_poll
    if now - last_network_poll < 1:
        return
    last_network_poll = now
    network_ready = check_network()

def schedule_service_restart():
    global restart_requested
    if restart_requested:
        return
    restart_requested = True
    print('button> scheduling service restart', flush=True)
    try:
        subprocess.Popen([
            'sudo',
            '/home/ubuntu/bsp/pi/button/restart-services.sh',
        ], shell=False)
    except OSError as e:
        restart_requested = False
        print('button> failed to schedule service restart', e, flush=True)

def button_hold(now, seconds):
    global shutdown_requested, restart_ready_logged
    if seconds >= restart_hold_seconds and not restart_ready_logged:
        restart_ready_logged = True
        print('button> restart armed; release before 10s to restart services', flush=True)
    if seconds >= shutdown_hold_seconds and not shutdown_requested:
        shutdown_requested = True
        print('button> shutdown hold', flush=True)
        led.blink(0.05, 0.5)
        get('http://localhost:8080/home')
        time.sleep(2)
        subprocess.call(['sudo', '/usr/sbin/shutdown', '-h', 'now'], shell=False)
    
def button_release(now, seconds):
    global led_pattern_name, led_pattern_started, plotter_last_error, restart_ready_logged
    if shutdown_requested:
        return
    if seconds >= restart_hold_seconds:
        schedule_service_restart()
        return
    restart_ready_logged = False
    if not services_ready():
        print('button release ignored while services are not ready')
        return
    if not button_light_enabled:
        print('button release ignored while light is off')
        return
    print('button release')
    if plotter_state == 'HOME':
        apply_status({'button_light': False, 'last_error': None, 'state': 'CAPTURING'})
        led_pattern_name = 'capturing'
        led_pattern_started = time.monotonic()
        led.on()
    payload = get_json(button_url)
    if payload is None:
        apply_status({'button_light': True, 'state': plotter_state})
    else:
        apply_status(payload)

while True:
    cur_active = button.is_active
    current_time = time.monotonic()
    poll_status(current_time)
    poll_camera(current_time)
    poll_network(current_time)
    update_led(current_time)
    now = datetime.datetime.now()
    if cur_active and not last_active:
        last_press = now
        restart_ready_logged = False
    if cur_active: 
        duration = now - last_press
        button_hold(now, duration.total_seconds())
    if not cur_active and last_active:
        duration = now - last_press
        button_release(now, duration.total_seconds())
    last_active = cur_active
    time.sleep(1/60)
