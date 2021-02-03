# Setting up the Raspberry Pi

Install the Ubuntu 20.04 64-bit OS to a 32GB+ SD Card.

Start the Pi, find the ip address and ssh into it. It will ask you to change the password. Exit ssh and run `ssh-copy-id` to enable passwordless ssh.

[Disable updates](https://www.reddit.com/r/linuxadmin/comments/kvcfv0/ubuntu_unattendedupgrades_other/gizk3z8/):

```
sudo systemctl disable --now apt-daily{{,-upgrade}.service,{,-upgrade}.timer}
sudo systemctl disable --now unattended-upgrades
sudo systemctl daemon-reload
```

`sudo reboot now` then log back in and upgrade `sudo apt update && sudo apt full-upgrade -y`

Install dependencies:

```
sudo apt install -y \
    python3-pip
sudo pip3 install \
    RPi.GPIO \
    gpiozero \
    opencv-python-headless \
    pyserial \
    flask \
    waitress \
    requests
```

Enable gpio permissions [for all users](https://github.com/gpiozero/gpiozero/issues/837#issuecomment-703743142): `sudo chmod og+rwx /dev/gpio*`.

Setup the shutdown script:

```
cd ~/bsp/pi/shutdown
bash install-shutdown.sh
```

Setup the server script:

```
cd ~/bsp/pi/server
bash install-server.sh
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

## Niceness

Install Avahi to allow `.local` access: `sudo apt install avahi-daemon`

Simplify the login message:

```
sudo chmod -x /etc/update-motd.d/{10-help-text,50-motd-news,90-updates-available,91-release-upgrade,92-unattended-upgrades}
```

With ngrok exposing the machine publicly, [disable ssh passwords](https://www.cyberciti.biz/faq/how-to-disable-ssh-password-login-on-linux/).

## Possible problems

If you don't enable gpio permissions, RPi.GPIO or gpiozero will say `Not running on a RPi!`.

RPi.GPIO does not support `wait_for_edge` on newer operating systems, possibly [due to a kernel deprecation](https://sourceforge.net/p/raspberry-gpio-python/tickets/175/). It will say `RuntimeError: Error waiting for edge` if you try to `wait_for_edge`. Simply creating a `Button` with `gpiozero` will cause `RuntimeError: Failed to add edge detection`.

The Python libraries must be installed with sudo, and the shutdown service must run as root. Otherwise systemctl will read: `Failed to start Shutdown Service.` There may also be a way to configure `PYTHONPATH` to correctly find the libraries install for the local user.