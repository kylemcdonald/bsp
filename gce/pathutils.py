import numpy as np
from scipy.ndimage import gaussian_filter1d

def remove_consecutive_duplicates(path):
    use = np.any(path[1:] != path[:-1], 1)
    return path[np.hstack((True, use))]

def resample_path(path, spacing):
    resampled = [path[0]]
    cur_point = path[0].copy()
    cur_index = 0
    n = len(path)
    diffs = path[1:] - path[:-1]
    distances = np.sqrt(np.sum(diffs ** 2, 1))
    directions = diffs / distances.reshape(-1,1)
    remaining_in_input = distances[0]
    remaining_in_output = spacing
    while cur_index + 1 < n:
        if remaining_in_input > remaining_in_output:
            cur_point += directions[cur_index] * remaining_in_output
            resampled.append(cur_point.copy())
            remaining_in_input -= remaining_in_output
            remaining_in_output = spacing
        else:
            remaining_in_output -= remaining_in_input
            cur_index += 1
            if cur_index + 1 == n:
                break
            remaining_in_input = distances[cur_index]
            cur_point = path[cur_index]
    return resampled

def smooth_path(path, sigma=1.0):
    return gaussian_filter1d(path, sigma=sigma, axis=0)