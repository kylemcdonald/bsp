import cv2
import time
import numpy as np
from wait_for_format import wait_for_format

def capture(cap):
    while True:
        ret, frame = cap.read()
        yield frame


def progress(itr, update_interval=1):
    start_time = None
    last_time = None
    for i, x in enumerate(itr):
        cur_time = time.time()
        if start_time is None:
            start_time = cur_time
            last_time = cur_time
        yield x
        if cur_time - last_time > update_interval:
            duration = cur_time - start_time
            speed = (i + 1) / duration
            print(round(speed, 1), 'fps')
            last_time = cur_time

if __name__ == '__main__':
    
    fourcc = 'MJPG'
    width = 1920*2
    height = 1080*2
    fps = 5

    cap = wait_for_format(fourcc, width, height, fps)

    try:
        for i,e in enumerate(progress(capture(cap))):
            if i % 20 == 0:
                cv2.imwrite(f'out.jpg', e)
                print(e.shape)
            continue
    except KeyboardInterrupt:
        pass