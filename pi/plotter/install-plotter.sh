
sudo cp plotter.service /lib/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable plotter.service
sudo systemctl start plotter.service