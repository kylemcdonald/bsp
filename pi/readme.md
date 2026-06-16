# Setting Up the Raspberry Pi

This Pi runs three small services:

- `plotter`: receives planned vector paths, sends images to the configured
  processor, and streams G-code to TinyG.
- `camera`: captures a full webcam JPEG and sends it to the plotter service.
- `button`: watches the GPIO button and calls the plotter service.

The Pi no longer runs local face detection, eye detection, blink detection, dlib,
TFLite, or Coral code. The plotter service sends the full `.jpg` to the
configured `BSP_VIBECHECK_URL` or `BSP_PROCESS_URL`, and that remote service is
responsible for image analysis/cropping/vectorization.

## OS

Use a current 64-bit OS. Preferred:

- Raspberry Pi OS Lite 64-bit
- Ubuntu Server 24.04 LTS 64-bit

Avoid a fresh Ubuntu 20.04 install. It is past standard support.

After first boot:

```sh
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

Optional but useful:

```sh
sudo apt install -y avahi-daemon
sudo hostnamectl set-hostname "bsp-install"
sudo systemctl restart avahi-daemon
```

## Checkout

The service files assume this checkout:

```sh
cd ~
git clone <repo-url> bsp
cd ~/bsp
```

If you use a different user or path, update the `.service` files and scripts.

## Install System Dependencies

Run this once on the Pi:

```sh
cd ~/bsp
bash pi/install-system-deps.sh
```

This installs the OS-managed hardware packages:

- `python3-gpiozero` for the button and LED
- `python3-opencv` and `python3-numpy` for webcam capture/JPEG encoding
- `v4l-utils` for camera inspection/debugging
- `python3-venv` and `python3-pip` for the project venv

It also creates a `gpio` group/udev rule for GPIO devices and adds the `ubuntu`
user to hardware groups:

- `dialout` for TinyG serial
- `video` for the webcam
- `gpio` for GPIO access

Log out and back in, or reboot, after group changes:

```sh
sudo reboot
```

## Python Environment

The project uses a venv at `~/bsp/.venv`, but it is created with
`--system-site-packages` so it can use apt-managed Pi hardware packages such as
`cv2`, `gpiozero`, and `numpy`.

To recreate only the Python venv:

```sh
cd ~/bsp
bash pi/setup-venv.sh
```

The pip-managed Pi dependencies are listed in `pi/requirements-pi.txt`:

- `flask`
- `waitress`
- `requests`
- `pyserial`

Do not use `sudo pip3 install` for this app. Keep OS/hardware packages in apt
and app-level packages in the venv.

## Shutdown Permission

The button service runs as the normal `ubuntu` user. Long-press shutdown is
allowed through a narrow sudoers rule installed by `pi/install-system-deps.sh`:

```sudoers
ubuntu ALL=(root) NOPASSWD: /usr/sbin/shutdown -h now
```

The button code calls exactly:

```sh
sudo /usr/sbin/shutdown -h now
```

This avoids running the whole button service as root.

## Install Services

After dependencies are installed and the Pi has been rebooted for group
membership:

```sh
cd ~/bsp
bash pi/install-services.sh
```

This installs:

- `/etc/systemd/system/plotter.service`
- `/etc/systemd/system/camera.service`
- `/etc/systemd/system/button.service`

Useful commands:

```sh
systemctl status plotter camera button
journalctl -u plotter -f
journalctl -u camera -f
journalctl -u button -f
```

## Configuration

The services optionally read `/etc/bsp.env`.

Create it if the processor endpoint needs to change:

```sh
sudo cp ~/bsp/pi/bsp.env.example /etc/bsp.env
sudo nano /etc/bsp.env
sudo systemctl restart plotter
```

Available settings:

- `BSP_VIBECHECK_URL`: base URL for the full-frame vector processing API, default `http://vibecheck.taildd340.ts.net:8787`; for RunPod use its full `https://...` base URL if provided
- `BSP_PROCESS_URL`: optional full process endpoint override, default `$BSP_VIBECHECK_URL/api/process`; only `plotter.service` uses this setting
- `BSP_PLOTTER_CAPTURE_IMAGE_URL`: local plotter endpoint used by the camera after JPEG capture, default `http://localhost:8080/capture-image`
- `BSP_PLOTTER_CAPTURE_ERROR_URL`: local plotter endpoint used by the camera when capture or processing fails, default `http://localhost:8080/capture-error`
- `BSP_CAMERA_SHUTTER_URL`: local camera shutter endpoint used by the plotter
- `BSP_CAMERA_PREVIEW_URL`: local camera preview endpoint used by the plotter web UI, default `http://localhost:8081/preview.jpg`
- `BSP_CAMERA_SETTINGS_URL`: local camera settings endpoint used by the plotter web UI, default `http://localhost:8081/settings`
- `BSP_CAMERA_DEVICE`: V4L2 camera device used for camera controls, default `/dev/video0`
- `BSP_TINYG_PORT`: optional TinyG serial device override, for example `/dev/ttyUSB0`

Restart both `camera` and `plotter` after changing local camera/plotter URLs or
the camera device:

```sh
sudo systemctl restart camera plotter
```

## Hardware Checks

Check the webcam:

```sh
v4l2-ctl --list-devices
v4l2-ctl --device=/dev/video0 --list-formats-ext
```

Check TinyG serial:

```sh
~/bsp/.venv/bin/python -m serial.tools.list_ports -v
```

The plotter service searches for an FTDI device matching `FT230X`.

## Service Endpoints

Plotter:

- `GET http://localhost:8080/status`
- `GET http://localhost:8080/min`
- `GET http://localhost:8080/home`
- `GET http://localhost:8080/max`
- `GET http://localhost:8080/button`
- `POST http://localhost:8080/draw`
- `POST http://localhost:8080/draw-json`
- `GET http://localhost:8080/camera-preview.jpg`
- `GET http://localhost:8080/processor-endpoint`
- `POST http://localhost:8080/processor-endpoint`
- `GET http://localhost:8080/pending-path`
- `POST http://localhost:8080/capture-image`
- `POST http://localhost:8080/capture-result`
- `POST http://localhost:8080/capture-error`

Camera:

- `GET http://localhost:8081/status`
- `GET http://localhost:8081/shutter`
- `GET http://localhost:8081/preview.jpg`
- `GET http://localhost:8081/settings`
- `POST http://localhost:8081/settings`

Button:

- short press calls `http://localhost:8080/button`; when the plotter is home this triggers a camera capture and turns the button light off, when the capture result is ready the button light turns on, the next press draws that stored result, and a press while drawing resets to the beginning state
- while the button light is off, button presses are ignored locally by the button service
- capture and processor failures are reported in the plotter state, which returns to `HOME` with `last_error` set in `/status`; the button LED flashes at 10Hz until the next press, which starts a new capture
- long press for more than 5 seconds homes the plotter and shuts down the Pi

## Processor Response Schema

The plotter now accepts either of these path payloads:

```json
{"coordinates": [[0, 0], [1, 1]]}
```

or:

```json
{"continuous_path": {"points": [[0, 0], [1, 1]]}}
```

or the full process API shape:

```json
{"vector": {"continuous_path": {"points": [[0, 0], [1, 1]]}}}
```

The plotter extracts and stores the `vector` object from the process response
until the next valid button press.

The processor endpoint can also be changed at runtime from the plotter web UI
or by posting `{"url": "https://host/api/process"}` to `/processor-endpoint`.
This runtime value is not written back to `/etc/bsp.env`; the env file remains
the startup default after a service restart.

All planned paths are rotated 180 degrees at the plotter planning layer before
G-code is generated, regardless of whether they arrive from the web interface,
`/draw`, or `/draw-json`.

## Removed Legacy Setup

Do not install these on the Pi for the current pipeline:

- `dlib`
- `python3-tflite-runtime`
- Coral/EdgeTPU apt repositories
- local face/eye/blink model files
- custom OpenCV builds
- swap changes solely for compiling dlib

Those were only needed for the old local preprocessing path.

## Remote Access

For LAN access, Avahi provides `.local` hostnames:

```sh
ssh ubuntu@bsp-install.local
```

If exposing SSH through a tunnel, disable password login and use SSH keys only.
