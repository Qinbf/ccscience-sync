import contextlib
import json
import http.client
import http.server
import io
import os
import pathlib
import tempfile
import threading
import urllib.request
import unittest
from unittest import mock

import ccscience


class ModelMappingTests(unittest.TestCase):
    def test_maps_common_models(self):
        self.assertEqual(ccscience.map_model("opus[1m]", {}), "claude-opus-4-8")
        self.assertEqual(ccscience.map_model("sonnet", {}), "claude-sonnet-5")
        self.assertEqual(ccscience.map_model("sonnet-4.6", {}), "claude-sonnet-4-6")
        self.assertEqual(ccscience.map_model("haiku", {}), "claude-haiku-4-5")

    def test_respects_model_map_override(self):
        config = {"model_map": {"opus[1m]": "custom-opus"}}
        self.assertEqual(ccscience.map_model("opus[1m]", config), "custom-opus")

    def test_maps_effort(self):
        self.assertEqual(ccscience.map_effort("max"), "high")
        self.assertEqual(ccscience.map_effort("med"), "medium")
        self.assertIsNone(ccscience.map_effort("unknown"))


class LocalizationTests(unittest.TestCase):
    def test_detects_chinese_locales(self):
        self.assertEqual(ccscience.detect_language("zh_CN.UTF-8"), "zh")
        self.assertEqual(ccscience.detect_language("zh-Hans-CN"), "zh")
        self.assertEqual(ccscience.detect_language("zh_TW"), "zh")

    def test_defaults_non_chinese_to_english(self):
        self.assertEqual(ccscience.detect_language("en_US.UTF-8"), "en")
        self.assertEqual(ccscience.detect_language("ja_JP.UTF-8"), "en")

    def test_localizes_gui_status_output(self):
        text = (
            "helper: running (claude-opus-4-8)\n"
            "thirdparty provider: csswitch-profile (https://api.deepseek.com/anthropic)\n"
            "thirdparty forwarder: not-running\n"
            "runtime patch: installed (/tmp/index.html)"
        )
        localized = ccscience.localize_cli_output(text, "zh")
        self.assertIn("后台服务：运行中", localized)
        self.assertIn("第三方来源：csswitch-profile", localized)
        self.assertIn("第三方转发器：未运行", localized)
        self.assertIn("运行时补丁：已安装", localized)


class ClaudeScienceUrlTests(unittest.TestCase):
    def test_parses_fresh_url_from_cli_output(self):
        completed = ccscience.subprocess.CompletedProcess(
            ["claude-science", "url"],
            0,
            "http://localhost:8765/?nonce=abc123\n(single-use, expires in 3 min)\n",
            "",
        )
        with mock.patch.object(
            ccscience,
            "claude_science_commands",
            return_value=[pathlib.Path("/tmp/claude-science")],
        ):
            with mock.patch.object(ccscience, "run", return_value=completed):
                self.assertEqual(ccscience.fresh_claude_science_url(), "http://localhost:8765/?nonce=abc123")

    def test_reports_when_cli_has_no_url(self):
        completed = ccscience.subprocess.CompletedProcess(
            ["claude-science", "url"],
            1,
            "",
            "not running",
        )
        with mock.patch.object(
            ccscience,
            "claude_science_commands",
            return_value=[pathlib.Path("/tmp/claude-science")],
        ):
            with mock.patch.object(ccscience, "run", return_value=completed):
                with self.assertRaises(SystemExit) as raised:
                    ccscience.fresh_claude_science_url("zh")
        self.assertEqual(str(raised.exception), ccscience.tr("zh", "science_url_missing"))

    def test_open_science_starts_forwarder_for_direct_provider(self):
        env = {"ANTHROPIC_BASE_URL": ccscience.thirdparty_forwarder_base_url()}
        with mock.patch.object(ccscience, "science_launch_environment",
                               return_value=(env, {"enabled": True})):
            with mock.patch.object(ccscience, "ensure_thirdparty_forwarder") as ensure:
                with mock.patch.object(ccscience, "fresh_claude_science_url",
                                       return_value="http://127.0.0.1:8990/?nonce=x"):
                    with mock.patch.object(ccscience.webbrowser, "open"):
                        url, bridge = ccscience.open_claude_science("en")
        ensure.assert_called_once_with()
        self.assertEqual(url, "http://127.0.0.1:8990/?nonce=x")
        self.assertTrue(bridge["enabled"])

    def test_cli_open_science_starts_forwarder_for_direct_provider(self):
        env = {"ANTHROPIC_BASE_URL": ccscience.thirdparty_forwarder_base_url()}
        with mock.patch.object(ccscience, "science_launch_environment",
                               return_value=(env, {"enabled": True})):
            with mock.patch.object(ccscience, "ensure_thirdparty_forwarder") as ensure:
                with mock.patch.object(ccscience, "fresh_claude_science_url",
                                       return_value="http://127.0.0.1:8990/?nonce=x"):
                    code, out = ccscience.capture_output(
                        lambda: ccscience.cmd_open_science(
                            ccscience.argparse.Namespace(print_only=True)
                        )
                    )

        self.assertEqual(code, 0)
        ensure.assert_called_once_with()
        self.assertEqual(out, "http://127.0.0.1:8990/?nonce=x")


class CSSwitchBridgeTests(unittest.TestCase):
    def write_csswitch_config(self, root: pathlib.Path, model: str = "glm-5.2",
                              name: str = "GLM", template_id: str = "glm",
                              api_key: str = "hidden") -> None:
        path = root / ".csswitch" / "config.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            ccscience.json.dumps(
                {
                    "schema_version": 2,
                    "mode": "proxy",
                    "active_id": "p1",
                    "proxy_port": 18991,
                    "secret": "secret123",
                    "profiles": [
                        {
                            "id": "p1",
                            "name": name,
                            "template_id": template_id,
                            "model": model,
                            "api_key": api_key,
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

            with mock.patch.object(ccscience, "home", return_value=root):
                payload = ccscience.current_model_payload()

        self.assertEqual(payload["source"], "claude-settings")
        self.assertEqual(payload["model"], "claude-opus-4-8")
        # CSSwitch info is still exposed for routing/status
        self.assertTrue(payload["csswitch"]["enabled"])
        self.assertEqual(payload["csswitch"]["model"], "glm-5.2")

    def test_falls_back_to_csswitch_model_when_no_claude_code_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_csswitch_config(root)  # no ~/.claude/settings.json
            with mock.patch.object(ccscience, "home", return_value=root):
                payload = ccscience.current_model_payload()
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
            self.write_csswitch_config(root, model="MiniMax-M3[1M]", name="MiniMax", template_id="minimax")
            with mock.patch.object(ccscience, "home", return_value=root):
                payload = ccscience.current_model_payload()
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
            self.write_csswitch_config(root, model="MiniMax-M3", name="MiniMax", template_id="minimax")
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.object(
                ccscience, "csswitch_proxy_health", return_value=True
            ):
                env, bridge = ccscience.science_launch_environment()
        self.assertEqual(env["ANTHROPIC_BASE_URL"], ccscience.thirdparty_forwarder_base_url())
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "ccscience-forwarder")
        self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "MiniMax-M3")

    def test_active_csswitch_profile_overrides_stale_claude_direct_env_when_key_available(self):
        # This mirrors the real-world stale state: Claude settings still point
        # at MiniMax, but CC.Switch's active profile has moved to DeepSeek. The
        # active profile must win when its key is available via the shell env.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(json.dumps({
                "model": "opus",
                "env": {
                    "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "sk-minimax-stale",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M3",
                },
            }), encoding="utf-8")
            self.write_csswitch_config(root, model="deepseek-v4-pro", name="DeepSeek", template_id="deepseek")
            settings_path = root / ".claude" / "settings.json"
            csswitch_path = root / ".csswitch" / "config.json"
            os.utime(settings_path, (1000, 1000))
            os.utime(csswitch_path, (2000, 2000))
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.dict(
                ccscience.os.environ, {"DEEPSEEK_API_KEY": "sk-deepseek-active"}
            ):
                provider = ccscience.thirdparty_provider_details()
                payload = ccscience.current_model_payload()
                env, _bridge = ccscience.science_launch_environment()
                target = ccscience.thirdparty_target()

        self.assertEqual(provider["source"], "csswitch-profile")
        self.assertEqual(provider["base_url"], "https://api.deepseek.com/anthropic")
        self.assertEqual(provider["key"], "sk-deepseek-active")
        self.assertEqual(provider["key_env"], "DEEPSEEK_API_KEY")
        self.assertEqual(provider["model"], "deepseek-v4-pro")
        self.assertEqual(payload["upstream_base_url"], "https://api.deepseek.com/anthropic")
        self.assertEqual(payload["upstream_provider_model"], "deepseek-v4-pro")
        self.assertEqual(payload["upstream_source"], "csswitch-profile")
        self.assertEqual(payload["upstream_key_env"], "DEEPSEEK_API_KEY")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], ccscience.thirdparty_forwarder_base_url())
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "ccscience-forwarder")
        self.assertEqual(env["ANTHROPIC_MODEL"], "deepseek-v4-pro")
        self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "deepseek-v4-pro")
        self.assertNotEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "MiniMax-M3")
        self.assertEqual(target["provider_base"], "https://api.deepseek.com/anthropic")
        self.assertEqual(target["model"], "deepseek-v4-pro")

    def test_newer_claude_settings_override_stale_csswitch_profile(self):
        # CC Switch's visible UI can be driven by the Claude settings it just
        # wrote, while an older ~/.csswitch/config.json still names a previous
        # provider. In that mismatch, the newer settings file is the safer source.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(json.dumps({
                "model": "opus",
                "env": {
                    "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "sk-minimax-current",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M3[1M]",
                    "ANTHROPIC_MODEL": "MiniMax-M3",
                },
            }), encoding="utf-8")
            self.write_csswitch_config(root, model="deepseek-v4-pro", name="DeepSeek", template_id="deepseek")
            settings_path = root / ".claude" / "settings.json"
            csswitch_path = root / ".csswitch" / "config.json"
            os.utime(csswitch_path, (1000, 1000))
            os.utime(settings_path, (2000, 2000))
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.dict(
                ccscience.os.environ, {"DEEPSEEK_API_KEY": "sk-deepseek-stale"}
            ):
                provider = ccscience.thirdparty_provider_details()
                payload = ccscience.current_model_payload()

        self.assertEqual(provider["source"], "claude-settings")
        self.assertEqual(provider["base_url"], "https://api.minimaxi.com/anthropic")
        self.assertEqual(provider["key"], "sk-minimax-current")
        self.assertEqual(provider["key_env"], "ANTHROPIC_AUTH_TOKEN")
        self.assertEqual(provider["model"], "MiniMax-M3")
        self.assertEqual(payload["upstream_source"], "claude-settings")
        self.assertEqual(payload["upstream_base_url"], "https://api.minimaxi.com/anthropic")
        self.assertEqual(payload["upstream_provider_model"], "MiniMax-M3")
        self.assertTrue(payload["csswitch"]["stale"])

    def test_active_openai_compatible_profile_reads_openai_env_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            path = root / ".csswitch" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mode": "proxy",
                "active_id": "kimi1",
                "proxy_port": 18991,
                "secret": "secret123",
                "profiles": [{
                    "id": "kimi1",
                    "name": "Kimi",
                    "template_id": "kimi",
                    "model": "kimi-k2-0905-preview",
                    "env": {
                        "OPENAI_BASE_URL": "https://api.moonshot.ai/v1",
                        "OPENAI_API_KEY": "sk-kimi-profile",
                    },
                }],
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root):
                provider = ccscience.thirdparty_provider_details()
                target = ccscience.thirdparty_target()

        self.assertEqual(provider["source"], "csswitch-profile")
        self.assertEqual(provider["base_url"], "https://api.moonshot.ai/v1")
        self.assertEqual(provider["key"], "sk-kimi-profile")
        self.assertEqual(provider["key_env"], "profile.env.OPENAI_API_KEY")
        self.assertEqual(provider["model"], "kimi-k2-0905-preview")
        self.assertEqual(target["provider_base"], "https://api.moonshot.ai/v1")
        self.assertEqual(target["model"], "kimi-k2-0905-preview")

    def test_active_profile_reads_provider_specific_env_key_and_model_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            path = root / ".csswitch" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mode": "proxy",
                "active_id": "kimi1",
                "profiles": [{
                    "id": "kimi1",
                    "name": "Kimi",
                    "template_id": "kimi",
                    "env": {
                        "MOONSHOT_API_KEY": "sk-kimi-profile",
                        "OPENAI_MODEL": "kimi-k2.6",
                    },
                }],
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root):
                provider = ccscience.thirdparty_provider_details()

        self.assertEqual(provider["source"], "csswitch-profile")
        self.assertEqual(provider["base_url"], "https://api.moonshot.ai/v1")
        self.assertEqual(provider["key"], "sk-kimi-profile")
        self.assertEqual(provider["key_env"], "profile.env.MOONSHOT_API_KEY")
        self.assertEqual(provider["model"], "kimi-k2.6")

    def test_active_profile_accepts_profiles_dict_and_camelcase_active_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            path = root / ".csswitch" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mode": "proxy",
                "activeId": "kimi1",
                "profiles": {
                    "kimi1": {
                        "name": "Kimi",
                        "templateId": "kimi",
                        "modelName": "kimi-k2.6",
                        "env": {"MOONSHOT_API_KEY": "${MOONSHOT_API_KEY}"},
                    },
                },
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.dict(
                ccscience.os.environ, {"MOONSHOT_API_KEY": "sk-kimi-real"}
            ):
                provider = ccscience.thirdparty_provider_details()
                bridge = ccscience.csswitch_bridge_payload(check_health=False)

        self.assertEqual(provider["source"], "csswitch-profile")
        self.assertEqual(provider["base_url"], "https://api.moonshot.ai/v1")
        self.assertEqual(provider["key"], "sk-kimi-real")
        self.assertEqual(provider["key_env"], "profile.env.MOONSHOT_API_KEY")
        self.assertEqual(provider["model"], "kimi-k2.6")
        self.assertEqual(bridge["template_id"], "kimi")
        self.assertEqual(bridge["model"], "kimi-k2.6")

    def test_active_profile_accepts_inline_active_profile_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            path = root / ".csswitch" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mode": "proxy",
                "activeProfile": {
                    "displayName": "MiniMax Inline",
                    "templateId": "minimax",
                    "modelName": "MiniMax-M3[1M]",
                    "env": {"MINIMAX_API_KEY": "${MINIMAX_API_KEY}"},
                },
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.dict(
                ccscience.os.environ, {"MINIMAX_API_KEY": "sk-minimax-real"}
            ):
                provider = ccscience.thirdparty_provider_details()
                bridge = ccscience.csswitch_bridge_payload(check_health=False)

        self.assertEqual(provider["source"], "csswitch-profile")
        self.assertEqual(provider["base_url"], "https://api.minimax.io/anthropic")
        self.assertEqual(provider["key"], "sk-minimax-real")
        self.assertEqual(provider["model"], "MiniMax-M3")
        self.assertEqual(bridge["profile"], "MiniMax Inline")
        self.assertEqual(bridge["template_id"], "minimax")
        self.assertEqual(bridge["model"], "MiniMax-M3")

    def test_custom_profile_reads_provider_specific_key_from_explicit_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            path = root / ".csswitch" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mode": "proxy",
                "active_id": "custom-kimi",
                "profiles": [{
                    "id": "custom-kimi",
                    "name": "Custom Moonshot",
                    "template_id": "custom",
                    "model": "kimi-k2.6",
                    "env": {
                        "OPENAI_BASE_URL": "${MOONSHOT_BASE_URL}",
                        "MOONSHOT_API_KEY": "${MOONSHOT_API_KEY}",
                    },
                }],
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.dict(
                ccscience.os.environ, {
                    "MOONSHOT_BASE_URL": "https://api.moonshot.ai/v1",
                    "MOONSHOT_API_KEY": "sk-kimi-real",
                }
            ):
                provider = ccscience.thirdparty_provider_details()

        self.assertEqual(provider["source"], "csswitch-profile")
        self.assertEqual(provider["base_url"], "https://api.moonshot.ai/v1")
        self.assertEqual(provider["key"], "sk-kimi-real")
        self.assertEqual(provider["key_env"], "profile.env.MOONSHOT_API_KEY")
        self.assertEqual(provider["model"], "kimi-k2.6")

    def test_status_reports_thirdparty_source_without_secret_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            self.write_csswitch_config(root, model="deepseek-v4-pro", name="DeepSeek", template_id="deepseek")
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.dict(
                ccscience.os.environ, {"DEEPSEEK_API_KEY": "sk-deepseek-secret"}
            ), mock.patch.object(
                ccscience, "_thirdparty_forwarder_health",
                return_value={"forwarder_revision": ccscience.THIRDPARTY_FWD_REVISION, "pid": 1234}
            ), mock.patch.object(
                ccscience, "sandbox_daemon_status", return_value={"running": False}
            ), mock.patch.object(
                ccscience, "sandbox_has_valid_token", return_value=False
            ), mock.patch.object(
                ccscience, "helper_status", return_value="not-running"
            ), mock.patch.object(
                ccscience, "autostart_status", return_value="not-installed"
            ), mock.patch.object(
                ccscience, "runtime_indexes", return_value=[]
            ):
                code, out = ccscience.capture_output(
                    lambda: ccscience.cmd_status(ccscience.argparse.Namespace(port=ccscience.DEFAULT_PORT))
                )

        self.assertEqual(code, 0)
        self.assertIn("thirdparty provider: csswitch-profile (https://api.deepseek.com/anthropic)", out)
        self.assertIn("thirdparty model: deepseek-v4-pro", out)
        self.assertIn("thirdparty key: DEEPSEEK_API_KEY", out)
        self.assertIn(f"thirdparty forwarder: running (rev {ccscience.THIRDPARTY_FWD_REVISION}, pid 1234)", out)
        self.assertNotIn("sk-deepseek-secret", out)

    def test_claude_settings_openai_env_is_direct_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(json.dumps({
                "model": "opus",
                "env": {
                    "OPENAI_BASE_URL": "https://api.moonshot.ai/v1",
                    "OPENAI_API_KEY": "sk-kimi-settings",
                    "OPENAI_MODEL": "kimi-k2.6",
                },
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root):
                provider = ccscience.thirdparty_provider_details()
                payload = ccscience.current_model_payload()

        self.assertEqual(provider["source"], "claude-settings")
        self.assertEqual(provider["base_url"], "https://api.moonshot.ai/v1")
        self.assertEqual(provider["key"], "sk-kimi-settings")
        self.assertEqual(provider["key_env"], "OPENAI_API_KEY")
        self.assertEqual(provider["model"], "kimi-k2.6")
        self.assertEqual(payload["upstream_provider_model"], "kimi-k2.6")

    def test_claude_settings_anthropic_env_uses_provider_tier_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(json.dumps({
                "model": "opus",
                "env": {
                    "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "sk-minimax-settings",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M3[1M]",
                },
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root):
                provider = ccscience.thirdparty_provider_details()
                got = ccscience._provider_model_for_request(
                    "claude-opus-4-8", provider["base_url"], provider.get("model", ""))

        self.assertEqual(provider["source"], "claude-settings")
        self.assertEqual(provider["base_url"], "https://api.minimax.io/anthropic")
        self.assertEqual(provider["key_env"], "ANTHROPIC_AUTH_TOKEN")
        self.assertEqual(provider["model"], "MiniMax-M3")
        self.assertEqual(got, "MiniMax-M3")

    def test_claude_settings_can_read_provider_key_from_shell_env_for_known_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(json.dumps({
                "model": "kimi-k2.6",
                "env": {
                    "OPENAI_BASE_URL": "https://api.moonshot.ai/v1",
                },
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.dict(
                ccscience.os.environ, {"MOONSHOT_API_KEY": "sk-kimi-shell"}
            ):
                provider = ccscience.thirdparty_provider_details()

        self.assertEqual(provider["source"], "claude-settings")
        self.assertEqual(provider["key"], "sk-kimi-shell")
        self.assertEqual(provider["key_env"], "MOONSHOT_API_KEY")
        self.assertEqual(provider["model"], "kimi-k2.6")

    def test_minimax_profile_env_key_reference_defaults_to_international_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            path = root / ".csswitch" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mode": "proxy",
                "active_id": "minimax1",
                "profiles": [{
                    "id": "minimax1",
                    "name": "MiniMax",
                    "template_id": "minimax",
                    "env": {
                        "MINIMAX_API_KEY": "${MINIMAX_API_KEY}",
                        "ANTHROPIC_MODEL": "MiniMax-M3[1M]",
                    },
                }],
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.dict(
                ccscience.os.environ, {"MINIMAX_API_KEY": "sk-minimax-real"}
            ):
                provider = ccscience.thirdparty_provider_details()

        self.assertEqual(provider["source"], "csswitch-profile")
        self.assertEqual(provider["base_url"], "https://api.minimax.io/anthropic")
        self.assertEqual(provider["key"], "sk-minimax-real")
        self.assertEqual(provider["key_env"], "profile.env.MINIMAX_API_KEY")
        self.assertEqual(provider["model"], "MiniMax-M3")

    def test_minimax_profile_can_default_to_china_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            path = root / ".csswitch" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mode": "proxy",
                "active_id": "minimax-cn",
                "profiles": [{
                    "id": "minimax-cn",
                    "name": "MiniMax China",
                    "template_id": "minimax-cn",
                    "model": "MiniMax-M3",
                    "env": {
                        "MINIMAXI_API_KEY": "${MINIMAXI_API_KEY}",
                    },
                }],
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.dict(
                ccscience.os.environ, {"MINIMAXI_API_KEY": "sk-minimaxi-real"}
            ):
                provider = ccscience.thirdparty_provider_details()

        self.assertEqual(provider["source"], "csswitch-profile")
        self.assertEqual(provider["base_url"], "https://api.minimaxi.com/anthropic")
        self.assertEqual(provider["key"], "sk-minimaxi-real")
        self.assertEqual(provider["key_env"], "profile.env.MINIMAXI_API_KEY")
        self.assertEqual(provider["model"], "MiniMax-M3")

    def test_custom_profile_with_explicit_openai_base_and_key_is_direct_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            path = root / ".csswitch" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mode": "proxy",
                "active_id": "custom1",
                "profiles": [{
                    "id": "custom1",
                    "name": "My Relay",
                    "template_id": "custom",
                    "model": "relay-model",
                    "base_url": "https://relay.example.com/v1",
                    "api_key": "sk-custom-relay",
                }],
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root):
                provider = ccscience.thirdparty_provider_details()
                target = ccscience.thirdparty_target()

        self.assertEqual(provider["source"], "csswitch-profile")
        self.assertEqual(provider["base_url"], "https://relay.example.com/v1")
        self.assertEqual(provider["key"], "sk-custom-relay")
        self.assertEqual(provider["key_env"], "profile.api_key")
        self.assertEqual(provider["model"], "relay-model")
        self.assertEqual(target["provider_base"], "https://relay.example.com/v1")
        self.assertEqual(target["model"], "relay-model")

    def test_custom_profile_with_explicit_anthropic_base_and_key_is_direct_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            path = root / ".csswitch" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mode": "proxy",
                "active_id": "custom2",
                "profiles": [{
                    "id": "custom2",
                    "name": "Anthropic Relay",
                    "template_id": "custom",
                    "model": "relay-claude-model",
                    "env": {
                        "ANTHROPIC_BASE_URL": "https://relay.example.com/anthropic",
                        "ANTHROPIC_AUTH_TOKEN": "sk-custom-anthropic",
                    },
                }],
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root):
                provider = ccscience.thirdparty_provider_details()
                target = ccscience.thirdparty_target()

        self.assertEqual(provider["source"], "csswitch-profile")
        self.assertEqual(provider["base_url"], "https://relay.example.com/anthropic")
        self.assertEqual(provider["key"], "sk-custom-anthropic")
        self.assertEqual(provider["key_env"], "profile.env.ANTHROPIC_AUTH_TOKEN")
        self.assertEqual(provider["model"], "relay-claude-model")
        self.assertEqual(target["provider_base"], "https://relay.example.com/anthropic")
        self.assertEqual(target["model"], "relay-claude-model")

    def test_custom_profile_with_placeholder_key_is_not_direct_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            path = root / ".csswitch" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mode": "proxy",
                "active_id": "custom3",
                "profiles": [{
                    "id": "custom3",
                    "name": "Hidden Relay",
                    "template_id": "custom",
                    "model": "relay-model",
                    "base_url": "https://relay.example.com/v1",
                    "api_key": "hidden",
                }],
            }), encoding="utf-8")
            with mock.patch.object(ccscience, "home", return_value=root):
                provider = ccscience.thirdparty_provider_details()

        self.assertIsNone(provider)

    def test_launch_environment_uses_running_csswitch_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_csswitch_config(root)
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.object(
                ccscience, "csswitch_proxy_health", return_value=True
            ):
                env, bridge = ccscience.science_launch_environment()

        self.assertTrue(bridge["proxy_running"])
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:18991/secret123")

    def test_launch_environment_skips_stopped_csswitch_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_csswitch_config(root)
            with mock.patch.object(ccscience, "home", return_value=root), mock.patch.object(
                ccscience, "csswitch_proxy_health", return_value=False
            ):
                env, bridge = ccscience.science_launch_environment()

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

            self.assertEqual(ccscience.patch_index(path, 19783), "installed")
            patched = path.read_text(encoding="utf-8")
            self.assertIn(ccscience.MARKER_START, patched)
            self.assertIn("http://127.0.0.1:19783/model", patched)

            self.assertEqual(ccscience.unpatch_index(path), "removed")
            self.assertNotIn(ccscience.MARKER_START, path.read_text(encoding="utf-8"))

    def test_injection_refreshes_before_request(self):
        script = ccscience.injection_script(19783)
        self.assertIn("originalFetch.call(window, endpoint", script)
        self.assertIn("patchRequest(input, init)", script)
        self.assertIn('window.addEventListener("focus", scheduleSync)', script)
        self.assertNotIn("setInterval(syncAsync, 5000)", script)


class CryptoTests(unittest.TestCase):
    def test_aes256_gcm_nist_vectors(self):
        # NIST GCM test case 13: all-zero 256-bit key/IV, empty plaintext/AAD
        _, tag = ccscience.aes_gcm_encrypt(bytes(32), bytes(12), b"", b"")
        self.assertEqual(tag.hex(), "530f8afbc74536b9a963b4f1c4cb738b")
        # NIST GCM test case 14: one zero block of plaintext
        ct, tag = ccscience.aes_gcm_encrypt(bytes(32), bytes(12), bytes(16), b"")
        self.assertEqual(ct.hex(), "cea7403d4d606b6e074ec5d3baf39d18")
        self.assertEqual(tag.hex(), "d0d1c8a799996bf0265b98b5d48ab919")

    def test_hkdf_sha256_rfc5869_vector(self):
        # RFC 5869 test case 1
        ikm = bytes.fromhex("0b" * 22)
        salt = bytes.fromhex("000102030405060708090a0b0c")
        info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
        okm = ccscience.hkdf_sha256(ikm, salt, info, 42)
        self.assertEqual(
            okm.hex(),
            "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865",
        )

    def test_gcm_decrypt_roundtrip_and_tamper(self):
        key = bytes(range(32))
        iv = bytes(range(12))
        pt = b"the quick brown fox jumps"
        ct, tag = ccscience.aes_gcm_encrypt(key, iv, pt, b"v2:oauth")
        self.assertEqual(ccscience.aes_gcm_decrypt(key, iv, ct, tag, b"v2:oauth"), pt)
        with self.assertRaises(ValueError):
            ccscience.aes_gcm_decrypt(key, iv, ct, tag, b"wrong-aad")
        bad = bytearray(ct)
        bad[0] ^= 1
        with self.assertRaises(ValueError):
            ccscience.aes_gcm_decrypt(key, iv, bytes(bad), tag, b"v2:oauth")

    def test_token_v2_roundtrip(self):
        key_b64 = ccscience.base64.b64encode(bytes(range(32))).decode()
        body = ccscience.encrypt_token_v2('{"email":"virtual@localhost.invalid"}', key_b64)
        self.assertTrue(body.startswith("v2:"))
        self.assertEqual(
            ccscience.json.loads(ccscience.decrypt_token_v2(body, key_b64))["email"],
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
            info = ccscience.forge_virtual_oauth(auth)
            self.assertEqual(info["email"], ccscience.VIRTUAL_EMAIL)
            self.assertTrue((auth / "encryption.key").is_file())
            self.assertTrue((auth / "active-org.json").is_file())
            encs = list((auth / ".oauth-tokens").glob("*.enc"))
            self.assertEqual(len(encs), 1)
            self.assertTrue(ccscience.sandbox_has_valid_token(auth))
            org = ccscience.json.loads((auth / "active-org.json").read_text())
            self.assertEqual(org["org_uuid"], info["org_uuid"])

    def test_forge_keeps_single_enc_and_reuses_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = self._sandbox(tmp)
            first = ccscience.forge_virtual_oauth(auth)
            key1 = (auth / "encryption.key").read_text()
            second = ccscience.forge_virtual_oauth(auth)
            key2 = (auth / "encryption.key").read_text()
            self.assertEqual(key1, key2)  # encryption.key reused so old .enc stays decryptable
            self.assertEqual(len(list((auth / ".oauth-tokens").glob("*.enc"))), 1)
            self.assertNotEqual(first["account_uuid"], second["account_uuid"])

    def test_forge_can_embed_explicit_access_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = self._sandbox(tmp)
            ccscience.forge_virtual_oauth(auth, access_token="sk-real-provider-key", force=True)
            keys = ccscience._parse_key_file((auth / "encryption.key").read_text())
            enc = next(iter((auth / ".oauth-tokens").glob("*.enc"))).read_text()
            blob = json.loads(ccscience.decrypt_token_v2(enc, keys["OAUTH_ENCRYPTION_KEY"]))
            # Kept as an explicit low-level escape hatch; normal direct mode
            # uses a throwaway token and lets the forwarder inject the real key.
            self.assertEqual(blob["access_token"], "sk-real-provider-key")

    def test_forge_without_token_uses_throwaway_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = self._sandbox(tmp)
            ccscience.forge_virtual_oauth(auth)
            keys = ccscience._parse_key_file((auth / "encryption.key").read_text())
            enc = next(iter((auth / ".oauth-tokens").glob("*.enc"))).read_text()
            blob = json.loads(ccscience.decrypt_token_v2(enc, keys["OAUTH_ENCRYPTION_KEY"]))
            self.assertTrue(blob["access_token"].startswith("sk-ant-virtual-"))

    def test_refuses_real_credential_dir(self):
        with self.assertRaises(SystemExit):
            ccscience.forge_virtual_oauth(ccscience.home() / ".claude-science")

    def test_refuses_non_virtual_email(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                ccscience.forge_virtual_oauth(self._sandbox(tmp), email="me@gmail.com")

    def test_refuses_path_outside_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = pathlib.Path(tmp) / "plain" / ".claude-science"
            auth.parent.mkdir(parents=True)
            with self.assertRaises(SystemExit):
                ccscience.forge_virtual_oauth(auth)

    def test_guardrail_rejects_real_port(self):
        with self.assertRaises(SystemExit):
            ccscience._assert_sandbox_guardrails(ccscience.REAL_SCIENCE_PORT)


class SandboxLaunchEnvTests(unittest.TestCase):
    def test_launch_env_proxy_mode_routes_and_fastfails_anthropic(self):
        with mock.patch.object(ccscience, "home", return_value=pathlib.Path(tempfile.gettempdir())):
            env = ccscience.sandbox_launch_env(
                {"mode": "csswitch-proxy", "base_url": "http://127.0.0.1:18991/secret123"})
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:18991/secret123")
        self.assertEqual(env["https_proxy"], "http://127.0.0.1:18991")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:18991")
        self.assertIn("127.0.0.1", env["no_proxy"])
        self.assertIn(".sandbox", env["HOME"])

    def test_launch_env_direct_mode_routes_to_provider_and_fastfails(self):
        with mock.patch.object(ccscience, "home", return_value=pathlib.Path(tempfile.gettempdir())):
            env = ccscience.sandbox_launch_env(
                {"mode": "direct", "base_url": "https://api.deepseek.com/anthropic"})
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.deepseek.com/anthropic")
        # Provider host bypasses the dead proxy so inference reaches it directly.
        self.assertIn("api.deepseek.com", env["no_proxy"])
        # Anthropic HTTPS fast-fails via a dead local port — no proxy process.
        self.assertTrue(env["https_proxy"].startswith("http://127.0.0.1:"))
        self.assertNotIn("18991", env["https_proxy"])

    def test_thirdparty_target_prefers_direct_env(self):
        with mock.patch.dict(ccscience.os.environ, {"CCSCIENCE_TP_BASE": "", "CCSCIENCE_TP_KEY": ""}):
            with mock.patch.object(ccscience, "load_json", return_value={
                "model": "deepseek-v4-pro",
                "env": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                        "ANTHROPIC_AUTH_TOKEN": "sk-real-key"},
            }):
                target = ccscience.thirdparty_target()
        self.assertEqual(target["mode"], "direct")
        # Routed through OUR forwarder; the real provider is kept in provider_base.
        self.assertEqual(target["base_url"], f"http://127.0.0.1:{ccscience.THIRDPARTY_FWD_PORT}")
        self.assertEqual(target["provider_base"], "https://api.deepseek.com/anthropic")
        # The sandbox OAuth token stays a throwaway placeholder; the forwarder
        # reads/injects the real key instead of copying it into sandbox files.
        self.assertIsNone(target["access_token"])

    def test_thirdparty_target_id_changes_when_direct_model_changes(self):
        with mock.patch.object(ccscience, "thirdparty_provider_details",
                               return_value={"base_url": "https://api.deepseek.com/anthropic",
                                             "key": "sk-test", "source": "test",
                                             "model": "deepseek-v4-pro"}):
            first = ccscience.thirdparty_target()
        with mock.patch.object(ccscience, "thirdparty_provider_details",
                               return_value={"base_url": "https://api.deepseek.com/anthropic",
                                             "key": "sk-test", "source": "test",
                                             "model": "deepseek-v4-flash"}):
            second = ccscience.thirdparty_target()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["model"], "deepseek-v4-pro")
        self.assertEqual(second["model"], "deepseek-v4-flash")

    def test_normalize_thinking_auto_to_adaptive(self):
        # operon sends thinking.type "auto"; DeepSeek/MiniMax only accept adaptive.
        body = ccscience.normalize_thirdparty_request(
            {"thinking": {"type": "auto"}}, "api.deepseek.com")
        self.assertEqual(body["thinking"]["type"], "adaptive")

    def test_normalize_thinking_deepseek_forced_tool_disables(self):
        body = ccscience.normalize_thirdparty_request(
            {"thinking": {"type": "auto"}, "tool_choice": {"type": "any"}}, "api.deepseek.com")
        self.assertEqual(body["thinking"]["type"], "disabled")

    def test_normalize_strips_cache_control_everywhere(self):
        # cache_control is Anthropic-only; third-party endpoints reject the
        # request when present (MiniMax 400 2013, DeepSeek 400). Strip it from
        # tools, system blocks, and message content blocks.
        body = ccscience.normalize_thirdparty_request({
            "tools": [{"name": "x", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                       "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            "system": [{"type": "text", "text": "rules",
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user",
                          "content": [{"type": "text", "text": "hi",
                                       "cache_control": {"type": "ephemeral"}}]}],
        }, "api.minimaxi.com")
        self.assertNotIn("cache_control", body["tools"][0])
        self.assertNotIn("cache_control", body["system"][0])
        self.assertNotIn("cache_control", body["messages"][0]["content"][0])
        # the tool name and schema survive
        self.assertEqual(body["tools"][0]["name"], "x")
        self.assertEqual(body["tools"][0]["input_schema"], {
            "type": "object",
            "properties": {"q": {"type": "string"}},
        })

    def test_normalize_tools_drops_empty_schema_and_invalid_entries(self):
        body = ccscience.normalize_thirdparty_request({
            "tools": [
                {"name": "valid-but-empty"},
                {"name": "with-schema", "input_schema": {"properties": {"q": {"type": "string"}}}},
                {"name": ""},
                {"input_schema": {"type": "object"}},
            ],
            "tool_choice": {"type": "tool", "name": "missing"},
        }, "api.minimaxi.com")

        self.assertEqual([tool["name"] for tool in body["tools"]], ["with-schema"])
        self.assertEqual(
            body["tools"][0]["input_schema"],
            {"type": "object", "properties": {"q": {"type": "string"}}},
        )
        self.assertEqual(body["tool_choice"], {"type": "auto"})

    def test_normalize_removes_forced_tool_choice_when_no_tools_survive(self):
        body = ccscience.normalize_thirdparty_request({
            "tools": [{"name": ""}, "bad"],
            "tool_choice": {"type": "any"},
        }, "api.minimaxi.com")

        self.assertNotIn("tools", body)
        self.assertNotIn("tool_choice", body)

    def test_normalize_drops_schema_less_web_search_tool(self):
        body = ccscience.normalize_thirdparty_request({
            "tools": [
                {"name": "web_search"},
                {"name": "bash", "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                }},
            ],
        }, "api.minimaxi.com")

        self.assertEqual([tool["name"] for tool in body["tools"]], ["bash"])

    def test_normalize_deepseek_forced_tool_still_strips_cache_control(self):
        body = ccscience.normalize_thirdparty_request({
            "thinking": {"type": "auto"},
            "tool_choice": {"type": "any"},
            "tools": [{"name": "x", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                       "cache_control": {"type": "ephemeral"}}],
        }, "api.deepseek.com")
        self.assertEqual(body["thinking"]["type"], "disabled")
        self.assertNotIn("cache_control", body["tools"][0])
        self.assertEqual(body["tools"][0]["input_schema"]["properties"]["q"]["type"], "string")

    def test_thirdparty_target_falls_back_to_running_proxy(self):
        with mock.patch.object(ccscience, "thirdparty_provider_details", return_value=None):
            with mock.patch.object(ccscience, "csswitch_proxy_url",
                                   return_value="http://127.0.0.1:18991/secret"):
                with mock.patch.object(ccscience, "csswitch_bridge_payload",
                                       return_value={"enabled": True, "proxy_running": True,
                                                     "model": "deepseek-v4-pro"}):
                    target = ccscience.thirdparty_target()
        self.assertEqual(target["mode"], "csswitch-proxy")
        self.assertEqual(target["base_url"], "http://127.0.0.1:18991/secret")

    def test_thirdparty_target_none_without_any_source(self):
        with mock.patch.object(ccscience, "thirdparty_provider_details", return_value=None):
            with mock.patch.object(ccscience, "csswitch_proxy_url", return_value=None):
                with mock.patch.object(ccscience, "csswitch_bridge_payload",
                                       return_value={"enabled": False, "proxy_running": False}):
                    self.assertIsNone(ccscience.thirdparty_target())

    def test_open_thirdparty_requires_a_source(self):
        with mock.patch.object(ccscience, "thirdparty_target", return_value=None):
            with self.assertRaises(SystemExit) as raised:
                ccscience.open_thirdparty("en")
        self.assertEqual(str(raised.exception), ccscience.tr("en", "thirdparty_needs_source"))


class SandboxRuntimeTests(unittest.TestCase):
    def test_clone_dir_is_atomic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / "src"
            (src / "sub").mkdir(parents=True)
            (src / "sub" / "f.txt").write_text("hi", encoding="utf-8")
            dst = pathlib.Path(tmp) / "dst"
            ccscience._clone_dir(src, dst)
            self.assertEqual((dst / "sub" / "f.txt").read_text(encoding="utf-8"), "hi")
            # no partial staging dir left behind
            self.assertFalse([p for p in dst.parent.iterdir() if ".partial-" in p.name])
            # second call short-circuits on existing dst without error
            ccscience._clone_dir(src, dst)

    def test_launched_proxy_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ccscience, "sandbox_home", return_value=pathlib.Path(tmp)):
                self.assertIsNone(ccscience.launched_proxy_url())
                ccscience.launched_proxy_path().write_text("http://127.0.0.1:18991/abc", encoding="utf-8")
                self.assertEqual(ccscience.launched_proxy_url(), "http://127.0.0.1:18991/abc")

    def test_forge_refuses_symlink_leaf_to_real_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = pathlib.Path(tmp) / "real" / ".claude-science"
            real.mkdir(parents=True)
            sbx = pathlib.Path(tmp) / ".sandbox" / "home" / ".claude-science"
            sbx.parent.mkdir(parents=True)
            sbx.symlink_to(real)
            with mock.patch.object(ccscience, "home", return_value=pathlib.Path(tmp) / "real"):
                with self.assertRaises(SystemExit):
                    ccscience.forge_virtual_oauth(sbx)


class ThirdpartyForwarderTests(unittest.TestCase):
    def setUp(self):
        ccscience._LAST_UPSTREAM_MODEL = ""
        ccscience._TIER_MODELS.clear()
        ccscience._LAST_PROVIDER_STATE = ""

    @contextlib.contextmanager
    def _isolated_forwarder_settings(self):
        with mock.patch.dict(os.environ, {"CCSCIENCE_TP_MODEL": ""}, clear=False):
            with mock.patch.object(ccscience, "_thirdparty_settings_env", return_value={}):
                yield

    def _forwarder_json_roundtrip(self, provider, request_body, upstream_response):
        captured = {}

        class Upstream:
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(upstream_response).encode()

            def getcode(self):
                return 200

        def fake_open(req, timeout=300):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode())
            captured["timeout"] = timeout
            return Upstream()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self._isolated_forwarder_settings():
                with mock.patch.object(ccscience, "thirdparty_provider_details", return_value=provider):
                    with mock.patch.object(ccscience, "_open_upstream", side_effect=fake_open):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{server.server_port}/v1/messages",
                            data=json.dumps(request_body).encode(),
                            method="POST",
                            headers={"Content-Type": "application/json"},
                        )
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            got = json.loads(resp.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        return captured, got

    def test_provider_brand_known_and_fallback(self):
        self.assertEqual(ccscience._provider_brand("api.deepseek.com"), "DeepSeek")
        self.assertEqual(ccscience._provider_brand("api.minimaxi.com"), "MiniMax")
        self.assertEqual(ccscience._provider_brand("api.foobar.example.cn"), "Foobar")
        self.assertEqual(ccscience._provider_brand(""), "Third-Party")

    def test_pretty_model(self):
        self.assertEqual(ccscience._pretty_model("DeepSeek", "deepseek-v4-pro"), "DeepSeek V4 Pro")
        self.assertEqual(ccscience._pretty_model("MiniMax", "MiniMax-M2"), "MiniMax M2")
        # no model known yet -> fall back to the brand
        self.assertEqual(ccscience._pretty_model("DeepSeek", ""), "DeepSeek")

    def test_record_upstream_model_maps_tier(self):
        ccscience._record_upstream_model(
            "claude-opus-4-8", b'{"type":"message","model":"deepseek-v4-pro"}')
        self.assertEqual(ccscience._LAST_UPSTREAM_MODEL, "deepseek-v4-pro")
        self.assertEqual(ccscience._TIER_MODELS["claude-opus-4-8"], "deepseek-v4-pro")
        # a blob without a model id leaves state untouched
        ccscience._record_upstream_model("claude-opus-4-8", b'{"type":"ping"}')
        self.assertEqual(ccscience._LAST_UPSTREAM_MODEL, "deepseek-v4-pro")

    def test_forwarder_health_endpoint_reports_version(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=5) as resp:
                got = json.loads(resp.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertTrue(got["ok"])
        self.assertEqual(got["adapter"], "thirdparty-forwarder")
        self.assertEqual(got["version"], ccscience.VERSION)
        self.assertEqual(got["forwarder_revision"], ccscience.THIRDPARTY_FWD_REVISION)
        self.assertIsInstance(got["pid"], int)

    def test_thirdparty_forwarder_healthy_requires_current_version(self):
        class Response:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return json.dumps(self.payload).encode()

        with mock.patch.object(ccscience.urllib.request, "urlopen",
                               return_value=Response({"ok": True,
                                                      "adapter": "thirdparty-forwarder",
                                                      "version": ccscience.VERSION,
                                                      "forwarder_revision": ccscience.THIRDPARTY_FWD_REVISION})):
            self.assertTrue(ccscience.thirdparty_forwarder_healthy(12345))

        with mock.patch.object(ccscience.urllib.request, "urlopen",
                               return_value=Response({"ok": True,
                                                      "adapter": "thirdparty-forwarder",
                                                      "version": "0.3.0",
                                                      "forwarder_revision": ccscience.THIRDPARTY_FWD_REVISION})):
            self.assertFalse(ccscience.thirdparty_forwarder_healthy(12345))

        with mock.patch.object(ccscience.urllib.request, "urlopen",
                               return_value=Response({"ok": True,
                                                      "adapter": "thirdparty-forwarder",
                                                      "version": ccscience.VERSION,
                                                      "forwarder_revision": 1})):
            self.assertFalse(ccscience.thirdparty_forwarder_healthy(12345))

        with mock.patch.object(ccscience.urllib.request, "urlopen",
                               side_effect=ccscience.urllib.error.URLError("down")):
            self.assertFalse(ccscience.thirdparty_forwarder_healthy(12345))

    def test_terminate_process_on_port_only_kills_ccscience_process(self):
        with mock.patch.object(ccscience, "is_windows", return_value=False):
            with mock.patch.object(ccscience, "_listening_pids_on_port", side_effect=[[123456], []]):
                with mock.patch.object(ccscience, "_process_command",
                                       return_value="/usr/bin/python ccscience.py serve-forwarder"):
                    with mock.patch.object(ccscience.os, "kill") as kill:
                        self.assertTrue(ccscience._terminate_process_on_port(19784))

        kill.assert_called_once_with(123456, ccscience.signal.SIGTERM)

    def test_terminate_process_on_port_skips_unrelated_process(self):
        with mock.patch.object(ccscience, "is_windows", return_value=False):
            with mock.patch.object(ccscience, "_listening_pids_on_port", return_value=[123456]):
                with mock.patch.object(ccscience, "_process_command", return_value="/usr/bin/python other.py"):
                    with mock.patch.object(ccscience.os, "kill") as kill:
                        self.assertFalse(ccscience._terminate_process_on_port(19784))

        kill.assert_not_called()

    def test_ensure_forwarder_clears_stale_port_and_spawns(self):
        with mock.patch.object(ccscience, "thirdparty_forwarder_healthy",
                               side_effect=[False, False, True]) as healthy:
            with mock.patch.object(ccscience, "_terminate_process_on_port") as terminate:
                with mock.patch.object(ccscience.subprocess, "Popen") as popen:
                    with mock.patch.object(ccscience.time, "sleep"):
                        ccscience.ensure_thirdparty_forwarder()

        self.assertEqual(healthy.call_count, 3)
        terminate.assert_called_once_with(ccscience.THIRDPARTY_FWD_PORT)
        popen.assert_called_once()

    def test_ensure_forwarder_raises_when_spawn_never_becomes_ready(self):
        with mock.patch.object(ccscience, "thirdparty_forwarder_healthy", return_value=False):
            with mock.patch.object(ccscience, "_terminate_process_on_port"):
                with mock.patch.object(ccscience.subprocess, "Popen"):
                    with mock.patch.object(ccscience.time, "sleep"):
                        with self.assertRaises(SystemExit) as raised:
                            ccscience.ensure_thirdparty_forwarder()

        self.assertEqual(str(raised.exception), "third-party forwarder did not become ready")

    def test_thirdparty_label_resets_when_same_provider_model_changes(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(ccscience, "thirdparty_provider_details",
                                   return_value={"base_url": "https://api.deepseek.com/anthropic",
                                                 "key": "sk-test", "source": "test",
                                                 "model": "deepseek-v4-pro"}):
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/thirdparty-label", timeout=5
                ) as resp:
                    initial = json.loads(resp.read().decode())
                ccscience._record_upstream_model(
                    "claude-opus-4-8", b'{"model":"deepseek-v4-pro"}')
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/thirdparty-label", timeout=5
                ) as resp:
                    first = json.loads(resp.read().decode())
            with mock.patch.object(ccscience, "thirdparty_provider_details",
                                   return_value={"base_url": "https://api.deepseek.com/anthropic",
                                                 "key": "sk-test", "source": "test",
                                                 "model": "deepseek-v4-flash"}):
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/thirdparty-label", timeout=5
                ) as resp:
                    second = json.loads(resp.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(initial["display"], "DeepSeek V4 Pro")
        self.assertEqual(first["tiers"]["claude-opus-4-8"], "DeepSeek V4 Pro")
        self.assertEqual(second["tiers"], {})
        self.assertEqual(second["display"], "DeepSeek V4 Flash")

    def test_open_upstream_falls_back_on_self_signed_cert(self):
        import ssl
        import urllib.error
        sentinel = object()
        err = urllib.error.URLError(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED"))
        with mock.patch("urllib.request.urlopen", side_effect=[err, sentinel]) as uo:
            got = ccscience._open_upstream(mock.Mock(), timeout=1)
        self.assertIs(got, sentinel)
        # the retry disabled verification
        self.assertEqual(uo.call_args.kwargs.get("context").verify_mode, ssl.CERT_NONE)

    def test_open_upstream_strict_tls_reraises(self):
        import ssl
        import urllib.error
        err = urllib.error.URLError(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED"))
        with mock.patch.dict("os.environ", {"CCSCIENCE_TP_STRICT_TLS": "1"}):
            with mock.patch("urllib.request.urlopen", side_effect=err):
                with self.assertRaises(urllib.error.URLError):
                    ccscience._open_upstream(mock.Mock(), timeout=1)

    def test_normalize_minimax_keeps_thinking_not_disabled(self):
        # the DeepSeek-only "disable thinking under forced tool_choice" must not
        # fire for other providers (e.g. MiniMax) — they just get adaptive.
        body = ccscience.normalize_thirdparty_request(
            {"thinking": {"type": "auto"}, "tool_choice": {"type": "any"}}, "api.minimaxi.com")
        self.assertEqual(body["thinking"]["type"], "adaptive")

    def test_provider_model_for_request_uses_ccswitch_tier_override(self):
        with mock.patch.object(ccscience, "load_json", return_value={
            "model": "opus",
            "env": {
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M3[1M]",
                "ANTHROPIC_MODEL": "fallback-model",
            },
        }):
            got = ccscience._provider_model_for_request("claude-opus-4-8")
        self.assertEqual(got, "MiniMax-M3")

    def test_provider_model_for_request_falls_back_to_anthropic_model(self):
        with mock.patch.object(ccscience, "load_json", return_value={
            "model": "sonnet",
            "env": {"ANTHROPIC_MODEL": "kimi-k2-0905-preview"},
        }):
            got = ccscience._provider_model_for_request("claude-sonnet-5")
        self.assertEqual(got, "kimi-k2-0905-preview")

    def test_provider_model_per_tier_overrides_selected_model(self):
        # A per-tier DeepSeek setup: the active profile resolves a single
        # headline model (deepseek-v4-pro, the opus tier), but a background
        # haiku request must still map to the cheaper haiku-tier model rather
        # than being short-circuited onto the pricey selected model.
        with mock.patch.object(ccscience, "load_json", return_value={
            "model": "opus",
            "env": {
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash",
            },
        }):
            got = ccscience._provider_model_for_request(
                "claude-haiku-4-5", "https://api.deepseek.com", "deepseek-v4-pro")
        self.assertEqual(got, "deepseek-v4-flash")

    def test_provider_model_uses_selected_model_when_no_tier_override(self):
        # Single-model providers (Kimi maps every tier to one model) have no
        # per-tier env entry, so selected_model is still honored.
        with mock.patch.object(ccscience, "load_json", return_value={
            "model": "sonnet",
            "env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"},
        }):
            got = ccscience._provider_model_for_request(
                "claude-haiku-4-5", "https://api.moonshot.ai/v1", "kimi-k2-0905-preview")
        self.assertEqual(got, "kimi-k2-0905-preview")

    def test_relay_openai_stream_survives_incomplete_read(self):
        # A flaky third-party relay closes the SSE connection mid-stream. urllib
        # raises http.client.IncompleteRead (an HTTPException, NOT an OSError),
        # so the relay must swallow it rather than let the worker thread
        # traceback — the already-streamed content should still reach operon.
        class FlakyUpstream:
            def __init__(self):
                self._chunks = [b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n']

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _n=4096):
                if self._chunks:
                    return self._chunks.pop(0)
                raise http.client.IncompleteRead(b"")

        handler = ccscience.ThirdpartyForwardHandler.__new__(
            ccscience.ThirdpartyForwardHandler)
        handler.wfile = io.BytesIO()
        handler.send_response = lambda *a, **k: None
        handler.send_header = lambda *a, **k: None
        handler.end_headers = lambda *a, **k: None
        # Must not raise despite the mid-stream IncompleteRead.
        handler._relay_openai_stream(FlakyUpstream(), "claude-opus-4-8", "deepseek-v4-pro")
        out = handler.wfile.getvalue()
        self.assertIn(b"message_start", out)
        self.assertIn(b"Hi", out)

    def test_openai_compatible_base_detection(self):
        self.assertTrue(ccscience._is_openai_compatible_base("https://api.moonshot.ai/v1"))
        self.assertTrue(ccscience._is_openai_compatible_base("https://openrouter.ai/api/v1"))
        self.assertTrue(ccscience._is_openai_compatible_base("https://api.deepseek.com"))
        self.assertTrue(ccscience._is_openai_compatible_base("https://open.bigmodel.cn/api/paas/v4"))
        self.assertTrue(ccscience._is_openai_compatible_base("https://dashscope.aliyuncs.com/compatible-mode/v1"))
        self.assertFalse(ccscience._is_openai_compatible_base("https://api.deepseek.com/anthropic"))
        self.assertFalse(ccscience._is_openai_compatible_base("https://api.minimax.io/anthropic"))
        self.assertEqual(
            ccscience._openai_chat_url("https://api.moonshot.ai/v1"),
            "https://api.moonshot.ai/v1/chat/completions",
        )
        self.assertEqual(
            ccscience._openai_chat_url("https://open.bigmodel.cn/api/paas/v4"),
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        )

    def test_anthropic_endpoint_url_accepts_base_url_variants(self):
        self.assertEqual(
            ccscience._anthropic_endpoint_url("https://api.deepseek.com/anthropic", "/v1/messages"),
            "https://api.deepseek.com/anthropic/v1/messages",
        )
        self.assertEqual(
            ccscience._anthropic_endpoint_url("https://api.deepseek.com/anthropic/v1", "/v1/messages"),
            "https://api.deepseek.com/anthropic/v1/messages",
        )
        self.assertEqual(
            ccscience._anthropic_endpoint_url(
                "https://api.deepseek.com/anthropic/v1/messages",
                "/v1/messages",
            ),
            "https://api.deepseek.com/anthropic/v1/messages",
        )
        self.assertEqual(
            ccscience._anthropic_endpoint_url(
                "https://api.deepseek.com/anthropic/v1/messages",
                "/v1/messages?beta=1",
            ),
            "https://api.deepseek.com/anthropic/v1/messages?beta=1",
        )

    def test_anthropic_request_to_openai_chat_completions(self):
        body = {
            "model": "claude-opus-4-8",
            "max_tokens": 64,
            "stream": False,
            "system": [{"type": "text", "text": "system rules"}],
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"q": "x"}}
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}
                ]},
            ],
            "tools": [{"name": "lookup", "description": "search",
                       "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}],
            "tool_choice": {"type": "any"},
        }
        got = ccscience._anthropic_to_openai_request(body, "kimi-k2", "api.moonshot.ai")
        self.assertEqual(got["model"], "kimi-k2")
        self.assertEqual(got["messages"][0], {"role": "system", "content": "system rules"})
        self.assertEqual(got["messages"][1], {"role": "user", "content": "hi"})
        self.assertEqual(got["messages"][2]["tool_calls"][0]["function"]["name"], "lookup")
        self.assertEqual(got["messages"][3], {
            "role": "tool", "tool_call_id": "toolu_1", "content": "ok", "name": "lookup",
        })
        self.assertEqual(got["tools"][0]["function"]["parameters"]["properties"]["q"]["type"], "string")
        self.assertEqual(got["tool_choice"], "required")
        self.assertEqual(got["thinking"], {"type": "disabled"})

    def test_openai_request_preserves_user_image_and_video_parts(self):
        body = {
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "describe these"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aW1n"}},
                {"type": "video", "source": {"type": "base64", "media_type": "video/mp4", "data": "dmlk"}},
            ]}],
        }
        got = ccscience._anthropic_to_openai_request(body, "kimi-k2.6", "api.moonshot.ai")
        content = got["messages"][0]["content"]

        self.assertEqual(content[0], {"type": "text", "text": "describe these"})
        self.assertEqual(content[1], {"type": "image_url",
                                      "image_url": {"url": "data:image/png;base64,aW1n"}})
        self.assertEqual(content[2], {"type": "video_url",
                                      "video_url": {"url": "data:video/mp4;base64,dmlk"}})

    def test_openai_request_preserves_multimodal_tool_result(self):
        body = {
            "messages": [{"role": "user", "content": [
                "prefix",
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "anBn"}},
                    {"type": "text", "text": "screenshot"},
                ]},
            ]}],
        }
        got = ccscience._anthropic_to_openai_request(body, "kimi-k2.6", "api.moonshot.ai")

        self.assertEqual(got["messages"][0], {"role": "user", "content": "prefix"})
        self.assertEqual(got["messages"][1]["role"], "tool")
        self.assertEqual(got["messages"][1]["tool_call_id"], "toolu_1")
        self.assertEqual(got["messages"][1]["content"][0], {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,anBn"},
        })
        self.assertEqual(got["messages"][1]["content"][1], {"type": "text", "text": "screenshot"})

    def test_kimi_tool_result_includes_tool_name_when_known(self):
        body = {"messages": [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"q": "x"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"},
            ]},
        ]}
        got = ccscience._anthropic_to_openai_request(body, "kimi-k2.6", "api.moonshot.ai")

        self.assertEqual(got["messages"][1], {
            "role": "tool", "tool_call_id": "toolu_1", "content": "ok", "name": "lookup",
        })

    def test_non_kimi_tool_result_does_not_add_tool_name(self):
        body = {"messages": [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"q": "x"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"},
            ]},
        ]}
        got = ccscience._anthropic_to_openai_request(body, "gpt-test", "api.openai.com")

        self.assertEqual(got["messages"][1], {
            "role": "tool", "tool_call_id": "toolu_1", "content": "ok",
        })

    def test_kimi_request_skips_adaptive_thinking_and_preserves_reasoning_content(self):
        body = {
            "model": "claude-opus-4-8",
            "thinking": {"type": "adaptive"},
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "kept reasoning"},
                    {"type": "text", "text": "answer"},
                ]},
                {"role": "user", "content": [{"type": "text", "text": "continue"}]},
            ],
        }
        got = ccscience._anthropic_to_openai_request(body, "kimi-k2.6", "api.moonshot.ai")

        self.assertNotIn("thinking", got)
        self.assertEqual(got["messages"][0]["content"], "answer")
        self.assertEqual(got["messages"][0]["reasoning_content"], "kept reasoning")

    def test_openai_request_does_not_preserve_reasoning_for_non_kimi_hosts(self):
        body = {"messages": [{"role": "assistant", "content": [
            {"type": "thinking", "thinking": "provider-specific"},
            {"type": "text", "text": "answer"},
        ]}]}
        got = ccscience._anthropic_to_openai_request(body, "gpt-test", "api.openai.com")

        self.assertNotIn("reasoning_content", got["messages"][0])

    def test_deepseek_openai_request_preserves_reasoning_and_thinking(self):
        body = {"thinking": {"type": "disabled"}, "messages": [
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "deep reasoning"},
                {"type": "text", "text": "answer"},
            ]},
            {"role": "user", "content": [{"type": "text", "text": "continue"}]},
        ]}
        got = ccscience._anthropic_to_openai_request(body, "deepseek-v4-pro", "api.deepseek.com")

        self.assertEqual(got["messages"][0]["reasoning_content"], "deep reasoning")
        self.assertEqual(got["thinking"], {"type": "disabled"})

    def test_deepseek_openai_request_maps_adaptive_thinking_to_enabled(self):
        got = ccscience._anthropic_to_openai_request(
            {"thinking": {"type": "adaptive", "reasoning_effort": "max"}, "messages": []},
            "deepseek-v4-pro",
            "api.deepseek.com",
        )

        self.assertEqual(got["thinking"], {"type": "enabled", "reasoning_effort": "max"})

    def test_minimax_openai_request_enables_reasoning_split_and_preserves_thinking(self):
        body = {"thinking": {"type": "adaptive"}, "messages": [
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "minimax thought"},
                {"type": "text", "text": "answer"},
            ]},
            {"role": "user", "content": [{"type": "text", "text": "continue"}]},
        ]}
        got = ccscience._anthropic_to_openai_request(body, "MiniMax-M3", "api.minimax.io")

        self.assertTrue(got["reasoning_split"])
        self.assertEqual(got["thinking"], {"type": "adaptive"})
        self.assertEqual(got["messages"][0]["reasoning_content"], "minimax thought")
        self.assertEqual(got["messages"][0]["reasoning_details"], [
            {"type": "text", "text": "minimax thought"},
        ])

    def test_kimi_request_forwards_only_supported_thinking_modes(self):
        enabled = ccscience._anthropic_to_openai_request(
            {"thinking": {"type": "enabled", "keep": "all"}, "messages": []},
            "kimi-k2.6",
            "api.moonshot.ai",
        )
        disabled = ccscience._anthropic_to_openai_request(
            {"thinking": {"type": "disabled"}, "messages": []},
            "kimi-k2.6",
            "api.moonshot.ai",
        )
        always_on = ccscience._anthropic_to_openai_request(
            {"thinking": {"type": "disabled"}, "messages": []},
            "kimi-k2.7-code",
            "api.moonshot.ai",
        )

        self.assertEqual(enabled["thinking"], {"type": "enabled", "keep": "all"})
        self.assertEqual(disabled["thinking"], {"type": "disabled"})
        self.assertNotIn("thinking", always_on)

    def test_kimi_request_disables_thinking_for_forced_tool_choice(self):
        got = ccscience._anthropic_to_openai_request(
            {"messages": [], "thinking": {"type": "enabled"},
             "tools": [{"name": "lookup", "input_schema": {"type": "object"}}],
             "tool_choice": {"type": "tool", "name": "lookup"}},
            "kimi-k2.6",
            "api.moonshot.ai",
        )

        self.assertEqual(got["tool_choice"], {"type": "function", "function": {"name": "lookup"}})
        self.assertEqual(got["thinking"], {"type": "disabled"})

    def test_kimi_always_thinking_model_downgrades_forced_tool_choice_to_auto(self):
        got = ccscience._anthropic_to_openai_request(
            {"messages": [], "thinking": {"type": "disabled"},
             "tools": [{"name": "lookup", "input_schema": {"type": "object"}}],
             "tool_choice": {"type": "tool", "name": "lookup"}},
            "kimi-k2.7-code",
            "api.moonshot.ai",
        )

        self.assertEqual(got["tool_choice"], "auto")
        self.assertNotIn("thinking", got)

    def test_kimi_request_strips_sampling_parameters_that_k2_rejects(self):
        got = ccscience._anthropic_to_openai_request(
            {"messages": [], "temperature": 0.2, "top_p": 0.8, "stream": True},
            "kimi-k2.6",
            "api.moonshot.ai",
        )

        self.assertNotIn("temperature", got)
        self.assertNotIn("top_p", got)
        self.assertTrue(got["stream"])

    def test_non_kimi_openai_provider_keeps_sampling_parameters(self):
        got = ccscience._anthropic_to_openai_request(
            {"messages": [], "temperature": 0.2, "top_p": 0.8},
            "gpt-test",
            "api.openai.com",
        )

        self.assertEqual(got["temperature"], 0.2)
        self.assertEqual(got["top_p"], 0.8)

    def test_estimate_anthropic_input_tokens_counts_request_shape(self):
        body = {
            "model": "claude-opus-4-8",
            "system": [{"type": "text", "text": "rules"}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello world"}]}],
            "tools": [{"name": "lookup", "input_schema": {"type": "object"}}],
        }
        self.assertGreater(ccscience.estimate_anthropic_input_tokens(body), 1)

    def test_openai_response_to_anthropic_message(self):
        blob = json.dumps({
            "id": "chatcmpl_1",
            "model": "kimi-k2",
            "choices": [{"message": {"role": "assistant", "reasoning_content": "think", "content": "hello"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        }).encode()
        got = json.loads(ccscience._openai_to_anthropic_response(blob, "claude-opus-4-8"))
        self.assertEqual(got["type"], "message")
        self.assertEqual(got["model"], "kimi-k2")
        self.assertEqual(got["content"], [
            {"type": "thinking", "thinking": "think", "signature": ""},
            {"type": "text", "text": "hello"},
        ])
        self.assertEqual(got["stop_reason"], "end_turn")
        self.assertEqual(got["usage"], {"input_tokens": 7, "output_tokens": 3})

    def test_iter_openai_sse_payloads_accepts_crlf(self):
        class Stream:
            def __init__(self):
                self.parts = [
                    b'data: {"model":"kimi-k2","choices":[]}\r\n\r\n',
                    b'data: [DONE]\r\n\r\n',
                    b'',
                ]

            def read(self, _n):
                return self.parts.pop(0)

        self.assertEqual(
            list(ccscience._iter_openai_sse_payloads(Stream())),
            [b'{"model":"kimi-k2","choices":[]}', b"[DONE]"],
        )

    def test_openai_stream_reasoning_delta_diffs_cumulative_details(self):
        previous = ""
        got, previous = ccscience._openai_stream_reasoning_delta(
            {"reasoning_details": [{"type": "text", "text": "think"}]},
            previous,
        )
        self.assertEqual(got, "think")
        self.assertEqual(previous, "think")

        got, previous = ccscience._openai_stream_reasoning_delta(
            {"reasoning_details": [{"type": "text", "text": "thinking"}]},
            previous,
        )
        self.assertEqual(got, "ing")
        self.assertEqual(previous, "thinking")

        got, previous = ccscience._openai_stream_reasoning_delta(
            {"reasoning_content": " next"},
            previous,
        )
        self.assertEqual(got, " next")
        self.assertEqual(previous, "thinking")

    def test_forwarder_openai_provider_matrix(self):
        base_body = {
            "model": "claude-opus-4-8",
            "max_tokens": 16,
            "stream": False,
            "temperature": 0.2,
            "top_p": 0.8,
            "thinking": {"type": "enabled", "reasoning_effort": "max"},
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "prior"},
                    {"type": "text", "text": "previous answer"},
                ]},
                {"role": "user", "content": [{"type": "text", "text": "say ok"}]},
            ],
            "tools": [{"name": "lookup", "description": "look up data",
                       "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}],
            "tool_choice": {"type": "tool", "name": "lookup"},
        }
        cases = [
            {
                "name": "kimi",
                "base": "https://api.moonshot.ai/v1",
                "model": "kimi-k2.6",
                "url": "https://api.moonshot.ai/v1/chat/completions",
                "expect": lambda body: (
                    self.assertEqual(body["model"], "kimi-k2.6"),
                    self.assertNotIn("temperature", body),
                    self.assertNotIn("top_p", body),
                    self.assertEqual(body["thinking"], {"type": "disabled"}),
                    self.assertEqual(body["tool_choice"], {"type": "function", "function": {"name": "lookup"}}),
                    self.assertEqual(body["messages"][0]["reasoning_content"], "prior"),
                ),
            },
            {
                "name": "kimi-code",
                "base": "https://api.moonshot.ai/v1",
                "model": "kimi-k2.7-code",
                "url": "https://api.moonshot.ai/v1/chat/completions",
                "expect": lambda body: (
                    self.assertEqual(body["model"], "kimi-k2.7-code"),
                    self.assertEqual(body["tool_choice"], "auto"),
                    self.assertNotIn("thinking", body),
                    self.assertNotIn("temperature", body),
                    self.assertNotIn("top_p", body),
                ),
            },
            {
                "name": "deepseek",
                "base": "https://api.deepseek.com",
                "model": "deepseek-v4-pro",
                "url": "https://api.deepseek.com/v1/chat/completions",
                "expect": lambda body: (
                    self.assertEqual(body["model"], "deepseek-v4-pro"),
                    self.assertEqual(body["thinking"], {"type": "disabled"}),
                    self.assertEqual(body["messages"][0]["reasoning_content"], "prior"),
                    self.assertEqual(body["temperature"], 0.2),
                ),
            },
            {
                "name": "minimax-openai",
                "base": "https://api.minimax.io/v1",
                "model": "MiniMax-M3",
                "url": "https://api.minimax.io/v1/chat/completions",
                "expect": lambda body: (
                    self.assertEqual(body["model"], "MiniMax-M3"),
                    self.assertTrue(body["reasoning_split"]),
                    self.assertEqual(body["thinking"], {"type": "adaptive"}),
                    self.assertEqual(body["messages"][0]["reasoning_details"], [{"type": "text", "text": "prior"}]),
                ),
            },
            {
                "name": "glm",
                "base": "https://open.bigmodel.cn/api/paas/v4",
                "model": "glm-4.5",
                "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                "expect": lambda body: (
                    self.assertEqual(body["model"], "glm-4.5"),
                    self.assertNotIn("thinking", body),
                    self.assertNotIn("reasoning_split", body),
                    self.assertEqual(body["temperature"], 0.2),
                ),
            },
            {
                "name": "qwen",
                "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "qwen3-coder-plus",
                "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "expect": lambda body: self.assertEqual(body["model"], "qwen3-coder-plus"),
            },
            {
                "name": "openrouter",
                "base": "https://openrouter.ai/api/v1",
                "model": "anthropic/claude-sonnet-4.5",
                "url": "https://openrouter.ai/api/v1/chat/completions",
                "expect": lambda body: self.assertEqual(body["model"], "anthropic/claude-sonnet-4.5"),
            },
            {
                "name": "siliconflow",
                "base": "https://api.siliconflow.cn/v1",
                "model": "deepseek-ai/DeepSeek-V3.2",
                "url": "https://api.siliconflow.cn/v1/chat/completions",
                "expect": lambda body: self.assertEqual(body["model"], "deepseek-ai/DeepSeek-V3.2"),
            },
        ]
        for case in cases:
            with self.subTest(case["name"]):
                captured, got = self._forwarder_json_roundtrip(
                    {"base_url": case["base"], "key": "sk-test", "source": "test", "model": case["model"]},
                    dict(base_body),
                    {
                        "id": "chatcmpl_1",
                        "model": case["model"],
                        "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 1},
                    },
                )

                self.assertEqual(captured["url"], case["url"])
                self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-test")
                case["expect"](captured["body"])
                self.assertEqual(got["model"], case["model"])
                self.assertEqual(got["content"], [{"type": "text", "text": "OK"}])

    def test_forwarder_anthropic_provider_matrix(self):
        body = {
            "model": "claude-opus-4-8",
            "max_tokens": 16,
            "stream": False,
            "thinking": {"type": "auto"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "say ok", "cache_control": {"type": "ephemeral"}},
            ]}],
            "tools": [{"name": "lookup", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                       "cache_control": {"type": "ephemeral"}}],
        }
        cases = [
            ("deepseek-anthropic", "https://api.deepseek.com/anthropic", "deepseek-v4-pro",
             "https://api.deepseek.com/anthropic/v1/messages"),
            ("deepseek-v1", "https://api.deepseek.com/anthropic/v1", "deepseek-v4-pro",
             "https://api.deepseek.com/anthropic/v1/messages"),
            ("minimax-intl", "https://api.minimax.io/anthropic", "MiniMax-M3",
             "https://api.minimax.io/anthropic/v1/messages"),
            ("minimax-china-full", "https://api.minimaxi.com/anthropic/v1/messages", "MiniMax-M3",
             "https://api.minimaxi.com/anthropic/v1/messages"),
        ]
        for name, base, model, expected_url in cases:
            with self.subTest(name):
                captured, got = self._forwarder_json_roundtrip(
                    {"base_url": base, "key": "sk-test", "source": "test", "model": model},
                    json.loads(json.dumps(body)),
                    {
                        "type": "message",
                        "model": model,
                        "content": [{"type": "text", "text": "OK"}],
                    },
                )

                self.assertEqual(captured["url"], expected_url)
                self.assertEqual(captured["headers"]["X-api-key"], "sk-test")
                self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-test")
                self.assertEqual(captured["body"]["model"], model)
                self.assertEqual(captured["body"]["thinking"], {"type": "adaptive"})
                self.assertNotIn("cache_control", captured["body"]["tools"][0])
                self.assertEqual(captured["body"]["tools"][0]["input_schema"], {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                })
                self.assertNotIn("cache_control", captured["body"]["messages"][0]["content"][0])
                self.assertEqual(got["content"], [{"type": "text", "text": "OK"}])

    def test_forwarder_drops_schema_less_tools_before_anthropic_provider(self):
        captured, got = self._forwarder_json_roundtrip(
            {"base_url": "https://api.minimaxi.com/anthropic", "key": "sk-test",
             "source": "test", "model": "MiniMax-M3"},
            {
                "model": "claude-opus-4-8",
                "stream": False,
                "messages": [{"role": "user", "content": [{"type": "text", "text": "list files"}]}],
                "tools": [
                    {"name": "web_search"},
                    {"name": "bash", "input_schema": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"],
                    }},
                ],
            },
            {
                "type": "message",
                "model": "MiniMax-M3",
                "content": [{"type": "text", "text": "OK"}],
            },
        )

        self.assertEqual(captured["url"], "https://api.minimaxi.com/anthropic/v1/messages")
        self.assertEqual([tool["name"] for tool in captured["body"]["tools"]], ["bash"])
        self.assertEqual(got["content"], [{"type": "text", "text": "OK"}])

    def test_forwarder_post_adapts_openai_provider(self):
        captured = {}

        class Upstream:
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "id": "chatcmpl_1",
                    "model": "kimi-k2",
                    "choices": [{"message": {"role": "assistant", "content": "51"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 1},
                }).encode()

            def getcode(self):
                return 200

        def fake_open(req, timeout=300):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode())
            captured["timeout"] = timeout
            return Upstream()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(ccscience, "thirdparty_provider_details",
                                   return_value={"base_url": "https://api.moonshot.ai/v1",
                                                 "key": "sk-test", "source": "test", "model": "kimi-k2"}):
                with mock.patch.object(ccscience, "_provider_model_for_request", return_value="kimi-k2"):
                    with mock.patch.object(ccscience, "_open_upstream", side_effect=fake_open):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{server.server_port}/v1/messages",
                            data=json.dumps({
                                "model": "claude-opus-4-8",
                                "max_tokens": 8,
                                "stream": False,
                                "messages": [{"role": "user", "content": [{"type": "text", "text": "17*3"}]}],
                            }).encode(),
                            method="POST",
                            headers={"Content-Type": "application/json"},
                        )
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            got = json.loads(resp.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(captured["url"], "https://api.moonshot.ai/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(captured["body"]["model"], "kimi-k2")
        self.assertEqual(captured["body"]["messages"][0]["content"], "17*3")
        self.assertEqual(got["model"], "kimi-k2")
        self.assertEqual(got["content"], [{"type": "text", "text": "51"}])

    def test_forwarder_post_normalizes_anthropic_base_with_v1_suffix(self):
        captured = {}

        class Upstream:
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "type": "message",
                    "model": "deepseek-v4-pro",
                    "content": [{"type": "text", "text": "OK"}],
                }).encode()

            def getcode(self):
                return 200

        def fake_open(req, timeout=300):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode())
            return Upstream()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self._isolated_forwarder_settings():
                with mock.patch.object(ccscience, "thirdparty_provider_details",
                                       return_value={"base_url": "https://api.deepseek.com/anthropic/v1",
                                                     "key": "sk-test", "source": "test",
                                                     "model": "deepseek-v4-pro"}):
                    with mock.patch.object(ccscience, "_open_upstream", side_effect=fake_open):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{server.server_port}/v1/messages",
                            data=json.dumps({
                                "model": "claude-opus-4-8",
                                "max_tokens": 8,
                                "stream": False,
                                "messages": [{"role": "user", "content": [{"type": "text", "text": "say ok"}]}],
                            }).encode(),
                            method="POST",
                            headers={"Content-Type": "application/json"},
                        )
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            got = json.loads(resp.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(captured["url"], "https://api.deepseek.com/anthropic/v1/messages")
        self.assertEqual(captured["headers"]["X-api-key"], "sk-test")
        self.assertEqual(captured["body"]["model"], "deepseek-v4-pro")
        self.assertEqual(got["content"], [{"type": "text", "text": "OK"}])

    def test_forwarder_post_adapts_deepseek_openai_reasoning(self):
        captured = {}

        class Upstream:
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "id": "chatcmpl_1",
                    "model": "deepseek-v4-pro",
                    "choices": [{"message": {"role": "assistant",
                                              "reasoning_content": "think",
                                              "content": "OK"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                }).encode()

            def getcode(self):
                return 200

        def fake_open(req, timeout=300):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode())
            return Upstream()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(ccscience, "thirdparty_provider_details",
                                   return_value={"base_url": "https://api.deepseek.com",
                                                 "key": "sk-test", "source": "test",
                                                 "model": "deepseek-v4-pro"}):
                with mock.patch.object(ccscience, "_open_upstream", side_effect=fake_open):
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/messages",
                        data=json.dumps({
                            "model": "claude-opus-4-8",
                            "max_tokens": 8,
                            "stream": False,
                            "thinking": {"type": "adaptive"},
                            "messages": [
                                {"role": "assistant", "content": [
                                    {"type": "thinking", "thinking": "previous"},
                                    {"type": "text", "text": "answer"},
                                ]},
                                {"role": "user", "content": [{"type": "text", "text": "say ok"}]},
                            ],
                        }).encode(),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        got = json.loads(resp.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(captured["url"], "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(captured["body"]["thinking"], {"type": "enabled"})
        self.assertEqual(captured["body"]["messages"][0]["reasoning_content"], "previous")
        self.assertEqual(got["content"][0]["type"], "thinking")
        self.assertEqual(got["content"][1], {"type": "text", "text": "OK"})

    def test_forwarder_post_adapts_minimax_openai_reasoning_split(self):
        captured = {}

        class Upstream:
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "id": "chatcmpl_1",
                    "model": "MiniMax-M3",
                    "choices": [{"message": {"role": "assistant",
                                              "reasoning_details": [{"type": "text", "text": "think"}],
                                              "content": "OK"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                }).encode()

            def getcode(self):
                return 200

        def fake_open(req, timeout=300):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode())
            return Upstream()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(ccscience, "thirdparty_provider_details",
                                   return_value={"base_url": "https://api.minimax.io/v1",
                                                 "key": "sk-test", "source": "test",
                                                 "model": "MiniMax-M3"}):
                with mock.patch.object(ccscience, "_open_upstream", side_effect=fake_open):
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/messages",
                        data=json.dumps({
                            "model": "claude-opus-4-8",
                            "max_tokens": 8,
                            "stream": False,
                            "thinking": {"type": "adaptive"},
                            "messages": [
                                {"role": "assistant", "content": [
                                    {"type": "thinking", "thinking": "previous"},
                                    {"type": "text", "text": "answer"},
                                ]},
                                {"role": "user", "content": [{"type": "text", "text": "say ok"}]},
                            ],
                        }).encode(),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        got = json.loads(resp.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(captured["url"], "https://api.minimax.io/v1/chat/completions")
        self.assertTrue(captured["body"]["reasoning_split"])
        self.assertEqual(captured["body"]["thinking"], {"type": "adaptive"})
        self.assertEqual(captured["body"]["messages"][0]["reasoning_details"], [
            {"type": "text", "text": "previous"},
        ])
        self.assertEqual(got["content"][0]["type"], "thinking")
        self.assertEqual(got["content"][1], {"type": "text", "text": "OK"})

    def test_forwarder_handles_count_tokens_locally(self):
        calls = []

        def fake_open(*_args, **_kwargs):
            calls.append(True)
            raise AssertionError("count_tokens should not reach upstream")

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(ccscience, "thirdparty_provider_details",
                                   return_value={"base_url": "https://api.moonshot.ai/v1",
                                                 "key": "sk-test", "source": "test", "model": "kimi-k2"}):
                with mock.patch.object(ccscience, "_open_upstream", side_effect=fake_open):
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/messages/count_tokens",
                        data=json.dumps({
                            "model": "claude-opus-4-8",
                            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
                        }).encode(),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        got = json.loads(resp.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertGreater(got["input_tokens"], 0)
        self.assertEqual(calls, [])

    def test_forwarder_post_adapts_openai_stream_with_reasoning(self):
        captured = {}

        class Upstream:
            headers = {"Content-Type": "text/event-stream"}

            def __init__(self):
                self.parts = [
                    b'data: {"id":"c1","model":"kimi-k2","choices":[{"delta":{"reasoning_content":"think"},"finish_reason":null}]}\n\n',
                    b'data: {"id":"c1","model":"kimi-k2","choices":[{"delta":{"content":"OK"},"finish_reason":null}]}\n\n',
                    b'data: {"id":"c1","model":"kimi-k2","choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"completion_tokens":1}}\n\n',
                    b'data: [DONE]\n\n',
                    b'',
                ]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _n):
                return self.parts.pop(0)

        def fake_open(req, timeout=300):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode())
            return Upstream()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(ccscience, "thirdparty_provider_details",
                                   return_value={"base_url": "https://api.moonshot.ai/v1",
                                                 "key": "sk-test", "source": "test", "model": "kimi-k2"}):
                with mock.patch.object(ccscience, "_open_upstream", side_effect=fake_open):
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/messages",
                        data=json.dumps({
                            "model": "claude-opus-4-8",
                            "max_tokens": 8,
                            "stream": True,
                            "thinking": {"type": "adaptive"},
                            "messages": [{"role": "user", "content": [{"type": "text", "text": "say ok"}]}],
                        }).encode(),
                        method="POST",
                        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        got = resp.read().decode()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(captured["url"], "https://api.moonshot.ai/v1/chat/completions")
        self.assertTrue(captured["body"]["stream"])
        self.assertNotIn("thinking", captured["body"])
        self.assertIn('"type": "thinking_delta", "thinking": "think"', got)
        self.assertIn('"type": "text_delta", "text": "OK"', got)
        self.assertIn('event: message_stop', got)

    def test_forwarder_post_diffs_minimax_stream_reasoning_details(self):
        captured = {}

        class Upstream:
            headers = {"Content-Type": "text/event-stream"}

            def __init__(self):
                self.parts = [
                    ("data: " + json.dumps({
                        "id": "c1",
                        "model": "MiniMax-M3",
                        "choices": [{"delta": {"reasoning_details": [
                            {"type": "text", "text": "think"},
                        ]}, "finish_reason": None}],
                    }) + "\n\n").encode(),
                    ("data: " + json.dumps({
                        "id": "c1",
                        "model": "MiniMax-M3",
                        "choices": [{"delta": {"reasoning_details": [
                            {"type": "text", "text": "thinking"},
                        ]}, "finish_reason": None}],
                    }) + "\n\n").encode(),
                    b'data: {"id":"c1","model":"MiniMax-M3","choices":[{"delta":{"content":"OK"},"finish_reason":null}]}\n\n',
                    b'data: {"id":"c1","model":"MiniMax-M3","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                    b'data: [DONE]\n\n',
                    b'',
                ]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _n):
                return self.parts.pop(0)

        def fake_open(req, timeout=300):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode())
            return Upstream()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(ccscience, "thirdparty_provider_details",
                                   return_value={"base_url": "https://api.minimax.io/v1",
                                                 "key": "sk-test", "source": "test",
                                                 "model": "MiniMax-M3"}):
                with mock.patch.object(ccscience, "_open_upstream", side_effect=fake_open):
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/messages",
                        data=json.dumps({
                            "model": "claude-opus-4-8",
                            "max_tokens": 8,
                            "stream": True,
                            "thinking": {"type": "adaptive"},
                            "messages": [{"role": "user", "content": [{"type": "text", "text": "say ok"}]}],
                        }).encode(),
                        method="POST",
                        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        got = resp.read().decode()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(captured["url"], "https://api.minimax.io/v1/chat/completions")
        self.assertTrue(captured["body"]["reasoning_split"])
        self.assertEqual(captured["body"]["thinking"], {"type": "adaptive"})
        self.assertIn('"type": "thinking_delta", "thinking": "think"', got)
        self.assertIn('"type": "thinking_delta", "thinking": "ing"', got)
        self.assertNotIn('"type": "thinking_delta", "thinking": "thinking"', got)
        self.assertIn('"type": "text_delta", "text": "OK"', got)

    def test_forwarder_post_adapts_openai_stream_tool_call(self):
        class Upstream:
            headers = {"Content-Type": "text/event-stream"}

            def __init__(self):
                self.parts = [
                    b'data: {"id":"c1","model":"kimi-k2","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"lookup","arguments":"{\\"q\\""}}]},"finish_reason":null}]}\n\n',
                    b'data: {"id":"c1","model":"kimi-k2","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":":\\"x\\"}"}}]},"finish_reason":null}]}\n\n',
                    b'data: {"id":"c1","model":"kimi-k2","choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
                    b'data: [DONE]\n\n',
                    b'',
                ]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _n):
                return self.parts.pop(0)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ccscience.ThirdpartyForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(ccscience, "thirdparty_provider_details",
                                   return_value={"base_url": "https://api.moonshot.ai/v1",
                                                 "key": "sk-test", "source": "test", "model": "kimi-k2"}):
                with mock.patch.object(ccscience, "_open_upstream", return_value=Upstream()):
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/messages",
                        data=json.dumps({
                            "model": "claude-opus-4-8",
                            "max_tokens": 8,
                            "stream": True,
                            "messages": [{"role": "user", "content": [{"type": "text", "text": "lookup"}]}],
                            "tools": [{"name": "lookup", "input_schema": {"type": "object"}}],
                        }).encode(),
                        method="POST",
                        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        got = resp.read().decode()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertIn('"type": "tool_use"', got)
        self.assertIn('"id": "call_1"', got)
        self.assertIn('"name": "lookup"', got)
        self.assertIn('"type": "input_json_delta", "partial_json": "{\\"q\\":\\"x\\"}"', got)
        self.assertIn('"stop_reason": "tool_use"', got)


if __name__ == "__main__":
    unittest.main()
