import flask
from flask import Flask, jsonify, request
from waitress import serve

import json
import io
import cld_mst as process_cld
from PIL import Image

app = Flask(__name__)

@app.route('/', methods=['POST'])
def index():
    with open('img.jpg', 'wb') as f:
        f.write(request.get_data())

    with open('result.json', 'r') as f:
        ret = json.load(f)
    return jsonify(ret)

    # img_bytes = io.BytesIO(request.get_data())
    # img = Image.open(img_bytes)
    # ret = process_cld.rgb2line_steiner(img)
    # with open('result.json', 'w') as f:
    #     json.dump(ret, f)
    # return jsonify(ret)

serve(app, listen='*:8080')