#!/usr/bin/env python3
import argparse
import dataclasses
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
import requests
import serial


BASE_CENTER = (50.0, 65.0)
DEFAULT_PHONE = "http://echo.local:8080"
DEFAULT_PORT = "/dev/ttyUSB0"
RECOMMENDED_PARAMS = {
    "xjm": 2000.0,
    "yjm": 2000.0,
    "xvm": 3000.0,
    "yvm": 3000.0,
}
LEGACY_PARAMS = {
    "xjm": 2500.0,
    "yjm": 2500.0,
    "xvm": 3000.0,
    "yvm": 3000.0,
}


@dataclasses.dataclass
class Trial:
    name: str
    params: dict
    distance: float
    rest: float = 0.45
    pre_idle: float = 0.7
    post_idle: float = 1.0
    cycles: int = 1


class TinyG:
    def __init__(self, port, baudrate=115200):
        self.ser = serial.Serial(port, baudrate, timeout=1.0, write_timeout=2, rtscts=True)
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def drain(self, seconds=0.25):
        deadline = time.monotonic() + seconds
        lines = []
        while time.monotonic() < deadline:
            line = self.ser.readline()
            if line:
                lines.append(line.decode("utf-8", "replace").strip())
            else:
                time.sleep(0.02)
        return lines

    def command(self, command, timeout=5.0):
        if not command.endswith("\n"):
            command += "\n"
        command_text = command.strip()
        self.ser.write(command.encode("ascii"))
        self.ser.flush()
        deadline = time.monotonic() + timeout
        lines = []
        last_error = None
        while time.monotonic() < deadline:
            raw = self.ser.readline()
            if not raw:
                continue
            text = raw.decode("utf-8", "replace").strip()
            lines.append(text)
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed_text = self.parse_text_response(command_text, text)
                if parsed_text is not None:
                    return parsed_text, lines
                continue
            if "er" in parsed:
                last_error = parsed
                continue
            if "r" in parsed:
                return parsed, lines
            if "sr" in parsed and command.strip() == "?":
                return parsed, lines
            if command_text.lower().startswith("g") and "f" in parsed:
                return parsed, lines
        if last_error is not None:
            raise RuntimeError(f"TinyG error for {command.strip()}: {last_error}")
        raise TimeoutError(f"Timed out waiting for TinyG response to {command.strip()}: {lines[-5:]}")

    def parse_text_response(self, command, text):
        lower = text.lower()
        if command.startswith("$") and text.startswith("["):
            return {"text": text}
        if command.lower().startswith("g") and (" ok>" in lower or lower.endswith("ok>") or lower == "ok"):
            return {"text": text}
        return None

    def query_value(self, key):
        parsed, _ = self.command(f"${key}")
        if "text" in parsed:
            return parse_tinyg_text_value(parsed["text"])
        response = parsed.get("r", {})
        if key in response:
            return response[key]
        if f"${key}" in response:
            return response[f"${key}"]
        if len(response) == 1:
            return next(iter(response.values()))
        return response

    def set_value(self, key, value):
        parsed, _ = self.command(f"${key}={value:g}")
        return parsed

    def move(self, x, y):
        self.command(f"g0x{x:.4f}y{y:.4f}")


def post_json(url, payload=None, timeout=10):
    response = requests.post(url, json=payload or {}, timeout=timeout)
    if response.status_code == 409 and url.endswith("/recordings/stop"):
        return response.json()
    response.raise_for_status()
    return response.json()


def get_json(url, timeout=20):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def normalize_phone_url(phone):
    phone = phone.rstrip("/")
    if not re.match(r"^https?://", phone):
        phone = f"http://{phone}"
    return phone


def parse_tinyg_text_value(text):
    pieces = re.split(r"\s{2,}", text.strip())
    if len(pieces) < 2:
        return text
    match = re.search(r"[-+]?\d+(?:\.\d+)?", pieces[1])
    if not match:
        return text
    value = float(match.group(0))
    return int(value) if value.is_integer() else value


def estimate_move_time(start, end, velocity_mm_min):
    distance = math.dist(start, end)
    velocity_mm_s = max(1.0, velocity_mm_min / 60.0)
    # TinyG jerk limiting dominates short strokes, so use a conservative floor.
    return max(0.25, distance / velocity_mm_s * 1.8 + 0.15)


def trial_points(distance, cycles=1):
    cx, cy = BASE_CENTER
    single = [
        (cx + distance, cy),
        (cx, cy),
        (cx, cy + distance),
        (cx, cy),
        (cx + distance, cy + distance),
        (cx, cy),
        (cx - distance, cy),
        (cx, cy),
        (cx, cy - distance),
        (cx, cy),
    ]
    points = []
    for _ in range(cycles):
        points.extend(single)
    return points


def rolling_mean(values, window):
    if window <= 1 or len(values) < window:
        return np.repeat(np.mean(values, axis=0, keepdims=True), len(values), axis=0)
    kernel = np.ones(window) / window
    columns = [np.convolve(values[:, i], kernel, mode="same") for i in range(values.shape[1])]
    return np.column_stack(columns)


def motion_vectors(payload, pre_idle):
    motion = payload.get("deviceMotion", [])
    if motion:
        t = np.array([sample["t"] for sample in motion], dtype=float)
        vec = np.array(
            [
                [
                    sample["userAccelerationX"],
                    sample["userAccelerationY"],
                    sample["userAccelerationZ"],
                ]
                for sample in motion
            ],
            dtype=float,
        )
        source = "deviceMotion.userAcceleration"
    else:
        accel = payload.get("accelerometer", [])
        t = np.array([sample["t"] for sample in accel], dtype=float)
        vec = np.array([[sample["x"], sample["y"], sample["z"]] for sample in accel], dtype=float)
        baseline_mask = t < max(0.2, pre_idle * 0.8)
        baseline = np.median(vec[baseline_mask], axis=0) if np.any(baseline_mask) else np.median(vec, axis=0)
        vec = vec - baseline
        source = "accelerometer.demeaned"
    return t, vec, source


def analyze(payload, trial, timeline):
    t, vec, source = motion_vectors(payload, trial.pre_idle)
    if len(t) < 5:
        return {
            "source": source,
            "sample_count": int(len(t)),
            "error": "not enough motion samples",
            "score": float("inf"),
        }

    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.01
    hz = 1.0 / dt if dt > 0 else 0.0
    window = max(3, int(round(0.20 / max(dt, 0.001))))
    low = rolling_mean(vec, window)
    high = vec - low
    mag = np.linalg.norm(vec, axis=1)
    hf_mag = np.linalg.norm(high, axis=1)

    baseline_mask = t < max(0.2, trial.pre_idle * 0.8)
    if not np.any(baseline_mask):
        baseline_mask = np.arange(len(t)) < max(1, min(10, len(t)))
    baseline_hf_rms = rms(hf_mag[baseline_mask])
    threshold = max(0.012, 4.0 * baseline_hf_rms)

    active_rms = []
    active_peak = []
    settle_rms = []
    settle_peak = []
    settle_times = []

    commands = timeline["commands"]
    for i, command in enumerate(commands):
        start_t = command["t"]
        end_t = start_t + command["estimated_move_time"]
        next_t = commands[i + 1]["t"] if i + 1 < len(commands) else timeline["stop_t"] - 0.1
        settle_end = max(end_t, min(next_t, end_t + trial.rest))

        active_mask = (t >= start_t) & (t <= end_t)
        settle_mask = (t > end_t) & (t <= settle_end)
        if np.any(active_mask):
            active_rms.append(rms(hf_mag[active_mask]))
            active_peak.append(float(np.max(mag[active_mask])))
        if np.any(settle_mask):
            settle_segment = hf_mag[settle_mask]
            settle_rms.append(rms(settle_segment))
            settle_peak.append(float(np.max(settle_segment)))
            settle_t = t[settle_mask]
            above = settle_t[settle_segment > threshold]
            settle_times.append(float(max(0.0, above[-1] - end_t)) if len(above) else 0.0)

    total_commanded_time = sum(command["estimated_move_time"] for command in commands)
    mean_settle_rms = mean(settle_rms)
    mean_settle_peak = mean(settle_peak)
    mean_settle_time = mean(settle_times)
    peak_g = float(np.max(mag))

    # Lower is better. Keep time in the score, but keep vibration dominant.
    score = (
        1000.0 * mean_settle_rms
        + 120.0 * mean_settle_peak
        + 20.0 * mean_settle_time
        + 0.5 * total_commanded_time
    )

    return {
        "source": source,
        "sample_count": int(len(t)),
        "sample_rate_hz": hz,
        "duration_s": float(t[-1] - t[0]),
        "baseline_hf_rms_g": baseline_hf_rms,
        "threshold_g": threshold,
        "active_hf_rms_g": mean(active_rms),
        "active_peak_g": mean(active_peak),
        "settle_hf_rms_g": mean_settle_rms,
        "settle_hf_peak_g": mean_settle_peak,
        "settle_time_s": mean_settle_time,
        "peak_user_accel_g": peak_g,
        "estimated_commanded_time_s": total_commanded_time,
        "score": score,
    }


def rms(values):
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(values * values)))


def mean(values):
    if not values:
        return 0.0
    return float(np.mean(values))


def apply_params(tinyg, params):
    for key in ("xjm", "yjm", "xvm", "yvm"):
        tinyg.set_value(key, float(params[key]))
    tinyg.command("$ej=1")


def run_trial(tinyg, phone, trial, out_dir, sensor_set, target_hz):
    print(f"trial {trial.name}: params={trial.params} distance={trial.distance:g}mm", flush=True)
    apply_params(tinyg, trial.params)
    tinyg.command("g21")
    tinyg.command("g90")

    # Normalize each trial to the same starting point before recording.
    tinyg.move(*BASE_CENTER)
    time.sleep(1.0)
    tinyg.drain()

    post_json(f"{phone}/recordings/stop", timeout=5)
    start = post_json(
        f"{phone}/recordings/start",
        {"sensorSet": sensor_set, "targetHz": target_hz},
        timeout=10,
    )
    t0 = time.monotonic()
    time.sleep(trial.pre_idle)

    commands = []
    current = BASE_CENTER
    for point in trial_points(trial.distance, cycles=trial.cycles):
        command_t = time.monotonic() - t0
        tinyg.move(*point)
        move_time = estimate_move_time(current, point, trial.params["xvm"])
        commands.append(
            {
                "t": command_t,
                "from": [current[0], current[1]],
                "to": [point[0], point[1]],
                "estimated_move_time": move_time,
            }
        )
        current = point
        time.sleep(move_time + trial.rest)

    time.sleep(trial.post_idle)
    stop_t = time.monotonic() - t0
    stop = post_json(f"{phone}/recordings/stop", timeout=10)
    payload = get_json(f"{phone}/recordings/latest", timeout=30)

    timeline = {
        "start_response": start,
        "stop_response": stop,
        "stop_t": stop_t,
        "commands": commands,
    }
    metrics = analyze(payload, trial, timeline)
    record = {
        "trial": dataclasses.asdict(trial),
        "timeline": timeline,
        "metrics": metrics,
        "payload": payload,
    }
    output_path = out_dir / f"{trial.name}.json"
    output_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(
        "  "
        f"score={metrics.get('score', float('nan')):.2f} "
        f"settle_rms={metrics.get('settle_hf_rms_g', 0):.5f}g "
        f"settle_peak={metrics.get('settle_hf_peak_g', 0):.5f}g "
        f"settle={metrics.get('settle_time_s', 0):.3f}s "
        f"peak={metrics.get('peak_user_accel_g', 0):.4f}g "
        f"hz={metrics.get('sample_rate_hz', 0):.1f}",
        flush=True,
    )
    return record


def query_original_params(tinyg):
    params = {}
    for key in ("xjm", "yjm", "xvm", "yvm", "1mi", "2mi", "3mi"):
        try:
            params[key] = tinyg.query_value(key)
        except Exception as error:
            params[key] = {"error": str(error)}
    return params


def adaptive_trials():
    baseline = dict(RECOMMENDED_PARAMS)
    legacy = dict(LEGACY_PARAMS)
    trials = [
        Trial("smoke_recommended_d2", baseline, distance=2.0, rest=0.45),
        Trial("recommended_d5", baseline, distance=5.0, rest=0.45),
        Trial("legacy_d5", legacy, distance=5.0, rest=0.45),
        Trial("jerk2250_d5", {**baseline, "xjm": 2250.0, "yjm": 2250.0}, distance=5.0, rest=0.45),
        Trial("jerk2000_d5", {**baseline, "xjm": 2000.0, "yjm": 2000.0}, distance=5.0, rest=0.45),
        Trial("jerk2750_d5", {**baseline, "xjm": 2750.0, "yjm": 2750.0}, distance=5.0, rest=0.45),
        Trial("jerk1750_d5", {**baseline, "xjm": 1750.0, "yjm": 1750.0}, distance=5.0, rest=0.50),
        Trial("jerk3000_d5", {**baseline, "xjm": 3000.0, "yjm": 3000.0}, distance=5.0, rest=0.45),
        Trial("jerk1500_d5", {**baseline, "xjm": 1500.0, "yjm": 1500.0}, distance=5.0, rest=0.55),
        Trial("jerk2000_vel2800_d10", {"xjm": 2000.0, "yjm": 2000.0, "xvm": 2800.0, "yvm": 2800.0}, distance=10.0, rest=0.50),
        Trial("jerk2000_vel3000_d10", {"xjm": 2000.0, "yjm": 2000.0, "xvm": 3000.0, "yvm": 3000.0}, distance=10.0, rest=0.50),
        Trial("jerk2000_vel3100_d10", {"xjm": 2000.0, "yjm": 2000.0, "xvm": 3100.0, "yvm": 3100.0}, distance=10.0, rest=0.50),
        Trial("jerk2250_vel3000_d10", {"xjm": 2250.0, "yjm": 2250.0, "xvm": 3000.0, "yvm": 3000.0}, distance=10.0, rest=0.50),
        Trial("jerk2000_vel3000_d20", {"xjm": 2000.0, "yjm": 2000.0, "xvm": 3000.0, "yvm": 3000.0}, distance=20.0, rest=0.65),
        Trial("jerk2250_vel3000_d20", {"xjm": 2250.0, "yjm": 2250.0, "xvm": 3000.0, "yvm": 3000.0}, distance=20.0, rest=0.65),
        Trial("recommended_d20", baseline, distance=20.0, rest=0.65),
        Trial("legacy_d20", legacy, distance=20.0, rest=0.65),
    ]
    return trials


def smoke_trials():
    return [Trial("smoke_recommended_d2", dict(RECOMMENDED_PARAMS), distance=2.0, rest=0.45)]


def confirm_trials():
    return [
        Trial("confirm_recommended_d20", dict(RECOMMENDED_PARAMS), distance=20.0, rest=0.65),
        Trial("confirm_legacy_d20", dict(LEGACY_PARAMS), distance=20.0, rest=0.65),
        Trial("confirm_j2000_v3000_d20", {"xjm": 2000.0, "yjm": 2000.0, "xvm": 3000.0, "yvm": 3000.0}, distance=20.0, rest=0.65),
        Trial("confirm_x1750_y2000_v3000_d20", {"xjm": 1750.0, "yjm": 2000.0, "xvm": 3000.0, "yvm": 3000.0}, distance=20.0, rest=0.65),
        Trial("confirm_x1750_y2250_v3000_d20", {"xjm": 1750.0, "yjm": 2250.0, "xvm": 3000.0, "yvm": 3000.0}, distance=20.0, rest=0.65),
        Trial("confirm_x1500_y2000_v3000_d20", {"xjm": 1500.0, "yjm": 2000.0, "xvm": 3000.0, "yvm": 3000.0}, distance=20.0, rest=0.65),
        Trial("confirm_j2000_v2900_d20", {"xjm": 2000.0, "yjm": 2000.0, "xvm": 2900.0, "yvm": 2900.0}, distance=20.0, rest=0.65),
        Trial("confirm_x1750_y2000_xv2900_yv3000_d20", {"xjm": 1750.0, "yjm": 2000.0, "xvm": 2900.0, "yvm": 3000.0}, distance=20.0, rest=0.65),
        Trial("confirm_j2000_v3000_d25", {"xjm": 2000.0, "yjm": 2000.0, "xvm": 3000.0, "yvm": 3000.0}, distance=25.0, rest=0.75),
        Trial("confirm_x1750_y2000_v3000_d25", {"xjm": 1750.0, "yjm": 2000.0, "xvm": 3000.0, "yvm": 3000.0}, distance=25.0, rest=0.75),
    ]


def final_trials():
    return [
        Trial("final_recommended_d25", dict(RECOMMENDED_PARAMS), distance=25.0, rest=0.75),
        Trial("final_legacy_d25", dict(LEGACY_PARAMS), distance=25.0, rest=0.75),
        Trial("final_j2000_v3000_d25", {"xjm": 2000.0, "yjm": 2000.0, "xvm": 3000.0, "yvm": 3000.0}, distance=25.0, rest=0.75),
        Trial("final_x1500_y2000_v3000_d25", {"xjm": 1500.0, "yjm": 2000.0, "xvm": 3000.0, "yvm": 3000.0}, distance=25.0, rest=0.75),
        Trial("final_x1750_y2000_v3000_d25", {"xjm": 1750.0, "yjm": 2000.0, "xvm": 3000.0, "yvm": 3000.0}, distance=25.0, rest=0.75),
        Trial("final_j1750_v3000_d25", {"xjm": 1750.0, "yjm": 1750.0, "xvm": 3000.0, "yvm": 3000.0}, distance=25.0, rest=0.75),
    ]


def main():
    parser = argparse.ArgumentParser(description="Run TinyG motion trials while recording iPhone motion data.")
    parser.add_argument("--phone", default=DEFAULT_PHONE)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--out", default=None)
    parser.add_argument("--plan", choices=["smoke", "adaptive", "confirm", "final"], default="smoke")
    parser.add_argument("--sensor-set", default="both", choices=["both", "accelerometer", "deviceMotion"])
    parser.add_argument("--target-hz", type=float, default=100.0)
    parser.add_argument("--restore-original", action="store_true")
    args = parser.parse_args()

    phone = normalize_phone_url(args.phone)
    out_dir = Path(args.out or f"tinyg/motion_trials/{time.strftime('%Y%m%d-%H%M%S')}")
    out_dir.mkdir(parents=True, exist_ok=True)

    state = get_json(f"{phone}/state", timeout=10)
    if state["recorder"]["isRecording"]:
        post_json(f"{phone}/recordings/stop", timeout=5)

    tinyg = TinyG(args.port)
    records = []
    original = {}
    try:
        tinyg.drain()
        original = query_original_params(tinyg)
        print(f"original TinyG params: {original}", flush=True)
        (out_dir / "original_params.json").write_text(json.dumps(original, indent=2), encoding="utf-8")

        if args.plan == "smoke":
            trials = smoke_trials()
        elif args.plan == "adaptive":
            trials = adaptive_trials()
        elif args.plan == "confirm":
            trials = confirm_trials()
        else:
            trials = final_trials()
        for trial in trials:
            records.append(run_trial(tinyg, phone, trial, out_dir, args.sensor_set, args.target_hz))

        summary = [
            {
                "name": record["trial"]["name"],
                "params": record["trial"]["params"],
                "distance": record["trial"]["distance"],
                **record["metrics"],
            }
            for record in records
        ]
        summary.sort(key=lambda item: item.get("score", float("inf")))
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("\nranked summary:", flush=True)
        for item in summary:
            print(
                f"  {item['name']:24s} score={item['score']:.2f} "
                f"settle_rms={item['settle_hf_rms_g']:.5f}g "
                f"settle_peak={item['settle_hf_peak_g']:.5f}g "
                f"settle={item['settle_time_s']:.3f}s "
                f"peak={item['peak_user_accel_g']:.4f}g",
                flush=True,
            )
        print(f"\nwrote {out_dir}", flush=True)
    finally:
        if args.restore_original and original:
            restore = {key: original[key] for key in ("xjm", "yjm", "xvm", "yvm") if isinstance(original.get(key), (int, float))}
            if restore:
                print(f"restoring TinyG params: {restore}", flush=True)
                apply_params(tinyg, restore)
        tinyg.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
