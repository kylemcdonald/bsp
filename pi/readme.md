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

## Button Control Permissions

The button service runs as the normal `ubuntu` user. Long-press shutdown and
service restart are allowed through narrow sudoers rules installed by
`pi/install-system-deps.sh`:

```sudoers
ubuntu ALL=(root) NOPASSWD: /usr/sbin/shutdown -h now
ubuntu ALL=(root) NOPASSWD: /home/ubuntu/bsp/pi/button/restart-services.sh
```

The button code calls shutdown exactly:

```sh
sudo /usr/sbin/shutdown -h now
```

For service restart, it calls the repo helper through sudo:

```sh
sudo /home/ubuntu/bsp/pi/button/restart-services.sh
```

That helper schedules a delayed one-shot transient systemd unit. The delay is
important because `button.service` is one of the services being restarted.

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
- `BSP_CAMERA_DEVICE`: optional V4L2 camera device/path used for capture and controls. If unset, the camera service prefers `/dev/v4l/by-id/*` and falls back to `/dev/video0`.
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

- `GET http://localhost:8081/status`; returns `200` only when the camera is connected and readable, and returns `503` after a runtime disconnect
- `GET http://localhost:8081/shutter`
- `GET http://localhost:8081/preview.jpg`
- `GET http://localhost:8081/settings`
- `POST http://localhost:8081/settings`

Button:

- short press calls `http://localhost:8080/button`; when the plotter is home this triggers a camera capture and turns the button light off, when the capture result is ready the button light turns on, the next press draws that stored result, and a press while drawing resets to the beginning state
- while the button light is off, button presses are ignored locally by the button service
- capture and processor failures are reported in the plotter state, which returns to `HOME` with `last_error` set in `/status`
- holding the button for 5 seconds arms a service restart; the LED switches to a fast `200ms` on, `200ms` off flash, and releasing the button after this point restarts `plotter.service`, `camera.service`, and `button.service`
- continuing to hold the button for 10 seconds homes the plotter and shuts down the Pi

## Button LED Feedback

The button service owns LED feedback. Error patterns repeat until the underlying
condition clears:

- network disconnected: one `100ms` flash, then `1000ms` off
- camera disconnected: two `100ms` flashes with `100ms` off between them, then `1000ms` off
- plotter error: three `100ms` flashes with `100ms` off between them, then `1000ms` off

The button service checks for a local default route, whether it is provided by
Ethernet or Wi-Fi, then probes the configured processor endpoint from
`plotter.service` status. A missing camera status response is treated as camera
disconnected. A missing plotter status response or plotter `ERROR` state is
treated as plotter error.

When more than one error is present, the LED reports the first condition in this
order: network, camera, plotter. During a normal capture, the LED blinks at
`250ms` on, `250ms` off. During a restart-armed button hold, that is overridden
by the fast `200ms` on, `200ms` off pattern.

## Plotter State Changes

The plotter service reports state through `GET /status`:

- `CENTERING`: startup-only calibration that defines the current logical
  position, moves to min, moves to max, then returns home
- `HOME`: idle at `home_position`, ready for a capture
- `CAPTURING`: waiting for the camera image or processor response
- `READY`: a processed path is stored and the next button press will draw it
- `DRAWING`: G-code is being streamed to TinyG
- `POSTDRAW`: draw completed and the service is waiting before returning home
- `RETURNING_HOME`: normal return to `home_position`
- `POSITIONED`: manually moved to min or max
- `ERROR`: plotter motion/control error; restart `plotter.service` to run
  startup centering before continuing. If TinyG is unavailable at startup or
  disconnects during operation, `plotter.service` keeps retrying the serial
  connection; when TinyG comes back, it reconfigures TinyG and runs startup
  `CENTERING` before returning to `HOME`. While idle, the plotter also polls
  TinyG health so a lost controller is reported without waiting for the next
  movement command.

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
