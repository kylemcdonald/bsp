
sudo install -m 0644 plotter.service /etc/systemd/system/plotter.service
sudo systemctl daemon-reload
sudo systemctl enable plotter.service
sudo systemctl restart plotter.service
