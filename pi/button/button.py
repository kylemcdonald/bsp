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
last_status_poll = 0
button_url = 'http://localhost:8080/button'
status_url = 'http://localhost:8080/status'

led = LED(led_pin)
led.on()

def get_json(url):
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        if response.content:
            return response.json()
    except requests.RequestException as e:
        print('button request failed', e, flush=True)
    except requests.exceptions.JSONDecodeError as e:
        print('button JSON response failed', e, flush=True)
    return None

def get(url):
    get_json(url)

def apply_status(payload):
    global button_light_enabled, plotter_state
    if not isinstance(payload, dict):
        return
    plotter_state = payload.get('state', plotter_state)
    button_light_enabled = bool(payload.get('button_light', True))
    if shutdown_requested:
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
    apply_status(get_json(status_url))

def button_hold(now, seconds):
    global shutdown_requested
    if seconds > 3 and not shutdown_requested:
        shutdown_requested = True
        print('button hold')
        led.blink(.05, .5)
        get('http://localhost:8080/home')
        time.sleep(2)
        subprocess.call(['sudo', '/usr/sbin/shutdown', '-h', 'now'], shell=False)
    
def button_release(now, seconds):
    if shutdown_requested:
        return
    if not button_light_enabled:
        print('button release ignored while light is off')
        return
    print('button release')
    if plotter_state == 'HOME':
        led.off()
        apply_status({'button_light': False, 'state': 'CAPTURING'})
    payload = get_json(button_url)
    if payload is None:
        apply_status({'button_light': True, 'state': plotter_state})
    else:
        apply_status(payload)

while True:
    cur_active = button.is_active
    current_time = time.monotonic()
    poll_status(current_time)
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
