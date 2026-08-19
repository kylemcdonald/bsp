# RunPod Processor Manager

`bsp-runpod.service` owns the installation's `bsp-convert` pod. It starts or
resumes the managed pod after the Pi gains network access, publishes status and
controls to the plotter UI, and stops the pod before system shutdown removes
network access.

The service uses the `runpodctl` authentication already configured for the
`ubuntu` user. It listens only on `127.0.0.1:8082`; the plotter service proxies
its controls into `http://bsp-install.local:8080/`.

Persistent configuration and lifecycle state live outside the checkout in
`/var/lib/bsp-runpod/`. The UI stores selected GPU cards and regions in
`config.json`. `US-CA-2` is always attempted first when it is selected.
Selections apply immediately to the next new pod. If a stopped managed pod no
longer uses an allowed card and region, the manager deletes that stopped pod
and creates a replacement when Start is requested or the Pi next boots.

Defaults:

- image: `kylemcdonald/bsp-convert:runpod-20260616-1386277`
- cards: H100 SXM/NVL/PCIe, H200 SXM/NVL, and B200
- regions: all current United States and Canadian RunPod data centers
- cloud: secure
- exposed port: `8787/http`
- container disk: 80 GB
- persistent volume: 120 GB mounted at `/workspace`

Useful commands:

```sh
systemctl status bsp-runpod
journalctl -u bsp-runpod -f
curl -s http://127.0.0.1:8082/status | python3 -m json.tool
```

The service accepts these optional variables from `/etc/bsp.env`:

- `BSP_RUNPOD_IMAGE`
- `BSP_RUNPOD_AUTOSTART` (default `true`)
- `BSP_RUNPOD_MANAGER_PORT` (default `8082`, loopback only)
- `BSP_RUNPOD_POLL_SECONDS` (default `5`)
- `BSP_RUNPOD_RETRY_SECONDS` (default `30`)
- `BSP_RUNPOD_TERMINATE_AFTER_MINUTES` (normally unset; useful as a temporary
  orphan-cost guard during testing)

The shutdown hook targets only the pod id saved in `/var/lib/bsp-runpod/state.json`.
It never stops or deletes unrelated pods in the account.
