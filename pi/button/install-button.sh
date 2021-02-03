
sudo cp button.service /lib/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable button.service
sudo systemctl start button.service