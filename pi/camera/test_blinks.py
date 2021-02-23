import numpy as np
import cv2
from eye_extractor import EyeExtractor
from blink_detector import BlinkDetector
from wait_for_format import wait_for_format
from flushed import log

import time
class Hysteresis:
    def __init__(self, rising_time=1, falling_time=0.1):
        self.rising_time = rising_time
        self.falling_time = falling_time
        self.last_change_time = None
        self.last_state = False
        self.latched_state = False

    def __call__(self, state):
        now = time.time()
        if self.last_state != state:
            self.last_change_time = now
            self.last_state = state
        duration = self.last_change_time - now
        if state and duration > self.rising_time:
            self.latched_state = True
        elif not state and duration > self.falling_time:
            self.latched_state = False
        return self.latched_state

def inner_square_crop(img):
    size = np.asarray(img.shape[:2])
    min_side = min(size)
    corner = (size - min_side) // 2
    return img[corner[0]:corner[0]+min_side, corner[1]:corner[1]+min_side]

def run(img):
    sub = inner_square_crop(img)
    eyes = eye_extractor(sub)
    if eyes is None:
        return
    blink = blink_detector(eyes)
    n = 80
    i = int(blink * n)
    msg = '*' * i
    msg += '_' * (n-i)
    log(msg)

    base_scale = 6
    points = eyes['points']
    center = points.mean(0)
    distances = np.sqrt(np.square(points - center).max(1))
    scale = distances.mean() * base_scale

    offset = np.subtract(img.shape, sub.shape)[:2] / 2
    img_center = (center[::-1] + offset)
    scale = int(scale)
    t,l = (img_center - (scale, scale)).astype(int)
    b,r = (t + scale * 2, l + scale * 2)

    # todo: safe crop to guarantee edges
    to_draw = img[t:b,l:r]

    # cv2.imwrite('out.jpg', to_draw)

if __name__ == '__main__':

    from test_fps import progress, capture

    fourcc = 'MJPG'
    width = 1920*2
    height = 1080*2
    fps = 5

    log('waiting for availability')
    cap = wait_for_format(fourcc, width, height, fps)
    log('camera is available')

    log('loading eye extractor and blink detector')
    eye_extractor = EyeExtractor()
    blink_detector = BlinkDetector()
    log('loaded')

    try:
        for i,e in enumerate(progress(capture(cap))):
            if i % 20 == 0:
                log(e.shape)

            run(e)
            
    except KeyboardInterrupt:
        pass