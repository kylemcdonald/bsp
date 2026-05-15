
sudo install -m 0644 camera.service /etc/systemd/system/camera.service
sudo systemctl daemon-reload
sudo systemctl enable camera.service
sudo systemctl restart camera.service
