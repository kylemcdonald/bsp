import os
import json
import glob
import subprocess

import cv2
import numpy as np
from matplotlib import pyplot as plt
from shapely import geometry as geom

from math import floor

from edges import raster_edges


from centerline.geometry import Centerline
from shapely import ops
import tqdm
def extract_centerlines(shapes):
    shapes = (shape.buffer(0) for shape in shapes)
    polys = [poly for poly in shapes if type(poly) == geom.Polygon and type(poly.envelope) == geom.Polygon]
    centerlines = [Centerline(p, valid=True) for p in polys]

    center_geoms = [line.geoms for line in centerlines]
    center_geom_lines = [geom.MultiLineString(line) for line in center_geoms]
    center_geom_lines = [ops.linemerge(line) for line in center_geom_lines]
    return center_geom_lines


def explode_multilines(lines):
    out = []
    for line in lines:
        if type(line) == geom.multilinestring.MultiLineString:
            out.extend(subline for subline in line)
        else:
            out.append(line)
    return out


def merge_naive(lines):
    all_coords = [list(line.coords) for line in lines]
    flattened = [coord for coords in all_coords for coord in coords]
    return geom.LineString(flattened)


from math import sqrt

def greedy_reorder(lines):
    ''' Reorder list of LineStrings greedily by lowest tail-tip distance'''
    lines = lines[:]
    curr = lines.pop(0)
    out = []
    while len(lines) > 0:
        start_curr = geom.Point(curr.coords[0])
        end_curr = geom.Point(curr.coords[-1])
        dist = float('+inf')
        nearest_tail = None
        for other in lines:
            start_o = geom.Point(other.coords[0])
            end_o = geom.Point(other.coords[-1])
            if end_curr.distance(start_o) < dist:
                dist = end_curr.distance(start_o)
                nearest_tail = other
            elif end_curr.distance(end_o) < dist:
                dist = end_curr.distance(end_o)
                other.coords = list(other.coords)[::-1]
                nearest_tail = other
        lines.remove(nearest_tail)
        out.append(nearest_tail)
        curr = nearest_tail
    return out


def reorder_center_dist(lines):
    bounds = geom.MultiLineString(lines).bounds
    center = geom.Point((bounds[2] - bounds[0])/2, (bounds[3] - bounds[1])/2)
    def dist(line):
        return center.distance(line.centroid)
    return sorted(lines, key=dist)



def reorder_start_dist(lines):
    bounds = geom.MultiLineString(lines).bounds
    center = geom.Point((bounds[2] - bounds[0])/2, (bounds[3] - bounds[1])/2)
    def dist(line):
        return center.distance(geom.Point(line.coords[0]))
    return sorted(lines, key=dist)



def reorder_end_dist(lines):
    bounds = geom.MultiLineString(lines).bounds
    center = geom.Point((bounds[2] - bounds[0])/2, (bounds[3] - bounds[1])/2)
    def dist(line):
        return center.distance(geom.Point(line.coords[-1]))
    return sorted(lines, key=dist)


def sobel(gray):
    scale = 1
    delta = 0
    ddepth = cv2.CV_32FC1

    grad_x = cv2.Sobel(gray, ddepth, 1, 0, ksize=3, scale=scale, delta=delta, borderType=cv2.BORDER_DEFAULT)
    # Gradient-Y
    # grad_y = cv.Scharr(gray,ddepth,0,1)
    grad_y = cv2.Sobel(gray, ddepth, 0, 1, ksize=3, scale=scale, delta=delta, borderType=cv2.BORDER_DEFAULT)


    abs_grad_x = cv2.convertScaleAbs(grad_x)
    abs_grad_y = cv2.convertScaleAbs(grad_y)


    grad = cv2.addWeighted(abs_grad_x, 0.5, abs_grad_y, 0.5, 0)
    return grad


import numpy as np

def sample_grad(grad_blurred):
    gp = grad_blurred.copy()
    gp[gp < (gp.mean() + 0.5 * gp.std())] = 0.0
    prob = gp
    sample_at = (np.random.poisson(prob + 0.001, (256, 256)) > 0).astype(np.uint8)

    sampled_grad_pixels = grad_blurred * sample_at
    sampled_grad_pixels[0, 0] = 1
    sampled_grad_pixels[-1, -1] = 1
    sampled_grad_pixels[0, -1] = 1
    sampled_grad_pixels[-1, 0] = 1

    return sampled_grad_pixels



import scipy.spatial

def triangulate(sampled_grad_pixels):
    nonzero_ys, nonzero_xs = np.nonzero(sampled_grad_pixels)
    nonzero_coords = np.dstack((nonzero_xs, 255 - nonzero_ys)).squeeze().astype(np.float32)
    tri = scipy.spatial.Delaunay(nonzero_coords)

    z = np.zeros_like(sampled_grad_pixels)
    p = tri.points.astype(np.int)
    vals = np.nonzero(sampled_grad_pixels)
    z[p[:, 1], p[:, 0]] = sampled_grad_pixels[vals[0], vals[1]]
    return tri, z



def to_graph(tri):
    nbrs = {i:set() for i in range(len(tri.points))}

    for smplx in tri.simplices:
        nbrs[smplx[0]].add(smplx[1])
        nbrs[smplx[1]].add(smplx[2])
        nbrs[smplx[2]].add(smplx[0])

        nbrs[smplx[1]].add(smplx[0])
        nbrs[smplx[2]].add(smplx[1])
        nbrs[smplx[0]].add(smplx[2])

    return nbrs


import heapq
from collections import defaultdict

def extract_path_rec(from_key, to_key, reverse_paths, out_list):
    next_key = reverse_paths[from_key]

    if next_key != to_key and next_key in reverse_paths:
        extract_path_rec(next_key, to_key, reverse_paths, out_list)

    out_list.append(next_key)
    return out_list

def extract_path(from_key, to_key, reverse_paths):
    path = extract_path_rec(from_key, to_key, reverse_paths, [])
    path.append(from_key)
    return path

def a_star(start_vertex, goal_vertex, graph, weight, heuristic, return_len=False):
    if start_vertex == goal_vertex:
        return [start_vertex, goal_vertex]
    q = [(0, start_vertex)]
    possible_nexts = set([start_vertex])
    reverse_paths = {}
    cheapest_paths = defaultdict(lambda: float('+inf'))
    cheapest_total = defaultdict(lambda: float('+inf'))
    cheapest_paths[start_vertex] = 0
    while len(possible_nexts) > 0:
        curr_f, curr = heapq.heappop(q)
        possible_nexts.remove(curr)
        if curr == goal_vertex:
            path = extract_path(goal_vertex, start_vertex, reverse_paths)
            if return_len:
                return path, cheapest_paths[goal_vertex]
            else:
                return path

        if curr not in graph:
            continue
        nbrs = graph[curr]

        for nbr in nbrs:
            h = weight(curr, nbr)
            maybe_best_g = h + cheapest_paths[curr]
            if cheapest_paths[nbr] > maybe_best_g:
                reverse_paths[nbr] = curr
                cheapest_paths[nbr] = maybe_best_g
                f = maybe_best_g + heuristic(nbr, goal_vertex)
                if nbr not in possible_nexts:
                    possible_nexts.add(nbr)
                    heapq.heappush(q, (f, nbr))


import time
from math import sqrt

def merge_naive(lines):
    all_coords = [list(line.coords) for line in lines]
    flattened = [coord for coords in all_coords for coord in coords]
    return geom.LineString(flattened)

def pt_vert_distance(pt, tri, idx):
    return sqrt(tuple_sq_dist(pt, tri.points[idx]))

def nearest_line(pt, lines, remaining_line_idxs):
    nearest = None
    nearest_idx = None
    flip = False
    closest_dist = 1e10
    for idx in remaining_line_idxs:
        other = lines[idx]
        start_dist = tuple_sq_dist(pt, other.coords[0])
        end_dist = tuple_sq_dist(pt, other.coords[-1])
        if start_dist < closest_dist:
            flip = False
            closest_dist = start_dist
            nearest = other
            nearest_idx = idx
        elif end_dist < closest_dist:
            flip = True
            closest_dist = end_dist
            nearest = other
            nearest_idx = idx
    return nearest, nearest_idx, flip


def mk_heuristic_fn(tri, grad_blurred):

    grad_max = grad_blurred.max()

    def distance(i, j):
        i_pos = tri.points[i]
        j_pos = tri.points[j]
        dx = i_pos - j_pos
        return np.linalg.norm(dx)

    def heuristic(i, goal):
        dist = distance(i, goal)
        coords = tri.points[i].astype(np.int)
        edginess = grad_blurred[255 - coords[1], coords[0]]
        return dist + (1.0 - edginess) * 10
    return heuristic

def mk_weight_fn(tri, grad_blurred):
    def distance(i, j):
        i_pos = tri.points[i]
        j_pos = tri.points[j]
        dx = i_pos - j_pos
        return np.linalg.norm(dx)

    grad_max = grad_blurred.max()

    def weight(i, j):
        dist = distance(i, j) ** 1.5
        i_pos = tri.points[i]
        j_pos = tri.points[j]

        mid = (i_pos + j_pos).astype(np.int) // 2
        i_pos = i_pos.astype(np.int)
        j_pos = j_pos.astype(np.int)
        edginess = (grad_blurred[255 - mid[1], mid[0]] +
                    grad_blurred[255 - i_pos[1], i_pos[0]] +
                    grad_blurred[255 - j_pos[1], j_pos[0]])/3.0
        return dist + (1.0 - edginess)*10
    return weight

def tuple_sq_dist(a, b):
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return (dx*dx) + (dy*dy)


def insert_a_star_connections(lines, tri, graph_copy, grad_blurred):
    weight = mk_weight_fn(tri, grad_blurred)
    heuristic = mk_heuristic_fn(tri, grad_blurred)
    remaining_lines = set(range(len(lines)))
    curr_idx = 0
    out = [lines[curr_idx]]
    remaining_lines.remove(curr_idx)
    pts_added = []
    while len(remaining_lines) > 0:
        curr = lines[curr_idx]
        end_curr = curr.coords[-1]
        dist = float('+inf')
        nearest_tail, nearest_tail_idx, flip = nearest_line(end_curr, lines, remaining_lines)

        if flip:
            nearest_tail.coords = list(nearest_tail.coords)[::-1]

        remaining_lines.remove(nearest_tail_idx)

        next_start_x, next_start_y = nearest_tail.coords[0]
        goal_pos = next_start_x, next_start_y

        goal_smplx_idx = tri.find_simplex(goal_pos)
        goal_smplx = tri.simplices[goal_smplx_idx]
        nearest_smplx_corner_to_goal = min(goal_smplx, key=lambda idx: pt_vert_distance(goal_pos, tri, idx))

        curr_smplx_idx = tri.find_simplex(end_curr)
        curr_smplx = tri.simplices[curr_smplx_idx]
        nearest_smplx_corner_to_curr = min(curr_smplx, key=lambda idx: pt_vert_distance(end_curr, tri, idx))

        if (nearest_smplx_corner_to_goal != nearest_smplx_corner_to_curr
            and nearest_smplx_corner_to_goal in graph_copy
            and nearest_smplx_corner_to_curr in graph_copy):
            path_between = a_star(nearest_smplx_corner_to_curr, nearest_smplx_corner_to_goal, graph_copy, weight, heuristic)

            if path_between is not None:
                for i in range(len(path_between) - 1):
                    p_i = path_between[i]
                    p_next = path_between[i + 1]
                    graph_copy[p_i].remove(p_next)
                    #del graph_copy[p_i]
                    #print('del', p_i)

                pts_between = [tuple(tri.points[idx]) for idx in path_between]
                pts_added.append(geom.LineString(pts_between))
                out.append(geom.LineString(pts_between))
            else:
                print("no path")
        out.append(nearest_tail)
        curr_idx = nearest_tail_idx
    return out, pts_added



def pipeline(gray):

    edges = raster_edges(gray)
    edges[:, 240:] = 255
    edges[:, :16] = 255
    edges[:4, :] = 255
    edges[252:, :] = 255

    cv2.imwrite('trace_in.bmp', edges)
    if os.name == 'nt':
        subprocess.check_call(r'.\potrace-1.16.win64\potrace.exe trace_in.bmp -o trace_out.geojson -b geojson')
    else:
        subprocess.check_call(r'./potrace-1.16.linux-x86_64/potrace trace_in.bmp -o trace_out.geojson -b geojson', shell=True)

    with open('trace_out.geojson') as fp:
        geojson = json.load(fp)

    shapes = [geom.shape(feature["geometry"]) for feature in geojson['features']]

    center_geom_lines = extract_centerlines(shapes)

    center_geom_lines = explode_multilines(center_geom_lines)

    center_geom_lines = [line for line in center_geom_lines
                         if max(line.length, geom.Point(line.coords[0]).distance(geom.Point(line.coords[-1]))) > 4]

    grad = sobel(gray)

    grad_blurred = cv2.GaussianBlur(grad / grad.max(), (9, 9), 5.0)

    grad_samples = sample_grad(grad_blurred)

    tri, grad_samples = triangulate(grad_samples)

    graph = to_graph(tri)

    a_star_connected, added_pts = insert_a_star_connections(reorder_start_dist(center_geom_lines), tri, graph, grad_blurred)
    merged = merge_naive(a_star_connected)
    return merged

def rgb2line(img):
    rgb = np.asarray(img)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    line = pipeline(gray)
    return line.__geo_interface__




def nearest_vertex(tri, pt):
    curr_smplx_idx = tri.find_simplex(pt)
    curr_smplx = tri.simplices[curr_smplx_idx]
    nearest_smplx_corner_to_curr = min(curr_smplx, key=lambda idx: pt_vert_distance(pt, tri, idx))
    return nearest_smplx_corner_to_curr


import pcst_fast

def image_to_lines(gray):

    print('generate raster edges')

    edges = raster_edges(gray)
    edges[:, 240:] = 255
    edges[:, :16] = 255
    edges[240:, :] = 255
    edges[:16, :] = 255
    cv2.imwrite('trace_in.bmp', edges)

    print('to geojson')

    if os.name == 'nt':
        subprocess.check_call(r'.\\potrace-1.16.win64\\potrace.exe trace_in.bmp -o trace_out.geojson -b geojson')
    else:
        subprocess.check_call(r'./potrace-1.16.linux-x86_64/potrace trace_in.bmp -o trace_out.geojson -b geojson', shell=True)

    with open('trace_out.geojson') as fp:
        geojson = json.load(fp)

    print('loading from geojson')

    shapes = [geom.shape(feature["geometry"]) for feature in geojson['features']]

    print('extract_centerlines')

    center_geom_lines = extract_centerlines(shapes)

    print('explode_multilines')

    center_geom_lines = explode_multilines(center_geom_lines)

    print('geom.Point.distance')

    center_geom_lines = [line for line in center_geom_lines
                         if max(line.length, geom.Point(line.coords[0]).distance(geom.Point(line.coords[-1]))) > 4]

    return center_geom_lines




def traverse(graph, curr, seen, tri, special, lines):
    seen.add(curr)
    nbrs = graph[curr]
    yield tri.points[curr]
    for nbr in nbrs:
        if nbr in seen:
            continue

        if (curr, nbr) in special:
            line_idx, reverse = special[(curr, nbr)]
            yield from lines[line_idx].coords[::-1 if reverse else 1]

        yield from traverse(graph, nbr, seen, tri, special, lines)

        if len(seen) < len(graph):
            if (curr, nbr) in special:
                line_idx, reverse = special[(curr, nbr)]
                yield from lines[line_idx].coords[::1 if reverse else -1]

    if len(seen) < len(graph):
        yield tri.points[curr]


# export cld_mst

class LineTooShort(Exception):
    pass

def traverse_nested(graph, curr, seen, tri, special, lines, min_len=50):
    seen.add(curr)
    nbrs = graph[curr]
    child_pts = []

    for nbr in nbrs:
        cur_len = 0
        if nbr in seen:
            continue

        extend_with = []

        try:
            if (curr, nbr) in special:
                line_idx, reverse = special[(curr, nbr)]
                extend_with.extend(lines[line_idx].coords[::-1 if reverse else 1])

            extend_with.extend(traverse_nested(graph, nbr, seen, tri, special, lines, min_len))

            if len(seen) < len(graph):
                if (curr, nbr) in special:
                    cur_len += lines[line_idx].length
                    line_idx, reverse = special[(curr, nbr)]
                    extend_with.extend(lines[line_idx].coords[::1 if reverse else -1])

            if geom.LineString(extend_with).length > min_len:
                child_pts.extend(extend_with)
        except LineTooShort as e:
            pass


    yield tri.points[curr]
    yield from iter(child_pts)
    if len(seen) < len(graph):
        yield tri.points[curr]


def rgb2line_steiner(img):
    rgb = np.asarray(img)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    line = pipeline_steiner(gray)
    return line.__geo_interface__

def pipeline_steiner(gray):

    print('image to lines')

    center_geom_lines = image_to_lines(gray)

    print('sobel + blur + grad')

    grad = sobel(gray)

    grad_blurred = cv2.GaussianBlur(grad / grad.max(), (9, 9), 5.0)

    grad_samples = sample_grad(grad_blurred)

    for line in center_geom_lines:
        s = line.coords[0]
        e = line.coords[-1]
        grad_samples[floor(s[0]), floor(s[1])] = 1
        grad_samples[floor(e[0]), floor(e[1])] = 1

    tri, grad_samples = triangulate(grad_samples)

    print('graph + reordering')

    tri_graph = to_graph(tri)

    center_geom_lines = reorder_start_dist(center_geom_lines)

    data = []
    ss = []
    ts = []

    def w(i, j):
        start = tri.points[i]
        end = tri.points[j]
        mid = np.floor((start + end) / 2).astype(np.int)
        gf = 1.0 - grad_blurred[255 - mid[1], mid[0]]
        dist = np.linalg.norm(start - end)
        return dist + gf * 10.0

    print('building data')
    
    for s, nbrs in tri_graph.items():
        for t in nbrs:
            ss.append(s)
            ts.append(t)
            data.append(w(s, t))

    print('creating coo_matrix and converting to csc')

    mat = scipy.sparse.coo_matrix((data, (ss, ts))).tocsc()

    tri_verts = [(nearest_vertex(tri, line.coords[0]), nearest_vertex(tri, line.coords[-1])) for line in center_geom_lines]

    starts = np.asarray([v[0] for v in tri_verts])
    ends = np.asarray([v[1] for v in tri_verts])

    print('setup')

    tri_mat = mat.copy()
    tri_mat[starts, ends] = 0.00001234 #
    tri_mat[ends, starts] = 0.00001234 #
    flat_edges_i, flat_edges_j = tri_mat.nonzero()
    flat_edges = np.dstack((flat_edges_i, flat_edges_j)).squeeze().astype(np.int64)
    prizes = np.zeros(shape=(tri_mat.shape[0],), dtype=np.float64)
    prizes[starts] = 100
    prizes[ends] = 100
    costs = np.asarray(tri_mat[flat_edges_i, flat_edges_j].squeeze()).squeeze()
    flat_edges.shape, prizes.shape

    print('fast pcst')

    v, es = pcst_fast.pcst_fast(flat_edges, prizes, costs, -1, 1, 'gw', 1)

    lines = center_geom_lines[:]

    graph = defaultdict(list)
    for e in es:
        st, end = flat_edges[e]
        graph[st].append(end)
        graph[end].append(st)

    print('finishing')

    special = {}
    for i, (s, e) in enumerate(zip(starts, ends)):
        special[(s, e)] = i, False
        special[(e, s)] = i, True

    return geom.LineString(traverse(graph, starts[0], set(), tri, special, lines))