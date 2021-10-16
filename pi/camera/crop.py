import numpy as np

def safe_crop(arr, tblr, fill=None):
    n,s,w,e = tblr
    shape = np.asarray(arr.shape)
    shape[:2] = s - n, e - w
    no, so, wo, eo = 0, shape[0], 0, shape[1]
    if n < 0:
        no += -n
        n = 0
    if w < 0:
        wo += -w
        w = 0
    if s >= arr.shape[0]:
        so -= s - arr.shape[0]
        s = arr.shape[0]
    if e >= arr.shape[1]:
        eo -= e - arr.shape[1]
        e = arr.shape[1]
    cropped = arr[n:s,w:e]
    if fill is None:
        return cropped
    out = np.empty(shape, dtype=arr.dtype)
    out.fill(fill)
    try:
        out[no:so,wo:eo] = cropped
    except ValueError:
        # this happens when there is no overlap
        pass
    return out