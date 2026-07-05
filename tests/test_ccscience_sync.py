import pathlib
import tempfile
import unittest
from unittest import mock

import ccscience_sync


class ModelMappingTests(unittest.TestCase):
    def test_maps_common_models(self):
        self.assertEqual(ccscience_sync.map_model("opus[1m]", {}), "claude-opus-4-8")
        self.assertEqual(ccscience_sync.map_model("sonnet", {}), "claude-sonnet-5")
        self.assertEqual(ccscience_sync.map_model("sonnet-4.6", {}), "claude-sonnet-4-6")
        self.assertEqual(ccscience_sync.map_model("haiku", {}), "claude-haiku-4-5")

    def test_respects_model_map_override(self):
        config = {"model_map": {"opus[1m]": "custom-opus"}}
        self.assertEqual(ccscience_sync.map_model("opus[1m]", config), "custom-opus")

    def test_maps_effort(self):
        self.assertEqual(ccscience_sync.map_effort("max"), "high")
        self.assertEqual(ccscience_sync.map_effort("med"), "medium")
        self.assertIsNone(ccscience_sync.map_effort("unknown"))


class LocalizationTests(unittest.TestCase):
    def test_detects_chinese_locales(self):
        self.assertEqual(ccscience_sync.detect_language("zh_CN.UTF-8"), "zh")
        self.assertEqual(ccscience_sync.detect_language("zh-Hans-CN"), "zh")
        self.assertEqual(ccscience_sync.detect_language("zh_TW"), "zh")

    def test_defaults_non_chinese_to_english(self):
        self.assertEqual(ccscience_sync.detect_language("en_US.UTF-8"), "en")
        self.assertEqual(ccscience_sync.detect_language("ja_JP.UTF-8"), "en")

    def test_localizes_gui_status_output(self):
        text = "helper: running (claude-opus-4-8)\nruntime patch: installed (/tmp/index.html)"
        localized = ccscience_sync.localize_cli_output(text, "zh")
        self.assertIn("后台服务：运行中", localized)
        self.assertIn("运行时补丁：已安装", localized)


class ClaudeScienceUrlTests(unittest.TestCase):
    def test_parses_fresh_url_from_cli_output(self):
        completed = ccscience_sync.subprocess.CompletedProcess(
            ["claude-science", "url"],
            0,
            "http://localhost:8765/?nonce=abc123\n(single-use, expires in 3 min)\n",
            "",
        )
        with mock.patch.object(
            ccscience_sync,
            "claude_science_commands",
            return_value=[pathlib.Path("/tmp/claude-science")],
        ):
            with mock.patch.object(ccscience_sync, "run", return_value=completed):
                self.assertEqual(ccscience_sync.fresh_claude_science_url(), "http://localhost:8765/?nonce=abc123")

    def test_reports_when_cli_has_no_url(self):
        completed = ccscience_sync.subprocess.CompletedProcess(
            ["claude-science", "url"],
            1,
            "",
            "not running",
        )
        with mock.patch.object(
            ccscience_sync,
            "claude_science_commands",
            return_value=[pathlib.Path("/tmp/claude-science")],
        ):
            with mock.patch.object(ccscience_sync, "run", return_value=completed):
                with self.assertRaises(SystemExit) as raised:
                    ccscience_sync.fresh_claude_science_url("zh")
        self.assertEqual(str(raised.exception), ccscience_sync.tr("zh", "science_url_missing"))


class CSSwitchBridgeTests(unittest.TestCase):
    def write_csswitch_config(self, root: pathlib.Path, model: str = "glm-5.2") -> None:
        path = root / ".csswitch" / "config.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            ccscience_sync.json.dumps(
                {
                    "schema_version": 2,
                    "mode": "proxy",
                    "active_id": "p1",
                    "proxy_port": 18991,
                    "secret": "secret123",
                    "profiles": [
                        {
                            "id": "p1",
                            "name": "GLM",
                            "template_id": "glm",
                            "model": model,
                            "api_key": "hidden",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_prefers_csswitch_active_profile_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text('{"model":"opus[1m]"}', encoding="utf-8")
            self.write_csswitch_config(root)

            with mock.patch.object(ccscience_sync, "home", return_value=root):
                payload = ccscience_sync.current_model_payload()

        self.assertEqual(payload["source"], "csswitch-profile")
        self.assertEqual(payload["source_model"], "glm-5.2")
        self.assertEqual(payload["model"], "glm-5.2")

    def test_launch_environment_uses_running_csswitch_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_csswitch_config(root)
            with mock.patch.object(ccscience_sync, "home", return_value=root), mock.patch.object(
                ccscience_sync, "csswitch_proxy_health", return_value=True
            ):
                env, bridge = ccscience_sync.science_launch_environment()

        self.assertTrue(bridge["proxy_running"])
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:18991/secret123")

    def test_launch_environment_skips_stopped_csswitch_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_csswitch_config(root)
            with mock.patch.object(ccscience_sync, "home", return_value=root), mock.patch.object(
                ccscience_sync, "csswitch_proxy_health", return_value=False
            ):
                env, bridge = ccscience_sync.science_launch_environment()

        self.assertIsNone(env)
        self.assertFalse(bridge["proxy_running"])


class RuntimePatchTests(unittest.TestCase):
    def test_patch_and_unpatch_index(self):
        html = (
            "<html><head></head><body>\n"
            '  <script type="module" src="/assets/index-test.js"></script>\n'
            "</body></html>\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "index.html"
            path.write_text(html, encoding="utf-8")

            self.assertEqual(ccscience_sync.patch_index(path, 19783), "installed")
            patched = path.read_text(encoding="utf-8")
            self.assertIn(ccscience_sync.MARKER_START, patched)
            self.assertIn("http://127.0.0.1:19783/model", patched)

            self.assertEqual(ccscience_sync.unpatch_index(path), "removed")
            self.assertNotIn(ccscience_sync.MARKER_START, path.read_text(encoding="utf-8"))

    def test_injection_refreshes_before_request(self):
        script = ccscience_sync.injection_script(19783)
        self.assertIn("originalFetch.call(window, endpoint", script)
        self.assertIn("patchRequest(input, init)", script)
        self.assertIn('window.addEventListener("focus", scheduleSync)', script)
        self.assertNotIn("setInterval(syncAsync, 5000)", script)


if __name__ == "__main__":
    unittest.main()
