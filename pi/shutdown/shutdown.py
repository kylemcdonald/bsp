#!/usr/bin/python3
import time
import datetime
from gpiozero import InputDevice
import subprocess

def button_hold(now, seconds):
    if seconds > 3:
        print('shutdown')
        subprocess.call(['shutdown', '-h', 'now'], shell=False)
    
def button_release(now, seconds):
    # if seconds > 3:
    #     print('rebooting')
    #     exit()
    pass

pin = 3
button = InputDevice(pin, pull_up=True)
last_active = False
last_press = None

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