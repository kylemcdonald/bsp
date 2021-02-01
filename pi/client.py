import base64
import json
import os

import requests

endpoint = os.environ['ENDPOINT']
headers = {'Content-type': 'image/jpeg'}
with open('img.jpg', 'rb') as f:
    payload = f.read()
response = requests.post(endpoint, data=payload, headers=headers)
data = response.json()
print(data)