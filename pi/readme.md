# Setting up the Raspberry Pi

Install the Ubuntu 20.04 64-bit OS to a 32GB+ SD Card.

Start the Pi, find the ip address and ssh into it. It will ask you to change the password. Exit ssh and run `ssh-copy-id` to enable passwordless ssh.

[Disable updates](https://www.reddit.com/r/linuxadmin/comments/kvcfv0/ubuntu_unattendedupgrades_other/gizk3z8/):

```
sudo systemctl disable --now apt-daily{{,-upgrade}.service,{,-upgrade}.timer}
sudo systemctl disable --now unattended-upgrades
sudo systemctl daemon-reload
sudo systemctl stop unattended-upgrades
sudo systemctl mask unattended-upgrades
```

`sudo reboot now` then log back in and upgrade `sudo apt update && sudo apt full-upgrade -y`

Disable snapd to free some RAM:

```
sudo systemctl stop snapd
sudo systemctl mask snapd
```

Install other dependencies:

```
sudo apt update
sudo apt install -y \
    python3-pip
sudo dphys-swapfile install
sudo pip3 install \
    RPi.GPIO \
    gpiozero \
    opencv-python-headless \
    pyserial \
    flask \
    waitress \
    requests 
```

Install tflite:

```
echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt update
sudo apt install python3-tflite-runtime
```

Install dlib, including `dphys-swapfile` for the 2GB Raspberry Pi in order to have the memory to build dlib:

```
sudo apt install -y \
    cmake \
    dphys-swapfile
sudo dphys-swapfile swapon
sudo pip3 install dlib
sudo dphys-swapfile swapoff
```

Enable gpio permissions [for all users](https://github.com/gpiozero/gpiozero/issues/837#issuecomment-703743142): `sudo chmod og+rwx /dev/gpio*`.

Setup the shutdown service:

```
cd ~/bsp/pi/shutdown
bash install-shutdown.sh
```

Setup the plotter service:

```
cd ~/bsp/pi/plotter
bash install-plotter.sh
```

Setup the camera service:

```
cd ~/bsp/pi/camera
bash install-camera.sh
```

## Remote access

Install and connect to Zerotier `NETWORK_ID`:

```
curl -s https://install.zerotier.com | sudo bash
sudo zerotier-cli $NETWORK_ID
```

Zerotier creates a VPN. Access the pi with `ssh ubuntu@ubuntu.local`

Download and install ngrok using `AUTH_TOKEN`:

```
sudo apt install unzip
cd ~
wget https://raw.githubusercontent.com/vincenthsu/systemd-ngrok/master/install.sh
sed -i "s/amd64/arm64/g" install.sh
sudo bash install.sh $AUTH_TOKEN
sudo rm -rf install.sh systemd-ngrok 
```

ngrok tunnels a port to ssh. If ngrok says the service is running at `tcp://0.tcp.ngrok.io:1234` then access the pi with `ssh ubuntu@0.tcp.ngrok.io -p1234`

## Setting up Teensy loader

```
sudo apt install -y libusb-dev
cd ~ && git clone https://github.com/PaulStoffregen/teensy_loader_cli.git
cd teensy_loader_cli
make
```

To push a .hex file to the Teensy, run this command and press the reset button (in either order):

```
sudo ./teensy_loader_cli --mcu=TEENSY41 -w -v plotter.ino.TEENSY41.hex
```

## Niceness

Install Avahi to allow `.local` access: `sudo apt install avahi-daemon`

Then change the hostname and restart Avahi:

```
sudo hostnamectl set-hostname "bsp-install"
sudo systemctl restart avahi-daemon
```

Simplify the login message:

```
sudo chmod -x /etc/update-motd.d/{10-help-text,50-motd-news,90-updates-available,91-release-upgrade,92-unattended-upgrades}
```

systemctl will say "status degraded" unless you disable motd completely. This might render the above unnecessary:

```
sudo systemctl stop motd-news
sudo systemctl mask motd-news
sudo systemctl reset-failed
```

With ngrok exposing the machine publicly, [disable ssh passwords](https://www.cyberciti.biz/faq/how-to-disable-ssh-password-login-on-linux/).

## Possible problems

If you don't enable gpio permissions, RPi.GPIO or gpiozero will say `Not running on a RPi!`.

RPi.GPIO does not support `wait_for_edge` on newer operating systems, possibly [due to a kernel deprecation](https://sourceforge.net/p/raspberry-gpio-python/tickets/175/). It will say `RuntimeError: Error waiting for edge` if you try to `wait_for_edge`. Simply creating a `Button` with `gpiozero` will cause `RuntimeError: Failed to add edge detection`.

The Python libraries must be installed with sudo, and the shutdown service must run as root. Otherwise systemctl will read: `Failed to start Shutdown Service.` There may also be a way to configure `PYTHONPATH` to correctly find the libraries install for the local user.

## Correct configuration

When the USB devices are correctly plugged in, `./uhubctl` should report:

```console
Current status for hub 2 [1d6b:0003 Linux 5.4.0-1028-raspi xhci-hcd xHCI Host Controller 0000:01:00.0, USB 3.00, 4 ports, ppps]
  Port 1: 02a0 power 5gbps Rx.Detect
  Port 2: 0203 power 5gbps U0 enable connect [046d:085e Logitech BRIO 90023138]
  Port 3: 02a0 power 5gbps Rx.Detect
  Port 4: 02a0 power 5gbps Rx.Detect
Current status for hub 1-1 [2109:3431 USB2.0 Hub, USB 2.10, 4 ports, ppps]
  Port 1: 0100 power
  Port 2: 0100 power
  Port 3: 0100 power
  Port 4: 0103 power enable connect [0403:6015 FTDI FT230X Basic UART D308QQ85]
Current status for hub 1 [1d6b:0002 Linux 5.4.0-1028-raspi xhci-hcd xHCI Host Controller 0000:01:00.0, USB 2.00, 1 ports, ppps]
  Port 1: 0503 power highspeed enable connect [2109:3431 USB2.0 Hub, USB 2.10, 4 ports, ppps]
  ```