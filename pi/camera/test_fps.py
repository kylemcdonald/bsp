import cv2
import time
import numpy as np

fourcc = 'MJPG'
width = 1920*2
height = 1080*2
fps = 5

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
cap.set(cv2.CAP_PROP_FPS, fps)

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

try:
    for i,e in enumerate(progress(capture(cap))):
        if i % 20 == 0:
        #     cv2.imwrite('out.jpg', e)
            print(e.shape)
        continue
except KeyboardInterrupt:
    pass