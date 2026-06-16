#!/usr/bin/python3
import time
import datetime
from gpiozero import InputDevice, LED
import subprocess
import requests

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
last_flash_toggle = 0
flash_on = False
button_url = 'http://localhost:8080/button'
status_url = 'http://localhost:8080/status'
camera_status_url = 'http://localhost:8081/status'
flash_interval = 0.25
error_flash_interval = 0.05
shutdown_hold_seconds = 5

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
    global button_light_enabled, plotter_last_error, plotter_ready, plotter_state
    if not isinstance(payload, dict):
        plotter_ready = False
        return
    plotter_state = payload.get('state', plotter_state)
    plotter_last_error = payload.get('last_error', plotter_last_error)
    plotter_ready = bool(payload.get('connected', plotter_ready))
    button_light_enabled = bool(payload.get('button_light', True))

def services_ready():
    return plotter_ready and camera_ready

def update_led(now):
    global last_flash_toggle, flash_on
    if shutdown_requested:
        return

    if not services_ready() or plotter_state == 'CAPTURING' or plotter_last_error:
        interval = error_flash_interval if services_ready() and plotter_last_error else flash_interval
        if now - last_flash_toggle >= interval:
            last_flash_toggle = now
            flash_on = not flash_on
            if flash_on:
                led.on()
            else:
                led.off()
        return

    if button_light_enabled:
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

def button_hold(now, seconds):
    global shutdown_requested
    if seconds > shutdown_hold_seconds and not shutdown_requested:
        shutdown_requested = True
        print('button hold')
        led.blink(.05, .5)
        get('http://localhost:8080/home')
        time.sleep(2)
        subprocess.call(['sudo', '/usr/sbin/shutdown', '-h', 'now'], shell=False)
    
def button_release(now, seconds):
    global last_flash_toggle, flash_on, plotter_last_error
    if shutdown_requested:
        return
    if not services_ready():
        print('button release ignored while services are not ready')
        return
    if not button_light_enabled:
        print('button release ignored while light is off')
        return
    print('button release')
    if plotter_state == 'HOME':
        apply_status({'button_light': False, 'last_error': None, 'state': 'CAPTURING'})
        last_flash_toggle = time.monotonic()
        flash_on = True
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
    update_led(current_time)
    now = datetime.datetime.now()
    if cur_active and not last_active:
        last_press = now
    if cur_active: 
        duration = now - last_press
        button_hold(now, duration.total_seconds())
    if not cur_active and last_active:
        duration = now - last_press
        button_release(now, duration.total_seconds())
    last_active = cur_active
    time.sleep(1/60)
