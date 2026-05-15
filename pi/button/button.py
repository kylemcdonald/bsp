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

led = LED(led_pin)
led.on()

def get(url):
    try:
        requests.get(url, timeout=5)
    except requests.RequestException as e:
        print('button request failed', e, flush=True)

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
    print('button release')
    get('http://localhost:8080/button')

while True:
    cur_active = button.is_active
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
