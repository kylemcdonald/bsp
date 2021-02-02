import os
import subprocess

from tempfile import TemporaryDirectory

import cv2
import numpy as np


def histogram_equalize(data, max_val=None, endpoint=False):
    input_shape = np.shape(data)
    data_flat = np.asarray(data).flatten()
    if max_val is None:
        max_val = data_flat.max()
    indices = np.argsort(data_flat)
    replacements = np.linspace(0, max_val, len(indices), endpoint=endpoint)
    data_flat[indices] = replacements
    return data_flat.reshape(*input_shape)

def _cld(gray, halfw = 8,smoothPasses = 4, sigma1 = .9, sigma2 = 3, tau = .97):
    name = 'cld_tmp_'
    cv2.imwrite(f'{name}_in.bmp', gray)
    if os.name == 'nt':
        wsl = 'wsl '
    else:
        wsl = ''
    subprocess.check_call(f'{wsl}./cld --src {name}_in.bmp --output {name}_out.bmp --ETF_kernel {halfw} --ETF_iter {smoothPasses} --sigma_c {sigma1} --sigma_m {sigma2} --tau {tau}', shell=True)
    return cv2.imread(f'{name}_out.bmp', cv2.IMREAD_GRAYSCALE)

def raster_edges(gray, histogram_eq=False, cld=True, canny_low=100, canny_hi=200):
    if histogram_eq:
        gray = histogram_equalize(gray)

    edges = 255 - cv2.Canny(gray, canny_low, canny_hi)

    if cld:
        edges &= _cld(gray)

    return edges