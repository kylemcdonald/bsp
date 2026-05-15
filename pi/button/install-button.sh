
sudo install -m 0644 button.service /etc/systemd/system/button.service
sudo systemctl daemon-reload
sudo systemctl enable button.service
sudo systemctl restart button.service
