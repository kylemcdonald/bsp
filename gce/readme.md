# Setting up Google Compute Engine

* c2-standard-4 (4 vCPUs, 16 GB memory)
* 32GB SSD
* Ubuntu 20.04
* Add ssh key
* Enable http and https

Log in, `ssh-keygen` and add to GitHub. Clone this repo.

```console
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
    tqdm
sudo pip3 install git+https://github.com/fraenkel-lab/pcst_fast.git
```

If you install `opencv-python` on GCE it will complain, which is why you need [`opencv-python-headless`](https://stackoverflow.com/a/63978454/940196).

Build CLD:

```console
sudo apt update
sudo apt install \
    cmake \
    libopencv-dev \
    libboost-all-dev \
    libwxgtk3.0-gtk3-dev
cd ~ && git clone https://github.com/SSARCandy/Coherent-Line-Drawing.git
cd Coherent-Line-Drawing
./build.sh
```

Create a Google Cloud Firewall rule to allow port 8080 on IP range 0.0.0.0/0 for all instances in network.

Install the systemd service:

```
cd ~/bsp/gce
bash install-server.sh
```