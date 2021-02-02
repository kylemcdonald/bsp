
sudo cp shutdown.service /lib/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable shutdown.service
sudo systemctl start shutdown.service