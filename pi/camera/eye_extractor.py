import dlib
import cv2
import numpy as np

def imresize(img, scale=None, output_wh=None):
    if scale is not None:
        h,w = img.shape[:2]
        output_wh = (int(w * scale), int(h * scale))
    return cv2.resize(img, output_wh, interpolation=cv2.INTER_AREA) # INTER_AREA adds 10ms

def shape_to_points(shape):
    return np.asarray([(e.x, e.y) for e in shape.parts()])

def distance(points):
    return np.sqrt(np.sum(np.square(np.diff(points, axis=0))))

def extract_between_points(img, points, output_wh, scale_factor=0.7):
    center = points.mean(0)
    scale = distance(points) * scale_factor
    aspect = output_wh[1] / output_wh[0]
    l, t = center - (scale, scale * aspect)
    r, b = center + (scale, scale * aspect)
    t,b,l,r = list(map(int, (t,b,l,r)))
    sub = imresize(img[t:b,l:r], output_wh=output_wh)
    return sub, scale

class EyeExtractor:
    def __init__(self, downsample=6, output_wh=(34, 26)):
        self.face_detector = dlib.get_frontal_face_detector()
        self.landmark_detector = dlib.shape_predictor('models/shape_predictor_5_face_landmarks.dat')
        self.downsample = downsample
        self.output_wh = output_wh
        
    def __call__(self, img):
        sub = imresize(img, scale=1/self.downsample)
        rects = self.face_detector(sub, 0)
        if len(rects) == 0:
            return None
        rect = rects[0] # todo: get most central face-sized face
        if hasattr(rect, 'rect'):
            rect = rect.rect # pick rect from CNN
        shape = self.landmark_detector(sub, rect)
        points = shape_to_points(shape) * self.downsample
        left_eye, left_scale = extract_between_points(img, points[:2], self.output_wh)
        right_eye, right_scale = extract_between_points(img, points[2:4], self.output_wh)
        scale = (left_scale + right_scale) / 2
        return {
            'scale': scale,
            'left': left_eye,
            'right': right_eye,
            'points': points
        }