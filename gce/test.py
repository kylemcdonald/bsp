#!/usr/bin/python3
import requests
import json
from time import time

gce_url = 'http://bsp-ams.kylemcdonald.net:8080'
data = open('img.jpg', 'rb').read()
headers = {'Content-type': 'image/jpeg'}

t0 = time()
response = requests.post(gce_url, data=data, headers=headers)
t1 = time()
print(t1-t0)

data = response.json()['coordinates']
with open('test-out.json', 'w') as f:
    json.dump(data, f)