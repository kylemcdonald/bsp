#!/usr/bin/python3
import flask
from flask import Flask, jsonify, request
from waitress import serve

import datetime
import os
import json
import io
import cld_mst as process_cld
from PIL import Image

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

    # byapss
    with open('sample.json', 'r') as f:
        ret = json.load(f)

    log('sending response')
    return jsonify(ret)

    # img_bytes = io.BytesIO(request.get_data())
    # img = Image.open(img_bytes)
    # ret = process_cld.rgb2line_steiner(img)
    # with open('result.json', 'w') as f:
    #     json.dump(ret, f)
    # return jsonify(ret)

serve(app, listen='*:8080')