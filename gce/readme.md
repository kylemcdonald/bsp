# Setting up Google Compute Engine

* c2-standard-4 (4 vCPUs, 16 GB memory)
* Ubuntu 20.04
* 32GB SSD
* Allow http and https traffic
* Add ssh key

Promote the ephemeral IP address to a [static IP address](https://console.cloud.google.com/networking/addresses/list) for the GCE instance. Set an A record on the DNS to point to `bsp.kylemcdonald.net`. Do this first so it has time to propagate.

Log in, `ssh-keygen` and add to GitHub. Clone this repo.

```console
git clone https://github.com/kylemcdonald/bsp.git
sudo apt update
sudo apt install -y \
    python3-pip
sudo pip3 install \
    waitress \
    flask \
    pillow \
    opencv-python-headless \
    matplotlib \
    shapely \
    centerline \
    tqdm \
    scikit-image
sudo pip3 install git+https://github.com/fraenkel-lab/pcst_fast.git
sudo pip3 install git+https://github.com/Image-Py/sknw
```

If you install `opencv-python` on GCE it will complain, which is why you need [`opencv-python-headless`](https://stackoverflow.com/a/63978454/940196).

Build CLD:

```console
sudo apt update
sudo apt install libopencv-dev
cd ~ && git clone https://github.com/kylemcdonald/coherent_line_drawing.git
cd coherent_line_drawing && bash build.sh
cp cld ~/bsp/gce
```

Download potrace:

```console
cd ~/bsp/gce
wget http://potrace.sourceforge.net/download/1.16/potrace-1.16.linux-x86_64.tar.gz
tar xvf potrace-1.16.linux-x86_64.tar.gz
```

Create a [Google Cloud Firewall rule](https://console.cloud.google.com/networking/firewalls/list) to allow port 8080 on IP range 0.0.0.0/0 for all instances in network.

Install the systemd service:

```
cd ~/bsp/gce
bash install-server.sh
```

Check the status: `sudo systemctl status server.service`
