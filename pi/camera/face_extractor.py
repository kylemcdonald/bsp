import dlib
import cv2
import numpy as np

def imresize(img, scale=None, output_wh=None):
    if scale is not None:
        h,w = img.shape[:2]
        output_wh = (int(w * scale), int(h * scale))
    return cv2.resize(img, output_wh, interpolation=cv2.INTER_AREA) # INTER_AREA adds 10ms

class FaceExtractor:
    def __init__(self, downsample=6, output_wh=(256, 256), scale=600, default_center=(1920,980)):
        self.face_detector = dlib.get_frontal_face_detector()
        self.downsample = downsample
        self.output_wh = output_wh
        self.scale = scale
        self.default_center = default_center
        
    def __call__(self, img):
        sub = imresize(img, scale=1/self.downsample)
        rects = self.face_detector(sub, 0)
        if len(rects) == 0:
            print('not found')
            center = self.default_center
        else:
            print('found')
            rect = rects[0]
            center = rect.center().x, rect.center().y
            center = np.asarray(center) * self.downsample
        x,y = center
        t,b,l,r = (y-self.scale,y+self.scale,x-self.scale,x+self.scale)
        resized = imresize(img[t:b,l:r], output_wh=self.output_wh)
        return resized