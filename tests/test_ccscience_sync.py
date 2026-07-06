import json
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

    def test_ccswitch_model_drives_injection_csswitch_only_routes(self):
        # With a Claude Code model selected, ccswitch is the source of truth: the
        # injected model is the mapped Claude Science id, not the raw provider name.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text('{"model":"opus[1m]"}', encoding="utf-8")
            self.write_csswitch_config(root)

            with mock.patch.object(ccscience_sync, "home", return_value=root):
                payload = ccscience_sync.current_model_payload()

        self.assertEqual(payload["source"], "claude-settings")
        self.assertEqual(payload["model"], "claude-opus-4-8")
        # CSSwitch info is still exposed for routing/status
        self.assertTrue(payload["csswitch"]["enabled"])
        self.assertEqual(payload["csswitch"]["model"], "glm-5.2")

    def test_falls_back_to_csswitch_model_when_no_claude_code_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_csswitch_config(root)  # no ~/.claude/settings.json
            with mock.patch.object(ccscience_sync, "home", return_value=root):
                payload = ccscience_sync.current_model_payload()
        self.assertEqual(payload["source"], "csswitch-profile")
        self.assertEqual(payload["model"], "glm-5.2")

    def test_ccswitch_direct_env_overrides_csswitch_routing(self):
        # ccswitch writes a self-contained provider entry (MiniMax etc.) into
        # settings.json.env. We must surface it as "direct" and reveal the real
        # upstream model, not silently fall back to the CSSwitch profile.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(json.dumps({
                "model": "opus",
                "env": {
                    "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "sk-cp-test",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M3[1M]",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME": "MiniMax-M3",
                },
            }), encoding="utf-8")
            self.write_csswitch_config(root)  # CSSwitch still claims enabled
            with mock.patch.object(ccscience_sync, "home", return_value=root):
                payload = ccscience_sync.current_model_payload()
        self.assertEqual(payload["upstream_mode"], "direct")
        self.assertEqual(payload["upstream_base_url"], "https://api.minimaxi.com/anthropic")
        self.assertEqual(payload["upstream_key_env"], "ANTHROPIC_AUTH_TOKEN")
        self.assertEqual(payload["upstream_provider_model"], "MiniMax-M3")
        self.assertEqual(payload["model"], "claude-opus-4-8")  # injected tier id, Science-valid

    def test_science_launch_environment_prefers_ccswitch_direct_env(self):
        # Even when CSSwitch proxy is up, ccswitch's env wins.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(json.dumps({
                "env": {
                    "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "sk-cp-test",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M3",
                },
            }), encoding="utf-8")
            self.write_csswitch_config(root)
            with mock.patch.object(ccscience_sync, "home", return_value=root), mock.patch.object(
                ccscience_sync, "csswitch_proxy_health", return_value=True
            ):
                env, bridge = ccscience_sync.science_launch_environment()
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.minimaxi.com/anthropic")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-cp-test")
        self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "MiniMax-M3")

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


class CryptoTests(unittest.TestCase):
    def test_aes256_gcm_nist_vectors(self):
        # NIST GCM test case 13: all-zero 256-bit key/IV, empty plaintext/AAD
        _, tag = ccscience_sync.aes_gcm_encrypt(bytes(32), bytes(12), b"", b"")
        self.assertEqual(tag.hex(), "530f8afbc74536b9a963b4f1c4cb738b")
        # NIST GCM test case 14: one zero block of plaintext
        ct, tag = ccscience_sync.aes_gcm_encrypt(bytes(32), bytes(12), bytes(16), b"")
        self.assertEqual(ct.hex(), "cea7403d4d606b6e074ec5d3baf39d18")
        self.assertEqual(tag.hex(), "d0d1c8a799996bf0265b98b5d48ab919")

    def test_hkdf_sha256_rfc5869_vector(self):
        # RFC 5869 test case 1
        ikm = bytes.fromhex("0b" * 22)
        salt = bytes.fromhex("000102030405060708090a0b0c")
        info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
        okm = ccscience_sync.hkdf_sha256(ikm, salt, info, 42)
        self.assertEqual(
            okm.hex(),
            "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865",
        )

    def test_gcm_decrypt_roundtrip_and_tamper(self):
        key = bytes(range(32))
        iv = bytes(range(12))
        pt = b"the quick brown fox jumps"
        ct, tag = ccscience_sync.aes_gcm_encrypt(key, iv, pt, b"v2:oauth")
        self.assertEqual(ccscience_sync.aes_gcm_decrypt(key, iv, ct, tag, b"v2:oauth"), pt)
        with self.assertRaises(ValueError):
            ccscience_sync.aes_gcm_decrypt(key, iv, ct, tag, b"wrong-aad")
        bad = bytearray(ct)
        bad[0] ^= 1
        with self.assertRaises(ValueError):
            ccscience_sync.aes_gcm_decrypt(key, iv, bytes(bad), tag, b"v2:oauth")

    def test_token_v2_roundtrip(self):
        key_b64 = ccscience_sync.base64.b64encode(bytes(range(32))).decode()
        body = ccscience_sync.encrypt_token_v2('{"email":"virtual@localhost.invalid"}', key_b64)
        self.assertTrue(body.startswith("v2:"))
        self.assertEqual(
            ccscience_sync.json.loads(ccscience_sync.decrypt_token_v2(body, key_b64))["email"],
            "virtual@localhost.invalid",
        )


class VirtualOAuthForgeTests(unittest.TestCase):
    def _sandbox(self, tmp: str) -> pathlib.Path:
        auth = pathlib.Path(tmp) / ".sandbox" / "home" / ".claude-science"
        auth.parent.mkdir(parents=True)
        return auth

    def test_forge_writes_valid_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = self._sandbox(tmp)
            info = ccscience_sync.forge_virtual_oauth(auth)
            self.assertEqual(info["email"], ccscience_sync.VIRTUAL_EMAIL)
            self.assertTrue((auth / "encryption.key").is_file())
            self.assertTrue((auth / "active-org.json").is_file())
            encs = list((auth / ".oauth-tokens").glob("*.enc"))
            self.assertEqual(len(encs), 1)
            self.assertTrue(ccscience_sync.sandbox_has_valid_token(auth))
            org = ccscience_sync.json.loads((auth / "active-org.json").read_text())
            self.assertEqual(org["org_uuid"], info["org_uuid"])

    def test_forge_keeps_single_enc_and_reuses_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = self._sandbox(tmp)
            first = ccscience_sync.forge_virtual_oauth(auth)
            key1 = (auth / "encryption.key").read_text()
            second = ccscience_sync.forge_virtual_oauth(auth)
            key2 = (auth / "encryption.key").read_text()
            self.assertEqual(key1, key2)  # encryption.key reused so old .enc stays decryptable
            self.assertEqual(len(list((auth / ".oauth-tokens").glob("*.enc"))), 1)
            self.assertNotEqual(first["account_uuid"], second["account_uuid"])

    def test_forge_embeds_real_access_token_for_direct_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = self._sandbox(tmp)
            ccscience_sync.forge_virtual_oauth(auth, access_token="sk-real-provider-key", force=True)
            keys = ccscience_sync._parse_key_file((auth / "encryption.key").read_text())
            enc = next(iter((auth / ".oauth-tokens").glob("*.enc"))).read_text()
            blob = json.loads(ccscience_sync.decrypt_token_v2(enc, keys["OAUTH_ENCRYPTION_KEY"]))
            # The real provider key rides as the OAuth access_token so Claude
            # Science sends it straight to the provider (no proxy in the path).
            self.assertEqual(blob["access_token"], "sk-real-provider-key")

    def test_forge_without_token_uses_throwaway_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = self._sandbox(tmp)
            ccscience_sync.forge_virtual_oauth(auth)
            keys = ccscience_sync._parse_key_file((auth / "encryption.key").read_text())
            enc = next(iter((auth / ".oauth-tokens").glob("*.enc"))).read_text()
            blob = json.loads(ccscience_sync.decrypt_token_v2(enc, keys["OAUTH_ENCRYPTION_KEY"]))
            self.assertTrue(blob["access_token"].startswith("sk-ant-virtual-"))

    def test_refuses_real_credential_dir(self):
        with self.assertRaises(SystemExit):
            ccscience_sync.forge_virtual_oauth(ccscience_sync.home() / ".claude-science")

    def test_refuses_non_virtual_email(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                ccscience_sync.forge_virtual_oauth(self._sandbox(tmp), email="me@gmail.com")

    def test_refuses_path_outside_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = pathlib.Path(tmp) / "plain" / ".claude-science"
            auth.parent.mkdir(parents=True)
            with self.assertRaises(SystemExit):
                ccscience_sync.forge_virtual_oauth(auth)

    def test_guardrail_rejects_real_port(self):
        with self.assertRaises(SystemExit):
            ccscience_sync._assert_sandbox_guardrails(ccscience_sync.REAL_SCIENCE_PORT)


class SandboxLaunchEnvTests(unittest.TestCase):
    def test_launch_env_proxy_mode_routes_and_fastfails_anthropic(self):
        with mock.patch.object(ccscience_sync, "home", return_value=pathlib.Path(tempfile.gettempdir())):
            env = ccscience_sync.sandbox_launch_env(
                {"mode": "csswitch-proxy", "base_url": "http://127.0.0.1:18991/secret123"})
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:18991/secret123")
        self.assertEqual(env["https_proxy"], "http://127.0.0.1:18991")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:18991")
        self.assertIn("127.0.0.1", env["no_proxy"])
        self.assertIn(".sandbox", env["HOME"])

    def test_launch_env_direct_mode_routes_to_provider_and_fastfails(self):
        with mock.patch.object(ccscience_sync, "home", return_value=pathlib.Path(tempfile.gettempdir())):
            env = ccscience_sync.sandbox_launch_env(
                {"mode": "direct", "base_url": "https://api.deepseek.com/anthropic"})
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.deepseek.com/anthropic")
        # Provider host bypasses the dead proxy so inference reaches it directly.
        self.assertIn("api.deepseek.com", env["no_proxy"])
        # Anthropic HTTPS fast-fails via a dead local port — no proxy process.
        self.assertTrue(env["https_proxy"].startswith("http://127.0.0.1:"))
        self.assertNotIn("18991", env["https_proxy"])

    def test_thirdparty_target_prefers_direct_env(self):
        with mock.patch.dict(ccscience_sync.os.environ, {"CCSCIENCE_TP_BASE": "", "CCSCIENCE_TP_KEY": ""}):
            with mock.patch.object(ccscience_sync, "load_json", return_value={
                "model": "deepseek-v4-pro",
                "env": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                        "ANTHROPIC_AUTH_TOKEN": "sk-real-key"},
            }):
                target = ccscience_sync.thirdparty_target()
        self.assertEqual(target["mode"], "direct")
        # Routed through OUR forwarder; the real provider is kept in provider_base.
        self.assertEqual(target["base_url"], f"http://127.0.0.1:{ccscience_sync.THIRDPARTY_FWD_PORT}")
        self.assertEqual(target["provider_base"], "https://api.deepseek.com/anthropic")
        self.assertEqual(target["access_token"], "sk-real-key")

    def test_normalize_thinking_auto_to_adaptive(self):
        # operon sends thinking.type "auto"; DeepSeek/MiniMax only accept adaptive.
        body = ccscience_sync.normalize_thirdparty_request(
            {"thinking": {"type": "auto"}}, "api.deepseek.com")
        self.assertEqual(body["thinking"]["type"], "adaptive")

    def test_normalize_thinking_deepseek_forced_tool_disables(self):
        body = ccscience_sync.normalize_thirdparty_request(
            {"thinking": {"type": "auto"}, "tool_choice": {"type": "any"}}, "api.deepseek.com")
        self.assertEqual(body["thinking"]["type"], "disabled")

    def test_thirdparty_target_falls_back_to_running_proxy(self):
        with mock.patch.object(ccscience_sync, "load_json", return_value={"env": {}}):
            with mock.patch.object(ccscience_sync, "csswitch_proxy_url",
                                   return_value="http://127.0.0.1:18991/secret"):
                with mock.patch.object(ccscience_sync, "csswitch_bridge_payload",
                                       return_value={"enabled": True, "proxy_running": True,
                                                     "model": "deepseek-v4-pro"}):
                    target = ccscience_sync.thirdparty_target()
        self.assertEqual(target["mode"], "csswitch-proxy")
        self.assertEqual(target["base_url"], "http://127.0.0.1:18991/secret")

    def test_thirdparty_target_none_without_any_source(self):
        with mock.patch.object(ccscience_sync, "load_json", return_value={"env": {}}):
            with mock.patch.object(ccscience_sync, "csswitch_proxy_url", return_value=None):
                with mock.patch.object(ccscience_sync, "csswitch_bridge_payload",
                                       return_value={"enabled": False, "proxy_running": False}):
                    self.assertIsNone(ccscience_sync.thirdparty_target())

    def test_open_thirdparty_requires_a_source(self):
        with mock.patch.object(ccscience_sync, "thirdparty_target", return_value=None):
            with self.assertRaises(SystemExit) as raised:
                ccscience_sync.open_thirdparty("en")
        self.assertEqual(str(raised.exception), ccscience_sync.tr("en", "thirdparty_needs_source"))


class SandboxRuntimeTests(unittest.TestCase):
    def test_clone_dir_is_atomic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / "src"
            (src / "sub").mkdir(parents=True)
            (src / "sub" / "f.txt").write_text("hi", encoding="utf-8")
            dst = pathlib.Path(tmp) / "dst"
            ccscience_sync._clone_dir(src, dst)
            self.assertEqual((dst / "sub" / "f.txt").read_text(encoding="utf-8"), "hi")
            # no partial staging dir left behind
            self.assertFalse([p for p in dst.parent.iterdir() if ".partial-" in p.name])
            # second call short-circuits on existing dst without error
            ccscience_sync._clone_dir(src, dst)

    def test_launched_proxy_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ccscience_sync, "sandbox_home", return_value=pathlib.Path(tmp)):
                self.assertIsNone(ccscience_sync.launched_proxy_url())
                ccscience_sync.launched_proxy_path().write_text("http://127.0.0.1:18991/abc", encoding="utf-8")
                self.assertEqual(ccscience_sync.launched_proxy_url(), "http://127.0.0.1:18991/abc")

    def test_forge_refuses_symlink_leaf_to_real_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = pathlib.Path(tmp) / "real" / ".claude-science"
            real.mkdir(parents=True)
            sbx = pathlib.Path(tmp) / ".sandbox" / "home" / ".claude-science"
            sbx.parent.mkdir(parents=True)
            sbx.symlink_to(real)
            with mock.patch.object(ccscience_sync, "home", return_value=pathlib.Path(tmp) / "real"):
                with self.assertRaises(SystemExit):
                    ccscience_sync.forge_virtual_oauth(sbx)


if __name__ == "__main__":
    unittest.main()
