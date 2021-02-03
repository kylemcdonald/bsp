#!/usr/bin/python3
import time
import datetime
from gpiozero import InputDevice, LED
import subprocess
import requests

button_pin = 3
led_pin = 4

button = InputDevice(button_pin, pull_up=True)
last_active = False
last_press = None

led = LED(led_pin)
led.on()

def button_hold(now, seconds):
    if seconds > 3:
        led.blink(.05, .5)
        requests.get('http://localhost:8080/home')
        time.sleep(2)
        subprocess.call(['shutdown', '-h', 'now'], shell=False)
    
def button_release(now, seconds):
    requests.get('http://localhost:8080/button')

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