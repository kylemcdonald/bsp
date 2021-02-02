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

Install Avahi to allow `.local` access: `sudo apt install avahi-daemon`

Install dependencies:

```
sudo apt install -y \
    python3-pip
sudo pip3 install \
    RPi.GPIO \
    gpiozero
pip3 install \
    opencv-python \
    pyserial \
    flask \
    waitress \
    requests
```

Enable gpio permissions [for all users](https://github.com/gpiozero/gpiozero/issues/837#issuecomment-703743142): `sudo chmod og+rwx /dev/gpio*`.

Simplify the login message:

```
sudo chmod -x /etc/update-motd.d/{10-help-text,50-motd-news,90-updates-available,91-release-upgrade,92-unattended-upgrades}
```

Setup the shutdown script:

```
cd ~/bsp/pi/shutdown
bash install-shutdown.sh
```

## Possible problems

If you don't enable gpio permissions, RPi.GPIO or gpiozero will say `Not running on a RPi!`.

RPi.GPIO does not support `wait_for_edge` on newer operating systems, possibly [due to a kernel deprecation](https://sourceforge.net/p/raspberry-gpio-python/tickets/175/). It will say `RuntimeError: Error waiting for edge` if you try to `wait_for_edge`. Simply creating a `Button` with `gpiozero` will cause `RuntimeError: Failed to add edge detection`.

The gpio libraries must be installed with sudo, and the shutdown service my run as root. Otherwise systemctl will read: `Failed to start Shutdown Service.` There may be a way to configure `PYTHONPATH` to correctly find the libraries install for the local user, but I didn't look into it.