import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import requests

import runpod_manager as module


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class RunpodManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temporary.name)
        self.manager = module.RunpodManager(state_dir=self.state_dir, autostart=False)

    def tearDown(self):
        self.temporary.cleanup()

    def set_stock(self):
        self.manager.gpu_options = [
            {
                "id": "NVIDIA H100 80GB HBM3",
                "name": "H100 SXM",
                "memory_gb": 80,
                "secure_price_per_hour": 3.29,
                "stock_status": "Low",
                "data_center_availability": {"US-CA-2": "Low", "US-GA-2": "Low"},
            },
            {
                "id": "NVIDIA H200",
                "name": "H200 SXM",
                "memory_gb": 141,
                "secure_price_per_hour": 4.59,
                "stock_status": "Low",
                "data_center_availability": {"US-CA-2": "Low", "US-GA-2": "Low"},
            },
        ]
        self.manager.data_center_options = [
            {"id": "US-CA-2", "name": "US-CA-2", "location": "United States"},
            {"id": "US-GA-2", "name": "US-GA-2", "location": "United States"},
        ]
        self.manager.config["allowed_gpu_ids"] = ["NVIDIA H100 80GB HBM3", "NVIDIA H200"]
        self.manager.config["deployment_region"] = "north-america"
        self.manager.config["priority_data_center_id"] = "US-CA-2"

    def test_autostart_marks_manager_starting_on_boot(self):
        with tempfile.TemporaryDirectory() as state_dir:
            manager = module.RunpodManager(state_dir=state_dir, autostart=True)
        self.assertTrue(manager.state["desired_running"])
        self.assertEqual(manager.state["status"], "starting")
        self.assertEqual(manager.state["phase"], "boot")

    def test_create_prefers_us_ca_2_and_first_allowed_card(self):
        self.set_stock()
        self.manager.state["desired_running"] = True
        self.manager._refresh_options = mock.Mock()
        calls = []

        def run_cli(*args, **kwargs):
            calls.append(args)
            if args[:2] == ("pod", "list"):
                return []
            if args[:2] == ("pod", "create"):
                return {"id": "pod123"}
            raise AssertionError(args)

        self.manager._run_cli = run_cli
        self.manager.reconcile()

        create = next(call for call in calls if call[:2] == ("pod", "create"))
        self.assertEqual(create[create.index("--data-center-ids") + 1], "US-CA-2")
        self.assertEqual(create[create.index("--gpu-id") + 1], "NVIDIA H100 80GB HBM3")
        self.assertEqual(self.manager.state["pod_id"], "pod123")
        self.assertEqual(
            self.manager.state["endpoint"],
            "https://pod123-8787.proxy.runpod.net/api/process",
        )

    def test_create_uses_selected_priority_data_center_first(self):
        self.set_stock()
        self.manager.config["priority_data_center_id"] = "US-GA-2"
        self.assertEqual(
            self.manager._candidate_pairs()[:2],
            [
                ("NVIDIA H100 80GB HBM3", "US-GA-2"),
                ("NVIDIA H200", "US-GA-2"),
            ],
        )

    def test_options_refresh_runs_during_first_five_minutes_of_boot(self):
        self.manager.last_options_refresh = 0
        self.manager._run_cli = mock.Mock(side_effect=(
            [{
                "gpuId": "NVIDIA H100 80GB HBM3",
                "displayName": "H100 SXM",
                "memoryInGb": 80,
                "securePricePerHr": 3.29,
                "available": True,
                "stockStatus": "Low",
                "dataCenterAvailability": [{"dataCenterId": "US-CA-2", "stockStatus": "Low"}],
            }],
            [{"id": "US-CA-2", "name": "US-CA-2", "location": "United States"}],
        ))
        with mock.patch.object(module.time, "monotonic", return_value=10):
            self.manager._refresh_options()
        self.assertEqual(self.manager._run_cli.call_count, 2)
        self.assertEqual(
            self.manager.gpu_options[0]["data_center_availability"],
            {"US-CA-2": "Low"},
        )

    def test_no_selected_capacity_reports_blocked_without_create_call(self):
        self.manager.state["desired_running"] = True
        self.manager.gpu_options = [{
            "id": "NVIDIA H100 80GB HBM3",
            "name": "H100 SXM",
            "data_center_availability": {"US-CA-2": "none"},
        }]
        self.manager.config["allowed_gpu_ids"] = ["NVIDIA H100 80GB HBM3"]
        self.manager.config["deployment_region"] = "north-america"
        self.manager.config["priority_data_center_id"] = "US-CA-2"
        self.manager._refresh_options = mock.Mock()
        self.manager._run_cli = mock.Mock(return_value=[])
        self.manager.reconcile()
        self.assertEqual(self.manager.state["status"], "blocked")
        self.assertIn("currently has stock", self.manager.state["message"])
        self.assertFalse(any(call.args[:2] == ("pod", "create") for call in self.manager._run_cli.call_args_list))

    def test_running_requires_model_readiness(self):
        self.manager.state.update({
            "pod_id": "pod123",
            "server_url": "https://pod123-8787.proxy.runpod.net",
            "endpoint": "https://pod123-8787.proxy.runpod.net/api/process",
            "desired_running": True,
            "status": "starting",
            "startup_started_at": "2026-08-19T10:00:00Z",
        })
        self.manager._refresh_options = mock.Mock()
        self.manager._run_cli = mock.Mock(return_value={
            "id": "pod123",
            "desiredStatus": "RUNNING",
            "runtimeStatus": "running",
        })

        with mock.patch.object(
            module.requests,
            "get",
            return_value=FakeResponse({"ok": True, "model_loaded": False, "preload": {"state": "loading"}}),
        ):
            self.manager.reconcile()
        self.assertEqual(self.manager.state["status"], "starting")
        self.assertEqual(self.manager.state["phase"], "model_loading")

        with mock.patch.object(
            module.requests,
            "get",
            return_value=FakeResponse({"ok": True, "model_loaded": True, "preload": {"state": "loaded"}}),
        ), mock.patch.object(module, "utc_now", return_value="2026-08-19T10:02:16Z"):
            self.manager.reconcile()
        self.assertEqual(self.manager.state["status"], "running")
        self.assertEqual(self.manager.state["phase"], "ready")
        self.assertEqual(self.manager.state["startup_duration_seconds"], 136.0)

    def test_manual_stop_waits_for_provider_stopped_status(self):
        self.manager.state.update({"pod_id": "pod123", "desired_running": True, "status": "running"})
        self.manager._refresh_options = mock.Mock()
        pod_statuses = iter((
            {"id": "pod123", "runtimeStatus": "running"},
            {"id": "pod123", "runtimeStatus": "stopped"},
        ))
        calls = []

        def run_cli(*args, **kwargs):
            calls.append(args)
            if args[:2] == ("pod", "get"):
                return next(pod_statuses)
            if args[:2] == ("pod", "stop"):
                return {}
            raise AssertionError(args)

        self.manager._run_cli = run_cli
        self.manager.request_stop()
        self.manager.reconcile()
        self.assertEqual(self.manager.state["status"], "stopping")
        self.assertTrue(any(call[:2] == ("pod", "stop") for call in calls))
        self.manager.reconcile()
        self.assertEqual(self.manager.state["status"], "stopped")
        self.assertIsNotNone(self.manager.state["stopped_at"])

    def test_repeated_stop_refreshes_timestamp_after_a_new_run(self):
        self.manager.state.update({
            "pod_id": "pod123",
            "desired_running": False,
            "status": "stopping",
            "stopped_at": "2020-01-01T00:00:00Z",
        })
        self.manager._refresh_options = mock.Mock()
        self.manager._run_cli = mock.Mock(return_value={"id": "pod123", "runtimeStatus": "stopped"})
        self.manager.reconcile()
        self.assertNotEqual(self.manager.state["stopped_at"], "2020-01-01T00:00:00Z")

    def test_disallowed_stopped_pod_is_deleted_before_replacement(self):
        self.set_stock()
        self.manager.config["allowed_gpu_ids"] = ["NVIDIA H200"]
        self.manager.state.update({
            "pod_id": "oldpod",
            "gpu_id": "NVIDIA H100 80GB HBM3",
            "data_center_id": "US-CA-2",
            "desired_running": True,
            "status": "stopped",
        })
        self.manager._refresh_options = mock.Mock()
        calls = []

        def run_cli(*args, **kwargs):
            calls.append(args)
            if args[:2] == ("pod", "get"):
                return {"id": "oldpod", "runtimeStatus": "stopped"}
            if args[:2] == ("pod", "delete"):
                return {}
            raise AssertionError(args)

        self.manager._run_cli = run_cli
        self.manager.reconcile()
        self.assertTrue(any(call[:2] == ("pod", "delete") for call in calls))
        self.assertIsNone(self.manager.state["pod_id"])

    def test_config_requires_a_card_and_valid_region_selections(self):
        with self.assertRaisesRegex(ValueError, "at least one GPU"):
            self.manager.update_config({
                "allowed_gpu_ids": [],
                "deployment_region": "north-america",
                "priority_data_center_id": "US-CA-2",
            })
        with self.assertRaisesRegex(ValueError, "supported deployment region"):
            self.manager.update_config({
                "allowed_gpu_ids": ["NVIDIA H100 80GB HBM3"],
                "deployment_region": "europe",
                "priority_data_center_id": "US-CA-2",
            })
        with self.assertRaisesRegex(ValueError, "priority data center"):
            self.manager.update_config({
                "allowed_gpu_ids": ["NVIDIA H100 80GB HBM3"],
                "deployment_region": "north-america",
                "priority_data_center_id": "EU-RO-1",
            })

    def test_config_saves_priority_and_derives_deployment_data_centers(self):
        self.set_stock()
        status = self.manager.update_config({
            "allowed_gpu_ids": ["NVIDIA H200"],
            "deployment_region": "north-america",
            "priority_data_center_id": "US-GA-2",
        })
        self.assertEqual(status["config"]["priority_data_center_id"], "US-GA-2")
        self.assertEqual(
            status["config"]["allowed_data_center_ids"],
            ["US-CA-2", "US-GA-2"],
        )

    def test_old_region_config_migrates_to_priority_selector(self):
        with tempfile.TemporaryDirectory() as state_dir:
            state_path = Path(state_dir)
            module.atomic_write_json(state_path / "config.json", {
                "allowed_gpu_ids": ["NVIDIA H100 80GB HBM3"],
                "allowed_data_center_ids": ["US-GA-2"],
            })
            manager = module.RunpodManager(state_dir=state_dir, autostart=False)
        self.assertEqual(manager.config["deployment_region"], "north-america")
        self.assertEqual(manager.config["priority_data_center_id"], "US-GA-2")

    def test_public_status_reports_live_startup_elapsed_time(self):
        self.manager.state.update({
            "desired_running": True,
            "status": "starting",
            "startup_started_at": "2026-08-19T10:00:00Z",
            "startup_duration_seconds": None,
        })
        with mock.patch.object(module, "utc_now", return_value="2026-08-19T10:00:42Z"):
            status = self.manager.public_status()
        self.assertEqual(status["startup_elapsed_seconds"], 42.0)

    def test_shutdown_fallback_targets_only_saved_pod(self):
        module.atomic_write_json(self.state_dir / "state.json", {"pod_id": "managed123"})
        completed = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        with mock.patch.object(module.requests, "post", side_effect=requests.ConnectionError("down")), mock.patch.object(
            module.subprocess, "run", return_value=completed
        ) as run:
            result = module.shutdown_managed_pod(
                self.state_dir,
                "http://127.0.0.1:8082",
                5,
            )
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.args[0][1:4], ["pod", "stop", "managed123"])

    def test_state_files_never_store_cli_credentials(self):
        self.manager._update_state(message="ready")
        state_text = (self.state_dir / "state.json").read_text()
        config_text = (self.state_dir / "config.json").read_text()
        self.assertNotIn("api_key", state_text.lower())
        self.assertNotIn("api_key", config_text.lower())
        json.loads(state_text)
        json.loads(config_text)


if __name__ == "__main__":
    unittest.main()
