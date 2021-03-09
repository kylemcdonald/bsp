#!/usr/bin/python3
import flask
from flask import Flask, jsonify, request
from waitress import serve

import datetime
import os
import json
import io
import cld_steiner as process_cld
from PIL import Image
from pathutils import remove_consecutive_duplicates, resample_path, smooth_path
import numpy as np

import sys
def log(*args):
    print(*args)
    sys.stdout.flush()

def save_to_disk(data, directory, extension):
    now = datetime.datetime.now()
    os.makedirs(directory, exist_ok=True)
    fn = now.replace(microsecond=0).isoformat() + extension
    fn = fn.replace(':', '-')
    fn = os.path.join(directory, fn)
    with open(fn, 'wb') as f:
        f.write(data)

app = Flask(__name__)

@app.route('/', methods=['POST'])
def index():
    log('received request')
    data = request.get_data()

    log('saving image', len(data), 'bytes')
    save_to_disk(data, 'images', '.jpg')

    log('sending response')
    
    # bypass
    # with open('sample.json', 'r') as f:
    #     ret = json.load(f)
    # return jsonify(ret)

    img_bytes = io.BytesIO(request.get_data())
    img = Image.open(img_bytes)
    
    try:
        lines = process_cld.rgb2line_steiner(img)
        path = np.asarray(lines['coordinates'])
        path = remove_consecutive_duplicates(path)
        path = resample_path(path, 0.2)
        path = smooth_path(path, 5)
        lines['coordinates'] = path.tolist()

        # save to disk
        # with open('result.json', 'w') as f:
        #     json.dump(lines, f)

        return jsonify(lines)
    
    except:
        log('error')
        with open('error.json') as f:
            return jsonify(json.load(f))

serve(app, listen='*:8080')