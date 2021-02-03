
sudo cp server.service /lib/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable server.service
sudo systemctl start server.service