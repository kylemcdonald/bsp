#!/usr/bin/env python3
"""Own the RunPod lifecycle for the BSP installation.

The long-running mode exposes a loopback-only HTTP API used by plotter.py.  The
``shutdown`` command is used by systemd's ExecStop so the managed pod is stopped
before the Pi loses network access.
"""

import argparse
import copy
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import threading
import time

import requests


DEFAULT_STATE_DIR = "/var/lib/bsp-runpod"
DEFAULT_MANAGER_PORT = 8082
DEFAULT_POD_NAME = "bsp-convert-installation"
DEFAULT_IMAGE = "kylemcdonald/bsp-convert:runpod-20260616-1386277"
DEFAULT_CONTAINER_PORT = 8787
DEFAULT_DEPLOYMENT_REGION = "north-america"
DEFAULT_PRIORITY_DATA_CENTER = "US-CA-2"
DEFAULT_PRIORITY_GPU_IDS = ["NVIDIA H100 80GB HBM3"]

CAPACITY_ERROR_TOKENS = (
    "capacity",
    "available gpu",
    "free gpu",
    "no gpu",
    "stock",
    "instance available",
)

DEPLOYMENT_REGION_OPTIONS = [
    {"id": DEFAULT_DEPLOYMENT_REGION, "name": "North America"},
    {"id": "europe", "name": "Europe"},
    {"id": "asia-pacific", "name": "Asia Pacific"},
]

DATA_CENTER_REGION_PREFIXES = {
    "north-america": ("US-", "CA-"),
    "europe": ("EU-", "EUR-"),
    "asia-pacific": ("AP-", "SEA-", "OC-"),
}

DEFAULT_GPU_OPTIONS = [
    {"id": "NVIDIA H100 80GB HBM3", "name": "H100 SXM", "memory_gb": 80},
    {"id": "NVIDIA H100 NVL", "name": "H100 NVL", "memory_gb": 94},
    {"id": "NVIDIA H100 PCIe", "name": "H100 PCIe", "memory_gb": 80},
    {"id": "NVIDIA H200", "name": "H200 SXM", "memory_gb": 141},
    {"id": "NVIDIA H200 NVL", "name": "H200 NVL", "memory_gb": 143},
    {"id": "NVIDIA B200", "name": "B200", "memory_gb": 180},
]

# Static fallbacks cover RunPod's current supported geographies. The live list
# and stock status are refreshed from the API at runtime.
DEFAULT_DATA_CENTER_OPTIONS = [
    {"id": "US-CA-2", "name": "US-CA-2", "location": "United States"},
    {"id": "US-CA-1", "name": "US-CA-1", "location": "United States"},
    {"id": "US-CO-1", "name": "US-CO-1", "location": "United States"},
    {"id": "US-DE-1", "name": "US-DE-1", "location": "United States"},
    {"id": "US-GA-1", "name": "US-GA-1", "location": "United States"},
    {"id": "US-GA-2", "name": "US-GA-2", "location": "United States"},
    {"id": "US-IL-1", "name": "US-IL-1", "location": "United States"},
    {"id": "US-KS-1", "name": "US-KS-1", "location": "United States"},
    {"id": "US-KS-2", "name": "US-KS-2", "location": "United States"},
    {"id": "US-KS-3", "name": "US-KS-3", "location": "United States"},
    {"id": "US-MD-1", "name": "US-MD-1", "location": "United States"},
    {"id": "US-MO-1", "name": "US-MO-1", "location": "United States"},
    {"id": "US-MO-2", "name": "US-MO-2", "location": "United States"},
    {"id": "US-NC-1", "name": "US-NC-1", "location": "United States"},
    {"id": "US-NC-2", "name": "US-NC-2", "location": "United States"},
    {"id": "US-NE-1", "name": "US-NE-1", "location": "United States"},
    {"id": "US-OR-1", "name": "US-OR-1", "location": "United States"},
    {"id": "US-OR-2", "name": "US-OR-2", "location": "United States"},
    {"id": "US-PA-1", "name": "US-PA-1", "location": "United States"},
    {"id": "US-TX-1", "name": "US-TX-1", "location": "United States"},
    {"id": "US-TX-2", "name": "US-TX-2", "location": "United States"},
    {"id": "US-TX-3", "name": "US-TX-3", "location": "United States"},
    {"id": "US-TX-4", "name": "US-TX-4", "location": "United States"},
    {"id": "US-TX-5", "name": "US-TX-5", "location": "United States"},
    {"id": "US-TX-6", "name": "US-TX-6", "location": "United States"},
    {"id": "US-WA-1", "name": "US-WA-1", "location": "United States"},
    {"id": "US-WA-2", "name": "US-WA-2", "location": "United States"},
    {"id": "CA-MTL-1", "name": "CA-MTL-1", "location": "Canada"},
    {"id": "CA-MTL-2", "name": "CA-MTL-2", "location": "Canada"},
    {"id": "CA-MTL-3", "name": "CA-MTL-3", "location": "Canada"},
    {"id": "CA-MTL-4", "name": "CA-MTL-4", "location": "Canada"},
    {"id": "EU-CZ-1", "name": "EU-CZ-1", "location": "Europe"},
    {"id": "EU-DK-1", "name": "EU-DK-1", "location": "Europe"},
    {"id": "EU-FR-1", "name": "EU-FR-1", "location": "France"},
    {"id": "EU-NL-1", "name": "EU-NL-1", "location": "Europe"},
    {"id": "EU-RO-1", "name": "EU-RO-1", "location": "Europe"},
    {"id": "EU-SE-1", "name": "EU-SE-1", "location": "Europe"},
    {"id": "EU-SE-2", "name": "EU-SE-2", "location": "Europe"},
    {"id": "EUR-IS-1", "name": "EUR-IS-1", "location": "Europe"},
    {"id": "EUR-IS-2", "name": "EUR-IS-2", "location": "Europe"},
    {"id": "EUR-IS-3", "name": "EUR-IS-3", "location": "Europe"},
    {"id": "EUR-IS-4", "name": "EUR-IS-4", "location": "Europe"},
    {"id": "EUR-IS-5", "name": "EUR-IS-5", "location": "Europe"},
    {"id": "EUR-NO-1", "name": "EUR-NO-1", "location": "Europe"},
    {"id": "EUR-NO-2", "name": "EUR-NO-2", "location": "Europe"},
    {"id": "AP-IN-1", "name": "AP-IN-1", "location": "India"},
    {"id": "AP-IN-2", "name": "AP-IN-2", "location": "India"},
    {"id": "AP-JP-1", "name": "AP-JP-1", "location": "Japan"},
    {"id": "SEA-SG-1", "name": "SEA-SG-1", "location": "SE Asia"},
    {"id": "OC-AU-1", "name": "OC-AU-1", "location": "Australia"},
]


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def elapsed_seconds(started_at, ended_at=None):
    """Return a non-negative elapsed duration for two UTC ISO timestamps."""
    if not started_at:
        return None
    try:
        started = dt.datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        ended = dt.datetime.fromisoformat(str(ended_at or utc_now()).replace("Z", "+00:00"))
        return round(max(0.0, (ended - started).total_seconds()), 1)
    except (TypeError, ValueError):
        return None


def deployment_region_for_data_center(data_center_id):
    data_center_id = str(data_center_id or "")
    for region_id, prefixes in DATA_CENTER_REGION_PREFIXES.items():
        if data_center_id.startswith(prefixes):
            return region_id
    return None


def parse_bool(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def is_capacity_error(message):
    normalized = str(message or "").lower()
    return any(token in normalized for token in CAPACITY_ERROR_TOKENS)


def atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def read_json(path, default):
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return copy.deepcopy(default)
    return data if isinstance(data, dict) else copy.deepcopy(default)


def pod_id_from_payload(payload):
    containers = [payload]
    if isinstance(payload, dict):
        containers.extend((payload.get("pod"), payload.get("data")))
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("id", "podId", "pod_id"):
            value = container.get(key)
            if value:
                return str(value)
    return None


def pod_runtime_status(payload):
    if not isinstance(payload, dict):
        return "unknown"
    runtime = str(payload.get("runtimeStatus") or "").strip().lower()
    if runtime:
        return runtime
    desired = str(payload.get("desiredStatus") or "").strip().upper()
    if desired in ("EXITED", "STOPPED"):
        return "stopped"
    if desired in ("TERMINATED", "DELETED"):
        return "terminated"
    if desired == "RUNNING":
        return "initializing"
    return "unknown"


def pod_uptime_seconds(payload):
    if not isinstance(payload, dict):
        return None
    try:
        value = float(payload.get("uptimeSeconds"))
    except (TypeError, ValueError):
        return None
    return round(max(0.0, value), 1)


class RunpodCLIError(RuntimeError):
    def __init__(self, message, stderr="", returncode=None):
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


class RunpodManager:
    def __init__(self, state_dir=None, runpodctl_bin=None, autostart=None):
        self.state_dir = Path(state_dir or os.environ.get("BSP_RUNPOD_STATE_DIR", DEFAULT_STATE_DIR))
        self.config_path = self.state_dir / "config.json"
        self.state_path = self.state_dir / "state.json"
        self.events_path = self.state_dir / "events.jsonl"
        self.runpodctl_bin = runpodctl_bin or os.environ.get("BSP_RUNPODCTL_BIN", "/usr/bin/runpodctl")
        self.poll_seconds = float(os.environ.get("BSP_RUNPOD_POLL_SECONDS", "5"))
        self.retry_seconds = float(os.environ.get("BSP_RUNPOD_RETRY_SECONDS", "30"))
        self.options_refresh_seconds = float(os.environ.get("BSP_RUNPOD_OPTIONS_REFRESH_SECONDS", "300"))
        self.command_timeout_seconds = float(os.environ.get("BSP_RUNPOD_COMMAND_TIMEOUT_SECONDS", "90"))
        self.health_timeout_seconds = float(os.environ.get("BSP_RUNPOD_HEALTH_TIMEOUT_SECONDS", "5"))
        self.autostart = parse_bool(
            os.environ.get("BSP_RUNPOD_AUTOSTART"),
            True if autostart is None else autostart,
        )
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.shutdown_event = threading.Event()
        self.worker = None
        self.last_options_refresh = 0.0
        self.next_retry_at = 0.0
        self.start_request_at = 0.0
        self.stop_request_at = 0.0
        self.startup_started_monotonic = None
        self.stop_started_monotonic = None
        self.gpu_options = copy.deepcopy(DEFAULT_GPU_OPTIONS)
        self.data_center_options = [
            {
                **copy.deepcopy(item),
                "deployment_region": deployment_region_for_data_center(item["id"]),
            }
            for item in DEFAULT_DATA_CENTER_OPTIONS
        ]

        default_config = {
            "allowed_gpu_ids": [item["id"] for item in DEFAULT_GPU_OPTIONS],
            "priority_gpu_ids": copy.deepcopy(DEFAULT_PRIORITY_GPU_IDS),
            "allowed_data_center_ids": [item["id"] for item in DEFAULT_DATA_CENTER_OPTIONS],
            "deployment_region": DEFAULT_DEPLOYMENT_REGION,
            "priority_data_center_id": DEFAULT_PRIORITY_DATA_CENTER,
            "priority_data_center_ids": [DEFAULT_PRIORITY_DATA_CENTER],
            "cloud_type": "SECURE",
            "container_disk_gb": 80,
            "container_port": DEFAULT_CONTAINER_PORT,
            "image": os.environ.get("BSP_RUNPOD_IMAGE", DEFAULT_IMAGE),
            "min_cuda_version": "12.8",
            "pod_name": DEFAULT_POD_NAME,
            "volume_gb": 120,
            "volume_mount_path": "/workspace",
        }
        self.config = self._normalize_config(read_json(self.config_path, default_config), default_config)
        atomic_write_json(self.config_path, self.config)

        self.state = read_json(self.state_path, {})
        self.state.setdefault("pod_id", None)
        self.state.setdefault("pod_name", self.config["pod_name"])
        self.state.setdefault("endpoint", None)
        self.state.setdefault("server_url", None)
        self.state.setdefault("gpu_id", None)
        self.state.setdefault("gpu_name", None)
        self.state.setdefault("data_center_id", None)
        self.state.setdefault("cost_per_hour", None)
        self.state.setdefault("runtime_status", "unknown")
        self.state.setdefault("machine_uptime_seconds", None)
        self.state.setdefault("status", "stopped")
        self.state.setdefault("phase", "idle")
        self.state.setdefault("message", "RunPod processor is stopped")
        self.state.setdefault("last_error", None)
        self.state.setdefault("desired_running", False)
        self.state.setdefault("startup_kind", None)
        self.state.setdefault("startup_started_at", None)
        self.state.setdefault("startup_duration_seconds", None)
        self.state.setdefault("stop_started_at", None)
        self.state.setdefault("stop_duration_seconds", None)
        self.state.setdefault("updated_at", utc_now())
        self.state.setdefault("last_event", None)
        self.state.setdefault("boot_id", self._boot_id())
        if self.autostart:
            self.state["desired_running"] = True
            self.state["status"] = "starting"
            self.state["phase"] = "boot"
            self.state["message"] = "Waiting to start the RunPod processor"
            self.state["ready_at"] = None
            self.state["stopped_at"] = None
            self.state["startup_kind"] = None
            self.state["startup_started_at"] = None
            self.state["startup_duration_seconds"] = None
            self.state["machine_uptime_seconds"] = 0.0
        self._save_state()
        self._event("manager_initialized", f"manager initialized; autostart={self.autostart}")

    @staticmethod
    def _boot_id():
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            return None

    @staticmethod
    def _normalize_config(config, defaults):
        supported_gpu_ids = [item["id"] for item in DEFAULT_GPU_OPTIONS]
        supported_gpu_id_set = set(supported_gpu_ids)
        has_priority_gpu_ids = "priority_gpu_ids" in config
        legacy_allowed_gpu_ids = config.get("allowed_gpu_ids")
        normalized = copy.deepcopy(defaults)
        normalized.update({key: value for key, value in config.items() if key in normalized})
        legacy_dc_ids = config.get("allowed_data_center_ids")
        if "priority_data_center_ids" not in config:
            singular_priority = str(config.get("priority_data_center_id") or "").strip()
            if singular_priority:
                normalized["priority_data_center_ids"] = [singular_priority]
            elif isinstance(legacy_dc_ids, list):
                legacy_dc_ids = [str(value) for value in legacy_dc_ids if value]
                if DEFAULT_PRIORITY_DATA_CENTER in legacy_dc_ids:
                    normalized["priority_data_center_ids"] = [DEFAULT_PRIORITY_DATA_CENTER]
                elif legacy_dc_ids:
                    normalized["priority_data_center_ids"] = [legacy_dc_ids[0]]
        for key in (
            "allowed_gpu_ids",
            "priority_gpu_ids",
            "allowed_data_center_ids",
            "priority_data_center_ids",
        ):
            values = normalized.get(key)
            if not isinstance(values, list):
                normalized[key] = copy.deepcopy(defaults[key])
            else:
                normalized[key] = list(dict.fromkeys(str(value) for value in values if value))
        if not has_priority_gpu_ids and isinstance(legacy_allowed_gpu_ids, list):
            legacy_priorities = [
                str(value)
                for value in legacy_allowed_gpu_ids
                if str(value) in supported_gpu_id_set
            ]
            # Before priority_gpu_ids existed, checked cards meant "allowed".
            # Preserve an explicit subset as the initial priority selection. An
            # untouched all-cards selection migrates to the new H100 default.
            if legacy_priorities and set(legacy_priorities) != supported_gpu_id_set:
                normalized["priority_gpu_ids"] = list(dict.fromkeys(legacy_priorities))
        normalized["allowed_gpu_ids"] = supported_gpu_ids
        normalized["priority_gpu_ids"] = [
            gpu_id
            for gpu_id in normalized["priority_gpu_ids"]
            if gpu_id in supported_gpu_id_set
        ]
        if normalized.get("deployment_region") not in {
            option["id"] for option in DEPLOYMENT_REGION_OPTIONS
        }:
            normalized["deployment_region"] = DEFAULT_DEPLOYMENT_REGION
        priority_ids = [
            data_center_id
            for data_center_id in normalized["priority_data_center_ids"]
            if deployment_region_for_data_center(data_center_id) == normalized["deployment_region"]
        ]
        if not priority_ids:
            fallback_ids = [
                item["id"]
                for item in DEFAULT_DATA_CENTER_OPTIONS
                if deployment_region_for_data_center(item["id"]) == normalized["deployment_region"]
            ]
            priority_ids = fallback_ids[:1]
        normalized["priority_data_center_ids"] = priority_ids
        normalized["priority_data_center_id"] = priority_ids[0] if priority_ids else None
        return normalized

    def _save_state(self):
        self.state["updated_at"] = utc_now()
        atomic_write_json(self.state_path, self.state)

    def _update_state(self, **changes):
        changed = False
        with self.lock:
            for key, value in changes.items():
                if self.state.get(key) != value:
                    self.state[key] = value
                    changed = True
            if changed:
                self._save_state()
        return changed

    def _event(self, kind, message, **details):
        event = {
            "at": utc_now(),
            "boot_id": self._boot_id(),
            "kind": kind,
            "message": message,
            **details,
        }
        with self.lock:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a") as events_file:
                events_file.write(json.dumps(event, sort_keys=True) + "\n")
            self.state["last_event"] = event
            self._save_state()
        print(f"runpod> {kind}: {message}", flush=True)

    def _run_cli(self, *args, allow_empty=False):
        command = [self.runpodctl_bin, *args]
        try:
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RunpodCLIError(f"runpodctl failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "runpodctl command failed").strip()
            raise RunpodCLIError(detail[-1200:], stderr=detail, returncode=result.returncode)
        if not result.stdout.strip():
            return {} if allow_empty else None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RunpodCLIError("runpodctl returned invalid JSON") from exc

    def _refresh_options(self, force=False):
        now = time.monotonic()
        if (
            not force
            and self.last_options_refresh > 0
            and now - self.last_options_refresh < self.options_refresh_seconds
        ):
            return
        gpu_payload = self._run_cli("gpu", "list", "--include-unavailable", "-o", "json")
        dc_payload = self._run_cli("datacenter", "list", "-o", "json")

        supported_ids = {item["id"] for item in DEFAULT_GPU_OPTIONS}
        gpu_options = []
        for gpu in gpu_payload if isinstance(gpu_payload, list) else []:
            gpu_id = gpu.get("gpuId")
            if gpu_id not in supported_ids:
                continue
            availability = {}
            for item in gpu.get("dataCenterAvailability") or []:
                dc_id = item.get("dataCenterId")
                if dc_id:
                    availability[dc_id] = str(item.get("stockStatus") or "none")
            gpu_options.append({
                "id": gpu_id,
                "name": gpu.get("displayName") or gpu_id,
                "memory_gb": gpu.get("memoryInGb"),
                "secure_price_per_hour": gpu.get("securePricePerHr"),
                "community_price_per_hour": gpu.get("communityPricePerHr"),
                "available": bool(gpu.get("available")),
                "stock_status": gpu.get("stockStatus") or "none",
                "data_center_availability": availability,
            })
        order = {item["id"]: index for index, item in enumerate(DEFAULT_GPU_OPTIONS)}
        gpu_options.sort(key=lambda item: order.get(item["id"], 999))

        priority_dc_ids = set(self.config.get("priority_data_center_ids") or [])
        region_order = {
            option["id"]: index for index, option in enumerate(DEPLOYMENT_REGION_OPTIONS)
        }
        dc_records = {
            item["id"]: copy.deepcopy(item)
            for item in DEFAULT_DATA_CENTER_OPTIONS
        }
        for dc in dc_payload if isinstance(dc_payload, list) else []:
            dc_id = str(dc.get("id") or "")
            deployment_region = deployment_region_for_data_center(dc_id)
            if not dc_id or not deployment_region:
                continue
            dc_records[dc_id] = {
                **dc_records.get(dc_id, {}),
                "id": dc_id,
                "name": dc.get("name") or dc_id,
                "location": str(dc.get("location") or "") or deployment_region,
            }
        dc_options = []
        for dc_id, dc in dc_records.items():
            deployment_region = deployment_region_for_data_center(dc_id)
            if not deployment_region:
                continue
            dc_options.append({
                "id": dc_id,
                "name": dc.get("name") or dc_id,
                "location": dc.get("location") or deployment_region,
                "deployment_region": deployment_region,
                "preferred": dc_id in priority_dc_ids,
            })
        dc_options.sort(key=lambda item: (
            region_order.get(item["deployment_region"], 999),
            item["id"],
        ))

        with self.lock:
            if gpu_options:
                self.gpu_options = gpu_options
            self.data_center_options = dc_options
            self.last_options_refresh = now

    def _endpoint_for(self, pod_id):
        port = int(self.config["container_port"])
        server_url = f"https://{pod_id}-{port}.proxy.runpod.net"
        return server_url, f"{server_url}/api/process"

    def _deployment_data_center_ids(self, deployment_region=None):
        deployment_region = deployment_region or self.config.get("deployment_region")
        if deployment_region not in {option["id"] for option in DEPLOYMENT_REGION_OPTIONS}:
            return []
        ids = [
            item["id"]
            for item in self.data_center_options
            if item.get("id")
            and (item.get("deployment_region") or deployment_region_for_data_center(item["id"]))
            == deployment_region
        ]
        ids.extend(
            item["id"]
            for item in DEFAULT_DATA_CENTER_OPTIONS
            if deployment_region_for_data_center(item["id"]) == deployment_region
        )
        return list(dict.fromkeys(ids))

    def _priority_data_center_ids(self, deployment_region=None):
        deployment_region = deployment_region or self.config.get("deployment_region")
        data_center_ids = self._deployment_data_center_ids(deployment_region)
        configured = self.config.get("priority_data_center_ids") or []
        priorities = [data_center_id for data_center_id in configured if data_center_id in data_center_ids]
        if priorities:
            return priorities
        if (
            deployment_region == DEFAULT_DEPLOYMENT_REGION
            and DEFAULT_PRIORITY_DATA_CENTER in data_center_ids
        ):
            return [DEFAULT_PRIORITY_DATA_CENTER]
        return data_center_ids[:1]

    def _priority_data_center_id(self):
        priority_ids = self._priority_data_center_ids()
        return priority_ids[0] if priority_ids else None

    def _begin_startup_timer(self, startup_kind, force=False):
        if self.startup_started_monotonic is not None and not force:
            return
        self.startup_started_monotonic = time.monotonic()
        self._update_state(
            startup_kind=startup_kind,
            startup_started_at=utc_now(),
            startup_duration_seconds=None,
            ready_at=None,
        )

    def _startup_elapsed_seconds(self, ended_at=None):
        if self.startup_started_monotonic is not None:
            return round(max(0.0, time.monotonic() - self.startup_started_monotonic), 1)
        return elapsed_seconds(self.state.get("startup_started_at"), ended_at)

    def _begin_stop_timer(self):
        if self.stop_started_monotonic is not None:
            return
        self.stop_started_monotonic = time.monotonic()
        self._update_state(
            stop_started_at=utc_now(),
            stop_duration_seconds=None,
        )

    def _stop_elapsed_seconds(self, ended_at=None):
        if self.stop_started_monotonic is not None:
            return round(max(0.0, time.monotonic() - self.stop_started_monotonic), 1)
        return elapsed_seconds(self.state.get("stop_started_at"), ended_at)

    def _pod_details(self, pod_id):
        return self._run_cli("pod", "get", pod_id, "--include-machine", "-o", "json")

    def _adopt_named_pod(self):
        payload = self._run_cli(
            "pod", "list", "--all", "--name", self.config["pod_name"], "-o", "json"
        )
        pods = payload if isinstance(payload, list) else []
        matches = [pod for pod in pods if pod.get("name") == self.config["pod_name"]]
        if not matches:
            return False
        pod = matches[-1]
        pod_id = pod_id_from_payload(pod)
        if not pod_id:
            return False
        server_url, endpoint = self._endpoint_for(pod_id)
        self._update_state(
            pod_id=pod_id,
            pod_name=self.config["pod_name"],
            server_url=server_url,
            endpoint=endpoint,
            runtime_status=pod_runtime_status(pod),
        )
        self._event("pod_adopted", f"adopted managed pod {pod_id}", pod_id=pod_id)
        return True

    def _candidate_pairs(self):
        gpu_by_id = {item["id"]: item for item in self.gpu_options}
        allowed_gpus = [
            item["id"]
            for item in DEFAULT_GPU_OPTIONS
            if item["id"] in gpu_by_id
        ]
        priority_gpu_ids = [
            gpu_id
            for gpu_id in self.config.get("priority_gpu_ids", [])
            if gpu_id in gpu_by_id
        ]
        priority_gpu_order = {
            gpu_id: index for index, gpu_id in enumerate(priority_gpu_ids)
        }
        allowed_gpu_order = {gpu_id: index for index, gpu_id in enumerate(allowed_gpus)}
        allowed_gpus.sort(key=lambda gpu_id: (
            0 if gpu_id in priority_gpu_order else 1,
            priority_gpu_order.get(gpu_id, allowed_gpu_order[gpu_id]),
        ))
        selected_dcs = self._deployment_data_center_ids()
        priority_dc_ids = self._priority_data_center_ids()
        priority_order = {dc_id: index for index, dc_id in enumerate(priority_dc_ids)}
        selected_dcs.sort(key=lambda dc_id: (
            priority_order.get(dc_id, len(priority_order)),
            dc_id,
        ))
        candidates = []
        for dc_id in selected_dcs:
            for gpu_id in allowed_gpus:
                availability = gpu_by_id[gpu_id].get("data_center_availability", {})
                stock = str(availability.get(dc_id) or "none").lower()
                if stock not in ("none", "unavailable", "sold out"):
                    candidates.append((gpu_id, dc_id))
        return candidates

    def _create_pod(self):
        self._refresh_options(force=True)
        if not self._deployment_data_center_ids():
            raise RunpodCLIError("The selected deployment region has no RunPod data centers")
        candidates = self._candidate_pairs()
        if not candidates:
            raise RunpodCLIError(
                "No supported H100/H200/B200 card currently has stock in the selected deployment region"
            )
        self._begin_startup_timer("cold", force=True)

        environment = json.dumps({
            "QWEN_PARKING_MODE": "all_cuda",
            "MODEL_CACHE_DIR": "/workspace/model-cache",
            "HF_HOME": "/workspace/huggingface",
            "OUTLINE_PNG_COMPRESS_LEVEL": "1",
        }, separators=(",", ":"))
        failures = []
        for gpu_id, dc_id in candidates:
            self._update_state(
                status="starting",
                phase="creating",
                message=f"Requesting {gpu_id} in {dc_id}",
                last_error=None,
            )
            command = [
                "pod", "create",
                "--name", self.config["pod_name"],
                "--image", self.config["image"],
                "--gpu-id", gpu_id,
                "--gpu-count", "1",
                "--cloud-type", self.config["cloud_type"],
                "--ports", f"{self.config['container_port']}/http",
                "--container-disk-in-gb", str(self.config["container_disk_gb"]),
                "--volume-in-gb", str(self.config["volume_gb"]),
                "--volume-mount-path", self.config["volume_mount_path"],
                "--min-cuda-version", self.config["min_cuda_version"],
                "--data-center-ids", dc_id,
                "--env", environment,
            ]
            safety_minutes = os.environ.get("BSP_RUNPOD_TERMINATE_AFTER_MINUTES")
            if safety_minutes:
                terminate_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=float(safety_minutes))
                command.extend(("--terminate-after", terminate_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")))
            try:
                payload = self._run_cli(*command)
            except RunpodCLIError as exc:
                failures.append(f"{gpu_id} in {dc_id}: {exc}")
                continue
            pod_id = pod_id_from_payload(payload)
            if not pod_id:
                failures.append(f"{gpu_id} in {dc_id}: create response had no pod id")
                continue
            server_url, endpoint = self._endpoint_for(pod_id)
            gpu_name = next((item["name"] for item in self.gpu_options if item["id"] == gpu_id), gpu_id)
            price = next((item.get("secure_price_per_hour") for item in self.gpu_options if item["id"] == gpu_id), None)
            self._update_state(
                pod_id=pod_id,
                pod_name=self.config["pod_name"],
                server_url=server_url,
                endpoint=endpoint,
                gpu_id=gpu_id,
                gpu_name=gpu_name,
                data_center_id=dc_id,
                cost_per_hour=price,
                runtime_status="initializing",
                machine_uptime_seconds=0.0,
                status="starting",
                phase="initializing",
                message=f"Pod {pod_id} is initializing",
                last_error=None,
                created_at=utc_now(),
            )
            self._event(
                "pod_created",
                f"created pod {pod_id} with {gpu_name} in {dc_id}",
                pod_id=pod_id,
                gpu_id=gpu_id,
                data_center_id=dc_id,
            )
            return
        raise RunpodCLIError("; ".join(failures)[-2000:] or "RunPod could not create a pod")

    def _current_pod_allowed(self):
        gpu_id = self.state.get("gpu_id")
        dc_id = self.state.get("data_center_id")
        if not gpu_id or not dc_id:
            return True
        return (
            gpu_id in {item["id"] for item in DEFAULT_GPU_OPTIONS}
            and dc_id in self._deployment_data_center_ids()
        )

    def _start_existing_pod(self, pod_id):
        if time.monotonic() - self.start_request_at < 20:
            return
        self.start_request_at = time.monotonic()
        self._begin_startup_timer("warm")
        self._update_state(
            status="starting",
            phase="starting",
            message=f"Starting pod {pod_id}",
            last_error=None,
        )
        self._run_cli("pod", "start", pod_id, "-o", "json", allow_empty=True)
        self._event("pod_start_requested", f"start requested for pod {pod_id}", pod_id=pod_id)

    def _stop_existing_pod(self, pod_id):
        if time.monotonic() - self.stop_request_at < 10:
            return
        self.stop_request_at = time.monotonic()
        self._begin_stop_timer()
        self._update_state(
            status="stopping",
            phase="stopping",
            message=f"Stopping pod {pod_id}",
            last_error=None,
        )
        self._run_cli("pod", "stop", pod_id, "-o", "json", allow_empty=True)
        self._event("pod_stop_requested", f"stop requested for pod {pod_id}", pod_id=pod_id)

    def _delete_stopped_pod(self, pod_id, reason):
        self._update_state(
            status="starting",
            phase="replacing",
            message=f"Replacing stopped pod {pod_id}: {reason}",
            last_error=None,
        )
        self._run_cli("pod", "delete", pod_id, "-o", "json", allow_empty=True)
        self._event(
            "pod_deleted_for_replacement",
            f"deleted stopped pod {pod_id}: {reason}",
            pod_id=pod_id,
        )
        self._clear_terminated_pod()

    def _check_application(self):
        server_url = self.state.get("server_url")
        if not server_url:
            return False
        try:
            response = requests.get(f"{server_url}/api/status", timeout=self.health_timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            self._update_state(
                status="starting",
                phase="application_starting",
                message=f"Pod is running; waiting for bsp-convert HTTP ({exc})",
            )
            return False
        preload = payload.get("preload") if isinstance(payload, dict) else None
        if isinstance(preload, dict) and preload.get("state") == "failed":
            error = str(preload.get("error") or "bsp-convert model preload failed")
            self._update_state(
                status="error",
                phase="application_error",
                message=error,
                last_error=error,
            )
            return False
        model_loaded = bool(payload.get("model_loaded")) if isinstance(payload, dict) else False
        preload_loaded = isinstance(preload, dict) and preload.get("state") == "loaded"
        if not (model_loaded or preload_loaded):
            stage = preload.get("stage") if isinstance(preload, dict) else None
            progress = preload.get("progress") if isinstance(preload, dict) else None
            suffix = f" ({stage}" if stage else ""
            if suffix and isinstance(progress, (int, float)):
                suffix += f", {progress * 100:.0f}%"
            if suffix:
                suffix += ")"
            self._update_state(
                status="starting",
                phase="model_loading",
                message=f"bsp-convert is loading the model{suffix}",
            )
            return False
        first_running = self.state.get("status") != "running"
        ready_at = self.state.get("ready_at")
        startup_duration = self.state.get("startup_duration_seconds")
        if first_running:
            self._begin_startup_timer(self.state.get("startup_kind") or "warm")
            ready_at = utc_now()
            startup_duration = self._startup_elapsed_seconds(ready_at)
        self._update_state(
            status="running",
            phase="ready",
            message="bsp-convert is ready",
            last_error=None,
            ready_at=ready_at or utc_now(),
            startup_duration_seconds=startup_duration,
        )
        if first_running:
            self._event(
                "processor_ready",
                f"bsp-convert is ready at {self.state.get('endpoint')}",
                pod_id=self.state.get("pod_id"),
                startup_kind=self.state.get("startup_kind"),
                startup_duration_seconds=startup_duration,
            )
        return True

    def _clear_terminated_pod(self):
        self._update_state(
            pod_id=None,
            endpoint=None,
            server_url=None,
            gpu_id=None,
            gpu_name=None,
            data_center_id=None,
            cost_per_hour=None,
            runtime_status="terminated",
            machine_uptime_seconds=None,
        )

    def reconcile(self):
        self._refresh_options()
        desired_running = bool(self.state.get("desired_running"))
        pod_id = self.state.get("pod_id")
        if not pod_id:
            try:
                self._adopt_named_pod()
            except RunpodCLIError:
                pass
            pod_id = self.state.get("pod_id")

        if not pod_id:
            if desired_running:
                if time.monotonic() < self.next_retry_at:
                    return
                try:
                    self._create_pod()
                except RunpodCLIError as exc:
                    self.next_retry_at = time.monotonic() + self.retry_seconds
                    message = str(exc)
                    blocked = is_capacity_error(message) or (
                        "No selected" in message
                        or "no pod id" in message
                        or "could not create" in message.lower()
                        or "insufficient" in message.lower()
                    )
                    self._update_state(
                        status="blocked" if blocked else "error",
                        phase="waiting_to_retry",
                        message=message,
                        last_error=message,
                    )
                    self._event("start_blocked" if blocked else "start_error", message)
            else:
                self._update_state(
                    status="stopped",
                    phase="idle",
                    message="RunPod processor is stopped",
                    runtime_status="stopped",
                    last_error=None,
                )
            return

        try:
            pod = self._pod_details(pod_id)
        except RunpodCLIError as exc:
            message = str(exc)
            if any(token in message.lower() for token in ("not found", "does not exist", "terminated")):
                self._event("pod_gone", f"managed pod {pod_id} no longer exists", pod_id=pod_id)
                self._clear_terminated_pod()
                return
            self._update_state(status="error", phase="status_error", message=message, last_error=message)
            return

        runtime = pod_runtime_status(pod)
        runtime_changes = {"runtime_status": runtime}
        machine_uptime = pod_uptime_seconds(pod)
        if machine_uptime is not None:
            runtime_changes["machine_uptime_seconds"] = machine_uptime
        self._update_state(**runtime_changes)
        if runtime == "terminated":
            self._event("pod_terminated", f"managed pod {pod_id} terminated", pod_id=pod_id)
            self._clear_terminated_pod()
            return

        if not desired_running:
            if runtime in ("stopped", "exited"):
                first_stopped = self.state.get("status") != "stopped"
                stopped_at = utc_now() if first_stopped else self.state.get("stopped_at")
                stop_duration = self.state.get("stop_duration_seconds")
                if first_stopped:
                    stop_duration = self._stop_elapsed_seconds(stopped_at)
                self._update_state(
                    status="stopped",
                    phase="idle",
                    message="RunPod processor is stopped",
                    last_error=None,
                    stopped_at=stopped_at,
                    stop_duration_seconds=stop_duration,
                )
                if first_stopped:
                    self._event(
                        "pod_stopped",
                        f"pod {pod_id} is stopped",
                        pod_id=pod_id,
                        stop_duration_seconds=stop_duration,
                    )
                    self.stop_started_monotonic = None
            else:
                self._stop_existing_pod(pod_id)
            return

        if runtime in ("stopped", "exited"):
            if not self._current_pod_allowed():
                try:
                    self._delete_stopped_pod(
                        pod_id,
                        "card or region is no longer allowed",
                    )
                except RunpodCLIError as exc:
                    message = str(exc)
                    self._update_state(
                        status="error",
                        phase="replacement_error",
                        message=message,
                        last_error=message,
                    )
                return
            try:
                self._start_existing_pod(pod_id)
            except RunpodCLIError as exc:
                message = str(exc)
                if is_capacity_error(message):
                    try:
                        self._delete_stopped_pod(pod_id, "its GPU is no longer available")
                    except RunpodCLIError as delete_exc:
                        message = f"{message}; replacement cleanup failed: {delete_exc}"
                        self._update_state(
                            status="error",
                            phase="replacement_error",
                            message=message,
                            last_error=message,
                        )
                else:
                    self._update_state(
                        status="error",
                        phase="start_error",
                        message=message,
                        last_error=message,
                    )
            return

        if runtime in ("initializing", "unknown"):
            reason = pod.get("runtimeStatusReason") if isinstance(pod, dict) else None
            self._update_state(
                status="starting",
                phase="initializing",
                message=f"Pod {pod_id} is initializing" + (f" ({reason})" if reason else ""),
            )
            return

        if runtime == "running":
            self._check_application()
            return

        self._update_state(
            status="starting",
            phase=runtime,
            message=f"Pod {pod_id} status is {runtime}",
        )

    def run(self):
        self.worker = threading.current_thread()
        while not self.shutdown_event.is_set():
            try:
                self.reconcile()
            except Exception as exc:  # keep lifecycle supervision alive after unexpected provider data
                message = f"unexpected manager error: {exc}"
                self._update_state(status="error", phase="manager_error", message=message, last_error=message)
                self._event("manager_error", message)
            self.wake.wait(self.poll_seconds)
            self.wake.clear()

    def start_worker(self):
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self.run, name="runpod-manager", daemon=True)
        self.worker.start()

    def request_start(self):
        if self.state.get("desired_running") and self.state.get("status") in ("starting", "running"):
            return
        self.next_retry_at = 0
        self.startup_started_monotonic = None
        self._update_state(
            desired_running=True,
            status="starting",
            phase="requested",
            message="RunPod start requested",
            last_error=None,
            stopped_at=None,
            ready_at=None,
            startup_kind=None,
            startup_started_at=None,
            startup_duration_seconds=None,
            machine_uptime_seconds=0.0,
        )
        self._event("manual_start", "manual RunPod start requested")
        self.wake.set()

    def request_stop(self, reason="manual"):
        self.startup_started_monotonic = None
        if (
            self.state.get("pod_id")
            and self.state.get("status") != "stopped"
            and self.state.get("desired_running")
        ):
            self.stop_started_monotonic = None
            self._begin_stop_timer()
        self._update_state(
            desired_running=False,
            status="stopping" if self.state.get("pod_id") else "stopped",
            phase="requested",
            message="RunPod stop requested" if self.state.get("pod_id") else "RunPod processor is stopped",
            last_error=None,
            ready_at=None,
        )
        self._event(f"{reason}_stop", f"{reason} RunPod stop requested")
        self.wake.set()

    def update_config(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("configuration must be a JSON object")
        priority_gpu_ids = payload.get("priority_gpu_ids")
        if priority_gpu_ids is None:
            # Accept the old UI payload during rolling upgrades. Its checked
            # cards become priorities; every supported card remains allowed.
            priority_gpu_ids = payload.get("allowed_gpu_ids")
        deployment_region = str(payload.get("deployment_region") or "").strip()
        priority_dc_ids = payload.get("priority_data_center_ids")
        if priority_dc_ids is None and payload.get("priority_data_center_id"):
            priority_dc_ids = [payload["priority_data_center_id"]]
        known_gpu_ids = {item["id"] for item in DEFAULT_GPU_OPTIONS}
        known_deployment_regions = {item["id"] for item in DEPLOYMENT_REGION_OPTIONS}
        deployment_dc_ids = self._deployment_data_center_ids(deployment_region)
        if deployment_region not in known_deployment_regions:
            raise ValueError("select a supported deployment region")
        if not isinstance(priority_dc_ids, list) or not priority_dc_ids:
            raise ValueError("select at least one priority data center")
        if not isinstance(priority_gpu_ids, list):
            raise ValueError("priority GPU cards must be a list")
        priority_gpu_ids = list(dict.fromkeys(str(value) for value in priority_gpu_ids))
        priority_dc_ids = list(dict.fromkeys(str(value) for value in priority_dc_ids if value))
        if not priority_dc_ids:
            raise ValueError("select at least one priority data center")
        invalid_priority_ids = [
            data_center_id
            for data_center_id in priority_dc_ids
            if data_center_id not in deployment_dc_ids
        ]
        if invalid_priority_ids:
            raise ValueError("select priority data centers within the deployment region")
        unknown_gpus = [value for value in priority_gpu_ids if value not in known_gpu_ids]
        if unknown_gpus:
            raise ValueError(f"unsupported GPU card(s): {', '.join(unknown_gpus)}")
        with self.lock:
            self.config["allowed_gpu_ids"] = [item["id"] for item in DEFAULT_GPU_OPTIONS]
            self.config["priority_gpu_ids"] = priority_gpu_ids
            self.config["deployment_region"] = deployment_region
            self.config["priority_data_center_ids"] = priority_dc_ids
            self.config["priority_data_center_id"] = priority_dc_ids[0]
            # Retain this derived field so existing installations and diagnostic
            # scripts can read a complete list during the UI migration.
            self.config["allowed_data_center_ids"] = deployment_dc_ids
            atomic_write_json(self.config_path, self.config)
        self._event(
            "configuration_updated",
            "RunPod priorities updated; cards: "
            + (", ".join(priority_gpu_ids) or "none")
            + f"; data centers in {deployment_region}: "
            + ", ".join(priority_dc_ids),
        )
        self.wake.set()
        return self.public_status()

    def public_status(self):
        with self.lock:
            state = copy.deepcopy(self.state)
            config = copy.deepcopy(self.config)
            gpu_options = copy.deepcopy(self.gpu_options)
            dc_options = copy.deepcopy(self.data_center_options)
        deployment_dc_ids = self._deployment_data_center_ids(config["deployment_region"])
        priority_dc_ids = self._priority_data_center_ids(config["deployment_region"])
        priority_dc_id = priority_dc_ids[0] if priority_dc_ids else None
        for option in dc_options:
            option["preferred"] = option.get("id") in priority_dc_ids
        state["config"] = {
            "allowed_gpu_ids": config["allowed_gpu_ids"],
            "priority_gpu_ids": config["priority_gpu_ids"],
            "allowed_data_center_ids": deployment_dc_ids,
            "deployment_region": config["deployment_region"],
            "priority_data_center_id": priority_dc_id,
            "priority_data_center_ids": priority_dc_ids,
            "image": config["image"],
            "preferred_data_center_id": priority_dc_id,
        }
        state["deployment_region_options"] = copy.deepcopy(DEPLOYMENT_REGION_OPTIONS)
        state["gpu_options"] = gpu_options
        state["data_center_options"] = dc_options
        state["startup_elapsed_seconds"] = None
        if state.get("desired_running") and state.get("startup_duration_seconds") is None:
            state["startup_elapsed_seconds"] = self._startup_elapsed_seconds()
        state["configuration_applies_on_next_creation"] = not self._current_pod_allowed()
        return state


def create_app(manager):
    from flask import Flask, request

    app = Flask(__name__)

    @app.get("/status")
    def status():
        return manager.public_status()

    @app.post("/start")
    def start():
        manager.request_start()
        return manager.public_status(), 202

    @app.post("/stop")
    def stop():
        manager.request_stop(reason="shutdown" if request.args.get("shutdown") == "1" else "manual")
        return manager.public_status(), 202

    @app.post("/config")
    def config():
        try:
            return manager.update_config(request.get_json(silent=True) or {}), 200
        except ValueError as exc:
            return {"error": str(exc)}, 400

    return app


def shutdown_managed_pod(state_dir, manager_url, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    try:
        requests.post(f"{manager_url.rstrip('/')}/stop?shutdown=1", timeout=5).raise_for_status()
        while time.monotonic() < deadline:
            payload = requests.get(f"{manager_url.rstrip('/')}/status", timeout=5).json()
            if payload.get("status") == "stopped":
                print("runpod> shutdown stop confirmed by manager", flush=True)
                return 0
            time.sleep(2)
    except (requests.RequestException, ValueError):
        pass

    # Fallback for a failed daemon: stop only the exact pod id recorded in the
    # manager state file.  Never discover or touch unrelated account pods here.
    state_path = Path(state_dir) / "state.json"
    state = read_json(state_path, {})
    pod_id = state.get("pod_id")
    if not pod_id:
        print("runpod> no managed pod to stop", flush=True)
        return 0
    runpodctl_bin = os.environ.get("BSP_RUNPODCTL_BIN", "/usr/bin/runpodctl")
    result = subprocess.run(
        [runpodctl_bin, "pod", "stop", str(pod_id), "-o", "json"],
        text=True,
        capture_output=True,
        timeout=max(5, int(timeout_seconds)),
        check=False,
    )
    if result.returncode != 0:
        print((result.stderr or result.stdout or "runpodctl stop failed").strip(), flush=True)
        return 1
    print(f"runpod> fallback stop requested for {pod_id}", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=("serve", "shutdown"), default="serve")
    parser.add_argument("--state-dir", default=os.environ.get("BSP_RUNPOD_STATE_DIR", DEFAULT_STATE_DIR))
    parser.add_argument("--manager-url", default=f"http://127.0.0.1:{DEFAULT_MANAGER_PORT}")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()

    if args.command == "shutdown":
        raise SystemExit(shutdown_managed_pod(args.state_dir, args.manager_url, args.timeout))

    manager = RunpodManager(state_dir=args.state_dir)
    manager.start_worker()
    app = create_app(manager)
    port = int(os.environ.get("BSP_RUNPOD_MANAGER_PORT", str(DEFAULT_MANAGER_PORT)))
    from waitress import serve

    try:
        serve(app, host="127.0.0.1", port=port, threads=6)
    finally:
        manager.shutdown_event.set()
        manager.wake.set()
        if manager.worker:
            manager.worker.join(timeout=5)


if __name__ == "__main__":
    main()
