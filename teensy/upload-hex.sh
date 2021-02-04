scp plotter/plotter.ino.TEENSY41.hex ubuntu:~/bsp/teensy/plotter
ssh ubuntu "cd ~/teensy_loader_cli && sudo ./teensy_loader_cli \
    --mcu=TEENSY41 -s -v \
    ~/bsp/teensy/plotter/plotter.ino.TEENSY41.hex"