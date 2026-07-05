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
