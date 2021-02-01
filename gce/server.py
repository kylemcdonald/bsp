import flask
from flask import Flask, jsonify, request
from waitress import serve

app = Flask(__name__)

@app.route('/', methods=['POST'])
def index():
    with open('img.jpg', 'wb') as f:
        f.write(request.get_data())
    return jsonify([[0,1],[2,3],[4,5]])

serve(app, listen='*:8080')