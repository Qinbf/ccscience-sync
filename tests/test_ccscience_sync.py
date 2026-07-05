import pathlib
import tempfile
import unittest

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
