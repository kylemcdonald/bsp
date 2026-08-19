# RunPod Processor Manager

`bsp-runpod.service` owns the installation's `bsp-convert` pod. It starts or
resumes the managed pod after the Pi gains network access, publishes status and
controls to the plotter UI, and stops the pod before system shutdown removes
network access.

The service uses the `runpodctl` authentication already configured for the
`ubuntu` user. It listens only on `127.0.0.1:8082`; the plotter service proxies
its controls into `http://bsp-install.local:8080/`.

Persistent configuration and lifecycle state live outside the checkout in
`/var/lib/bsp-runpod/`. The UI stores the deployment geography, priority data
centers, and selected GPU cards in `config.json`. North America, Europe, and
Asia Pacific are available deployment geographies. North America defaults to
`US-CA-2` as its priority; multiple data centers can be checked and are tried
before other data centers in the deployment geography. The card selector only
shows supported cards with current stock in at least one checked priority data
center, along with the stock status at each matching center.
Priority data centers without supported-card stock are hidden by default; the
UI toggle can show all regions and hide unavailable regions again.
Selections apply immediately to the next new pod. If a stopped managed pod no
longer uses an allowed card or deployment geography, the manager deletes that
stopped pod and creates a replacement when Start is requested or the Pi next
boots.

The UI reports elapsed startup time from the boot/manual Start request until
`bsp-convert` confirms its model is loaded, then keeps the completed duration
visible.

Defaults:

- image: `kylemcdonald/bsp-convert:runpod-20260616-1386277`
- cards: H100 SXM/NVL/PCIe, H200 SXM/NVL, and B200
- deployment geography: North America by default, with Europe and Asia Pacific
  also available
- priority data centers: `US-CA-2` by default; other centers in the selected
  geography remain automatic fallbacks
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
