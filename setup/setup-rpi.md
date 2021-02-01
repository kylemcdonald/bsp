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
pip3 install \
    opencv-python \
    pyserial \
    waitress
```

Simplify the login message:

```
sudo chmod -x /etc/update-motd.d/{10-help-text,50-motd-news,90-updates-available,91-release-upgrade,92-unattended-upgrades}
```