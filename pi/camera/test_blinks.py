import numpy as np
import cv2
from eye_extractor import EyeExtractor
from blink_detector import BlinkDetector
from wait_for_format import wait_for_format
from flushed import log

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
    log(blink)

    # base_scale = 6
    # points = eyes['points']
    # center = points.mean(0)
    # distances = np.sqrt(np.square(points - center).max(1))
    # scale = distances.mean() * base_scale

    # offset = np.subtract(img.shape, sub.shape)[:2] / 2
    # img_center = (center[::-1] + offset)
    # t,l = (img_center - (scale, scale)).astype(int)
    # b,r = (img_center + (scale, scale)).astype(int)
    # to_draw = img[t:b,l:r] # would be better to safe crop here

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