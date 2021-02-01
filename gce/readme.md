# Setting up Google Compute Engine

* c2-standard-4 (4 vCPUs, 16 GB memory)
* 32GB SSD
* Ubuntu 20.04
* Add ssh key
* Enable http and https

Log in, `ssh-keygen` and add to GitHub. Clone this repo.

```
sudo apt update
sudo apt install -y python3-pip
pip3 install --user waitress flask
```

This will print a warning about `waitress-serve` and `flask` not being on PATH, but this isn't an issue.

Create a Google Cloud Firewall rulle to allow port 8080 on IP range 0.0.0.0/0 for all instances in network.