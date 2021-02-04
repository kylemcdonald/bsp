
sudo cp camera.service /lib/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable camera.service
sudo systemctl start camera.service