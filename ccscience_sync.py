#!/usr/bin/env python3
"""Sync Claude Code/ccswitch model settings into Claude Science.

The tool is intentionally small and stdlib-only. It reads
~/.claude/settings.json, exposes the mapped model on a localhost endpoint,
and injects a tiny bootstrap script into Claude Science's web entrypoint so
new Claude Science requests carry the same model.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as _dt
import glob
import hashlib
import hmac
import http.client
import http.server
import io
import json
import locale
import os
import pathlib
import plistlib
import re
import secrets
import shutil
import signal
import ssl
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from typing import Any


APP_NAME = "ccscience-sync"
VERSION = "0.5.1"
DEFAULT_PORT = 19783
THIRDPARTY_FWD_PORT = 19784  # our own hidden normalizing forwarder (no CSSwitch)
THIRDPARTY_FWD_REVISION = 7
MACOS_LABEL = "io.github.ccscience-sync.helper"
MARKER_START = "<!-- ccscience-sync:start -->"
MARKER_END = "<!-- ccscience-sync:end -->"

# --- Third-party no-login (virtual login) mode ---
# Runs an ISOLATED, local-only Claude Science instance whose "login" is a
# self-generated virtual identity (never touches ~/.claude-science or the real
# account) and whose inference is routed entirely to the CSSwitch local proxy.
SANDBOX_PORT_DEFAULT = 8990
REAL_SCIENCE_PORT = 8765  # the real instance's default port — hard guardrail: never touch it
VIRTUAL_EMAIL = "virtual@localhost.invalid"
SANDBOX_RUNTIME_ASSETS = ("bin", "conda", "runtime", "seed-assets")
# encryption.key stores these newline-separated KEY=VALUE entries (operon format).
OAUTH_KEY_NAMES = (
    "ANTHROPIC_API_KEY_ENCRYPTION_KEY",
    "OAUTH_ENCRYPTION_KEY",
    "JWT_SIGNING_SECRET",
    "USER_SECRET_ENCRYPTION_KEY",
)


def home() -> pathlib.Path:
    return pathlib.Path.home()


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return os.name == "nt"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(name: str) -> pathlib.Path | None:
    """Locate a bundled data file both when running from source and when frozen.

    PyInstaller unpacks --add-data files into sys._MEIPASS; from source they live
    under ``assets/`` next to this module. Returns None if the file is absent so
    callers can degrade gracefully (e.g. skip setting a window icon).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = []
    if meipass:
        candidates.append(pathlib.Path(meipass) / name)
    candidates.append(pathlib.Path(__file__).resolve().parent / "assets" / name)
    for path in candidates:
        if path.is_file():
            return path
    return None


def locale_candidates() -> list[str]:
    candidates: list[str] = []
    for name in ("CCSCIENCE_SYNC_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if value:
            candidates.append(value)

    for category in (getattr(locale, "LC_MESSAGES", None), locale.LC_CTYPE):
        if category is None:
            continue
        with contextlib.suppress(Exception):
            value = locale.getlocale(category)[0]
            if value:
                candidates.append(value)

    with contextlib.suppress(Exception):
        value = locale.getlocale()[0]
        if value:
            candidates.append(value)

    if is_macos():
        with contextlib.suppress(Exception):
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleLanguages"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=1,
            )
            if result.stdout:
                for line in result.stdout.splitlines():
                    value = line.strip().strip('",')
                    if value and value not in ("(", ")"):
                        candidates.append(value)
                        break

    return candidates


def detect_language(value: str | None = None) -> str:
    candidates = [value] if value is not None else locale_candidates()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = candidate.strip().lower().replace("_", "-")
        if normalized.startswith(("zh", "chinese")) or any(
            token in normalized for token in ("zh-", "zh.", "hans", "hant", "simplified chinese", "traditional chinese")
        ):
            return "zh"
    return "en"


TEXT = {
    "en": {
        "subtitle": "Install once. New Claude Science sessions will use the latest model selected in ccswitch / Claude Code.",
        "ready": "Ready",
        "install": "Install / Update",
        "install_primary": "①  Install / Update",
        "status": "Check Status",
        "open_science": "Open Claude Science",
        "uninstall": "Uninstall",
        "quit": "Quit",
        "install_action": "Install",
        "status_action": "Status",
        "open_science_action": "Open Claude Science",
        "uninstall_action": "Uninstall",
        "finished": "{action} finished",
        "failed": "{action} failed",
        "installed_message": "Installed. You do not need to reinstall when switching models.",
        "no_output": "(no output)",
        "initial": (
            "Welcome! Three steps to get started:\n\n"
            "1. Click \"①  Install / Update\" once. That is the whole setup.\n"
            "2. Click \"Open Claude Science\" to use it. New sessions follow the model you pick "
            "in ccswitch / Claude Code.\n"
            "3. No Claude account? Pick a third-party model in CC.Switch, then click "
            "\"Third-Party (No Login)\".\n\n"
            "You do not need to reinstall after switching models."
        ),
        "gui_error": "Could not start GUI: {error}",
        "gui_fallback": "Run 'ccscience-sync install' from a terminal instead.",
        "opened_science": "Opened a fresh Claude Science link:\n{url}\n\nIf Claude Science asks for your Claude account, please sign in there. ccscience-sync cannot bypass account login.",
        "bridge_active": "CSSwitch bridge: active ({profile}, {model})",
        "bridge_inactive": "CSSwitch bridge: not active. Claude Science will use its normal connection.",
        "science_cli_missing": "Could not find the claude-science command. Open Claude Science from its own app, or add claude-science to PATH.",
        "science_url_missing": "Could not get a Claude Science URL from the claude-science command.",
        "open_thirdparty": "Third-Party (No Login)",
        "open_thirdparty_action": "Third-Party (No Login)",
        "thirdparty_needs_source": (
            "Third-party no-login mode needs a third-party model source first.\n"
            "In CC.Switch, switch the active profile to a third-party model (e.g. DeepSeek) — "
            "it writes the provider's base URL and API key — then click Third-Party (No Login) again."
        ),
        "opened_thirdparty": (
            "Opened an isolated, no-login Claude Science:\n{url}\n\n"
            "This runs a separate local instance with a locally generated virtual login "
            "({email}). It never touches your real Claude account or ~/.claude-science, and all "
            "inference goes through your own third-party API ({model})."
        ),
        "thirdparty_launch_failed": "Could not start the isolated Claude Science sandbox: {detail}",
    },
    "zh": {
        "subtitle": "安装一次即可。Claude Science 新会话会自动使用 ccswitch / Claude Code 中最新选择的模型。",
        "ready": "就绪",
        "install": "安装 / 更新",
        "install_primary": "①  一键安装 / 更新",
        "status": "检查状态",
        "open_science": "打开 Claude Science",
        "uninstall": "卸载",
        "quit": "退出",
        "install_action": "安装",
        "status_action": "状态检查",
        "open_science_action": "打开 Claude Science",
        "uninstall_action": "卸载",
        "finished": "{action}完成",
        "failed": "{action}失败",
        "installed_message": "已安装。以后切换模型不需要重新安装。",
        "no_output": "（没有输出）",
        "initial": (
            "欢迎！三步即可开始：\n\n"
            "1. 先点一次「①  一键安装 / 更新」，安装就完成了。\n"
            "2. 点「打开 Claude Science」开始使用。新会话会自动用你在 ccswitch / Claude Code 里选的模型。\n"
            "3. 没有 Claude 账号？在 CC.Switch 里选一个第三方模型，再点「第三方免登录」。\n\n"
            "以后切换模型不用重新安装。"
        ),
        "gui_error": "无法启动图形界面：{error}",
        "gui_fallback": "请改用终端运行 ccscience-sync install。",
        "opened_science": "已打开一个新的 Claude Science 一次性链接：\n{url}\n\n如果 Claude Science 要求登录 Claude 账号，请在 Claude Science 中正常登录。ccscience-sync 不能绕过账号登录。",
        "bridge_active": "CSSwitch 桥接：已启用（{profile}，{model}）",
        "bridge_inactive": "CSSwitch 桥接：未启用。本次会按 Claude Science 默认连接启动。",
        "science_cli_missing": "找不到 claude-science 命令。请从 Claude Science 自己的 App 打开，或把 claude-science 加入 PATH。",
        "science_url_missing": "无法从 claude-science 命令获取 Claude Science 链接。",
        "open_thirdparty": "第三方免登录",
        "open_thirdparty_action": "第三方免登录",
        "thirdparty_needs_source": (
            "第三方免登录需要先有一个第三方模型来源。\n"
            "请在 CC.Switch 里把当前档切换到一个第三方模型（如 DeepSeek），"
            "它会写好接口地址和 API Key，然后再点「第三方免登录」。"
        ),
        "opened_thirdparty": (
            "已打开一个隔离的、免登录的 Claude Science：\n{url}\n\n"
            "这是一个独立的本地实例，使用本机生成的虚拟登录（{email}），"
            "绝不触碰你真实的 Claude 账号或 ~/.claude-science；全部推理都经由你自己的第三方 API（{model}）。"
        ),
        "thirdparty_launch_failed": "无法启动隔离的 Claude Science 沙箱：{detail}",
    },
}


def tr(lang: str, key: str, **kwargs: Any) -> str:
    template = TEXT.get(lang, TEXT["en"]).get(key, TEXT["en"][key])
    return template.format(**kwargs)


def claude_settings_path() -> pathlib.Path:
    return home() / ".claude" / "settings.json"


def _env_path(name: str) -> pathlib.Path | None:
    value = os.environ.get(name)
    return pathlib.Path(value) if value else None


def _unique_paths(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    seen: set[str] = set()
    result: list[pathlib.Path] = []
    for path in paths:
        key = str(path.expanduser()).lower() if is_windows() else str(path.expanduser())
        if key not in seen:
            seen.add(key)
            result.append(path.expanduser())
    return result


def science_data_dirs() -> list[pathlib.Path]:
    override = _env_path("CLAUDE_SCIENCE_DATA_DIR")
    if override:
        return [override]

    candidates = [home() / ".claude-science"]
    if is_macos():
        candidates.extend(
            [
                home() / "Library" / "Application Support" / "Claude Science",
                home() / "Library" / "Application Support" / "com.anthropic.operon",
            ]
        )
    elif is_windows():
        appdata = _env_path("APPDATA")
        localappdata = _env_path("LOCALAPPDATA")
        for root in (localappdata, appdata):
            if root:
                candidates.extend(
                    [
                        root / "Claude Science",
                        root / "claude-science",
                        root / "Anthropic" / "Claude Science",
                        root / "Anthropic" / "claude-science",
                    ]
                )
    return _unique_paths(candidates)


def science_data_dir() -> pathlib.Path:
    return science_data_dirs()[0]


def user_config_path() -> pathlib.Path:
    return home() / ".ccscience-sync.json"


def csswitch_config_path() -> pathlib.Path:
    return home() / ".csswitch" / "config.json"


def launch_agent_path(label: str = MACOS_LABEL) -> pathlib.Path:
    return home() / "Library" / "LaunchAgents" / f"{label}.plist"


def app_data_dir() -> pathlib.Path:
    if is_windows():
        base = _env_path("LOCALAPPDATA") or (home() / "AppData" / "Local")
        return base / APP_NAME
    if is_macos():
        return home() / "Library" / "Application Support" / APP_NAME
    base = _env_path("XDG_DATA_HOME") or (home() / ".local" / "share")
    return base / APP_NAME


def windows_startup_dir() -> pathlib.Path:
    appdata = _env_path("APPDATA") or (home() / "AppData" / "Roaming")
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def windows_startup_path() -> pathlib.Path:
    return windows_startup_dir() / f"{APP_NAME}.vbs"


def log_path() -> pathlib.Path:
    if is_windows():
        return app_data_dir() / f"{APP_NAME}.log"
    if is_macos():
        return home() / "Library" / "Logs" / f"{APP_NAME}.log"
    base = _env_path("XDG_STATE_HOME") or (home() / ".local" / "state")
    return base / APP_NAME / f"{APP_NAME}.log"


def current_app_bundle() -> pathlib.Path | None:
    if not is_macos():
        return None
    executable = pathlib.Path(sys.executable).resolve()
    for path in (executable, *executable.parents):
        if path.suffix == ".app":
            return path
    return None


def frozen_install_target() -> pathlib.Path:
    if is_macos():
        bundle = current_app_bundle()
        if bundle:
            return app_data_dir() / f"{APP_NAME}-{VERSION}.app"
    if is_windows():
        return app_data_dir() / f"{APP_NAME}-{VERSION}.exe"
    return app_data_dir() / f"{APP_NAME}-{VERSION}"


def executable_inside_app(app_path: pathlib.Path) -> pathlib.Path:
    return app_path / "Contents" / "MacOS" / pathlib.Path(sys.executable).name


def ensure_frozen_install_target() -> pathlib.Path:
    executable = pathlib.Path(sys.executable).resolve()
    if not is_frozen():
        return executable

    target = frozen_install_target()
    if is_macos() and current_app_bundle():
        source_app = current_app_bundle()
        assert source_app is not None
        target_executable = executable_inside_app(target)
        if source_app.resolve() != target.resolve() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_app, target)
        return target_executable if target_executable.exists() else executable

    if target.resolve() != executable and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(executable, target)
    return target if target.exists() else executable


def claude_science_commands() -> list[pathlib.Path]:
    candidates: list[pathlib.Path] = []
    override = _env_path("CLAUDE_SCIENCE_BIN")
    if override:
        candidates.append(override)

    found = shutil.which("claude-science")
    if found:
        candidates.append(pathlib.Path(found))

    candidates.extend(
        [
            home() / ".local" / "bin" / "claude-science",
            pathlib.Path("/opt/homebrew/bin/claude-science"),
            pathlib.Path("/usr/local/bin/claude-science"),
        ]
    )
    return [path for path in _unique_paths(candidates) if path.exists()]


def fresh_claude_science_url(lang: str = "en", env: dict[str, str] | None = None) -> str:
    commands = claude_science_commands()
    for command in commands:
        result = run([str(command), "url"], env=env)
        output = f"{result.stdout}\n{result.stderr}"
        match = re.search(r"https?://[^\s]+", output)
        if result.returncode == 0 and match:
            return match.group(0)
    if commands:
        raise SystemExit(tr(lang, "science_url_missing"))
    raise SystemExit(tr(lang, "science_cli_missing"))


def open_claude_science(lang: str = "en") -> tuple[str, dict[str, Any]]:
    env, bridge = science_launch_environment()
    if env and env.get("ANTHROPIC_BASE_URL") == thirdparty_forwarder_base_url():
        ensure_thirdparty_forwarder()
    url = fresh_claude_science_url(lang, env=env)
    webbrowser.open(url)
    return url, bridge


def load_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc


def load_user_config() -> dict[str, Any]:
    data = load_json(user_config_path(), {})
    if not isinstance(data, dict):
        raise SystemExit(f"{user_config_path()} must contain a JSON object")
    return data


def load_csswitch_config() -> dict[str, Any]:
    try:
        data = json.loads(csswitch_config_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _profile_identity(profile: dict[str, Any]) -> str:
    for key in ("id", "profile_id", "profileId", "uuid", "name"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _csswitch_profiles(config: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = config.get("profiles")
    if isinstance(profiles, list):
        return [profile for profile in profiles if isinstance(profile, dict)]
    if isinstance(profiles, dict):
        out: list[dict[str, Any]] = []
        for key, value in profiles.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("id", str(key))
                out.append(item)
        return out
    return []


def csswitch_active_profile(config: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("active_profile", "activeProfile", "current_profile", "currentProfile",
                "selected_profile", "selectedProfile"):
        value = config.get(key)
        if isinstance(value, dict):
            return value
    profiles = _csswitch_profiles(config)
    active_id = ""
    for key in ("active_id", "activeId", "active_profile_id", "activeProfileId",
                "current_profile_id", "currentProfileId", "selected_profile_id",
                "selectedProfileId"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            active_id = value.strip()
            break
    if active_id:
        for profile in profiles:
            if _profile_identity(profile) == active_id:
                return profile
    if not active_id and len(profiles) == 1:
        return profiles[0]
    return None


def _int_port(value: Any, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 0 < port < 65536 else default


def csswitch_proxy_url(config: dict[str, Any]) -> str | None:
    secret = str(config.get("secret") or "")
    if not secret:
        return None
    port = _int_port(config.get("proxy_port"), 18991)
    return f"http://127.0.0.1:{port}/{secret}"


def csswitch_proxy_health(config: dict[str, Any]) -> bool:
    url = csswitch_proxy_url(config)
    if not url:
        return False
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=0.6) as res:
            return 200 <= res.status < 300
    except Exception:
        return False


def csswitch_bridge_payload(check_health: bool = True) -> dict[str, Any]:
    config = load_csswitch_config()
    profile = csswitch_active_profile(config)
    mode = str(config.get("mode") or "")
    enabled = mode == "proxy" and profile is not None
    port = _int_port(config.get("proxy_port"), 18991)
    secret = str(config.get("secret") or "")
    model = ""
    if profile:
        model = _profile_model(profile)
    profile_name = ""
    template_id = ""
    if profile:
        profile_name = str(profile.get("name") or profile.get("display_name") or profile.get("displayName") or
                           profile.get("template_id") or profile.get("templateId") or "")
        template_id = str(profile.get("template_id") or profile.get("templateId") or "")
    payload = {
        "enabled": enabled,
        "mode": mode or "missing",
        "profile": profile_name,
        "template_id": template_id,
        "model": model,
        "proxy_port": port,
        "proxy_url": f"http://127.0.0.1:{port}/****" if secret else "",
        "proxy_running": False,
        "config_path": str(csswitch_config_path()),
    }
    if enabled and check_health:
        payload["proxy_running"] = csswitch_proxy_health(config)
    return payload


def science_launch_environment() -> tuple[dict[str, str] | None, dict[str, Any]]:
    bridge = csswitch_bridge_payload(check_health=True)
    config = load_csswitch_config()
    proxy_url = csswitch_proxy_url(config)
    # If CC.Switch can be resolved to a direct provider, honor the active
    # profile and skip the CSSwitch proxy. This avoids stale Claude settings
    # winning after the user has switched profiles in CC.Switch.
    settings = load_json(claude_settings_path(), {})
    env_block = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    provider = thirdparty_provider_details()
    if provider:
        env = dict(os.environ)
        env["ANTHROPIC_BASE_URL"] = thirdparty_forwarder_base_url()
        # The forwarder injects the real provider key. Keep the child process
        # env free of long-lived third-party credentials.
        env["ANTHROPIC_AUTH_TOKEN"] = "ccscience-forwarder"
        # Forward safe ANTHROPIC_* overrides CC.Switch set (timeouts, beta flags,
        # etc.) unless they would override the selected active provider/model.
        for key, value in env_block.items():
            if isinstance(value, str) and key.startswith("ANTHROPIC_") and key not in (
                "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"
            ):
                if key.startswith("ANTHROPIC_DEFAULT_"):
                    continue
                env[key] = value
        provider_model = strip_context_suffix(provider.get("model", ""))
        if provider_model:
            env["ANTHROPIC_MODEL"] = provider_model
            settings_model = str(settings.get("model") or "")
            tier = _request_tier(settings_model) or "opus"
            env[f"ANTHROPIC_DEFAULT_{tier.upper()}_MODEL"] = provider_model
            env[f"ANTHROPIC_DEFAULT_{tier.upper()}_MODEL_NAME"] = provider_model
        return env, bridge
    if bridge.get("enabled") and bridge.get("proxy_running") and proxy_url:
        env = dict(os.environ)
        env["ANTHROPIC_BASE_URL"] = proxy_url
        return env, bridge
    return None, bridge


# ---------------------------------------------------------------------------
# Third-party no-login mode: pure-Python crypto (zero dependencies)
#
# Claude Science's request path resolves credentials OAuth-only (its manual
# API-key path is stubbed out), so a raw ANTHROPIC_API_KEY env var is not
# enough to run the agent. The supported way to make it operate without a real
# Claude sign-in is to seed its token store with a locally-generated "virtual"
# OAuth session with a far-future expiry. All inference then flows to
# ANTHROPIC_BASE_URL (either the CSSwitch proxy or our localhost forwarder),
# which injects the real third-party key outside the sandbox credential store.
# This never touches the real ~/.claude-science.
#
# The token file uses operon's "v2" format:
#   "v2:" + base64( IV(12) || AES-256-GCM(ciphertext) || authTag(16) )
#   key  = HKDF-SHA256(ikm=base64decode(OAUTH_ENCRYPTION_KEY), salt="",
#                      info="operon:aes-256-gcm:oauth", 32)
#   AAD  = b"v2:oauth"
# AES-256-GCM and HKDF are not in the Python standard library, so they are
# implemented here. Cross-checked byte-for-byte against Node's crypto.
# ---------------------------------------------------------------------------

_AES_SBOX: list[int] = []
_AES_RCON: list[int] = []


def _aes_init_tables() -> None:
    if _AES_SBOX:
        return
    p = q = 1
    sbox = [0] * 256
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if (p & 0x80) else 0)
        q ^= (q << 1) & 0xFF
        q ^= (q << 2) & 0xFF
        q ^= (q << 4) & 0xFF
        q ^= 0x09 if (q & 0x80) else 0
        q &= 0xFF
        xf = (q ^ ((q << 1) & 0xFF | (q >> 7)) ^ ((q << 2) & 0xFF | (q >> 6))
              ^ ((q << 3) & 0xFF | (q >> 5)) ^ ((q << 4) & 0xFF | (q >> 4)))
        sbox[p] = (xf ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    _AES_SBOX.extend(sbox)
    c = 1
    for _ in range(15):
        _AES_RCON.append(c)
        c = ((c << 1) ^ 0x1B) & 0xFF if (c & 0x80) else (c << 1) & 0xFF


def _aes_xtime(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if (a & 0x80) else (a << 1) & 0xFF


def _aes_key_expansion(key: bytes) -> list[list[int]]:
    _aes_init_tables()
    nk = len(key) // 4
    nr = {4: 10, 6: 12, 8: 14}[nk]
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = list(w[i - 1])
        if i % nk == 0:
            temp = [_AES_SBOX[b] for b in (temp[1:] + temp[:1])]
            temp[0] ^= _AES_RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            temp = [_AES_SBOX[b] for b in temp]
        w.append([w[i - nk][j] ^ temp[j] for j in range(4)])
    return w


def _aes_encrypt_block(block: bytes, w: list[list[int]], nr: int) -> bytes:
    state = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
    for c in range(4):
        for r in range(4):
            state[r][c] ^= w[c][r]
    for rnd in range(1, nr + 1):
        for r in range(4):
            for c in range(4):
                state[r][c] = _AES_SBOX[state[r][c]]
        for r in range(1, 4):
            state[r] = state[r][r:] + state[r][:r]
        if rnd != nr:
            for c in range(4):
                a = [state[r][c] for r in range(4)]
                state[0][c] = _aes_xtime(a[0]) ^ (_aes_xtime(a[1]) ^ a[1]) ^ a[2] ^ a[3]
                state[1][c] = a[0] ^ _aes_xtime(a[1]) ^ (_aes_xtime(a[2]) ^ a[2]) ^ a[3]
                state[2][c] = a[0] ^ a[1] ^ _aes_xtime(a[2]) ^ (_aes_xtime(a[3]) ^ a[3])
                state[3][c] = (_aes_xtime(a[0]) ^ a[0]) ^ a[1] ^ a[2] ^ _aes_xtime(a[3])
        for c in range(4):
            for r in range(4):
                state[r][c] ^= w[rnd * 4 + c][r]
    return bytes(state[r][c] for c in range(4) for r in range(4))


class _AES:
    def __init__(self, key: bytes) -> None:
        self.nr = {16: 10, 24: 12, 32: 14}[len(key)]
        self.w = _aes_key_expansion(key)

    def encrypt_block(self, b: bytes) -> bytes:
        return _aes_encrypt_block(b, self.w, self.nr)


def _gf_mult(x: int, y: int) -> int:
    R = 0xE1000000000000000000000000000000
    z = 0
    v = x
    for i in range(127, -1, -1):
        if (y >> i) & 1:
            z ^= v
        v = (v >> 1) ^ R if (v & 1) else v >> 1
    return z


def _ghash(h: int, data: bytes) -> int:
    y = 0
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        blk = blk + b"\x00" * (16 - len(blk))
        y = _gf_mult(y ^ int.from_bytes(blk, "big"), h)
    return y


def _inc32(block: bytes) -> bytes:
    ctr = (int.from_bytes(block[12:], "big") + 1) & 0xFFFFFFFF
    return block[:12] + ctr.to_bytes(4, "big")


def aes_gcm_encrypt(key: bytes, iv: bytes, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    aes = _AES(key)
    h = int.from_bytes(aes.encrypt_block(b"\x00" * 16), "big")
    j0 = iv + b"\x00\x00\x00\x01"  # 96-bit IV
    ct = bytearray()
    ctr = _inc32(j0)
    for i in range(0, len(plaintext), 16):
        ks = aes.encrypt_block(ctr)
        chunk = plaintext[i:i + 16]
        ct.extend(a ^ b for a, b in zip(chunk, ks))
        ctr = _inc32(ctr)
    lens = struct.pack(">QQ", len(aad) * 8, len(ct) * 8)
    a_pad = aad + b"\x00" * ((16 - len(aad) % 16) % 16)
    c_pad = bytes(ct) + b"\x00" * ((16 - len(ct) % 16) % 16)
    s = _ghash(h, a_pad + c_pad + lens)
    tag = bytes(a ^ b for a, b in zip(s.to_bytes(16, "big"), aes.encrypt_block(j0)))
    return bytes(ct), tag


def aes_gcm_decrypt(key: bytes, iv: bytes, ciphertext: bytes, tag: bytes, aad: bytes) -> bytes:
    aes = _AES(key)
    h = int.from_bytes(aes.encrypt_block(b"\x00" * 16), "big")
    j0 = iv + b"\x00\x00\x00\x01"
    lens = struct.pack(">QQ", len(aad) * 8, len(ciphertext) * 8)
    a_pad = aad + b"\x00" * ((16 - len(aad) % 16) % 16)
    c_pad = ciphertext + b"\x00" * ((16 - len(ciphertext) % 16) % 16)
    s = _ghash(h, a_pad + c_pad + lens)
    expected = bytes(a ^ b for a, b in zip(s.to_bytes(16, "big"), aes.encrypt_block(j0)))
    if not hmac.compare_digest(expected, tag):
        raise ValueError("GCM auth tag mismatch")
    pt = bytearray()
    ctr = _inc32(j0)
    for i in range(0, len(ciphertext), 16):
        ks = aes.encrypt_block(ctr)
        chunk = ciphertext[i:i + 16]
        pt.extend(a ^ b for a, b in zip(chunk, ks))
        ctr = _inc32(ctr)
    return bytes(pt)


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    if not salt:
        salt = b"\x00" * hashlib.sha256().digest_size
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = b""
    t = b""
    counter = 1
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        okm += t
        counter += 1
    return okm[:length]


def _derive_oauth_key(oauth_key_b64: str) -> bytes:
    ikm = base64.b64decode(oauth_key_b64)
    return hkdf_sha256(ikm, b"", b"operon:aes-256-gcm:oauth", 32)


def encrypt_token_v2(plaintext: str, oauth_key_b64: str) -> str:
    derived = _derive_oauth_key(oauth_key_b64)
    iv = secrets.token_bytes(12)
    ct, tag = aes_gcm_encrypt(derived, iv, plaintext.encode("utf-8"), b"v2:oauth")
    return "v2:" + base64.b64encode(iv + ct + tag).decode("ascii")


def decrypt_token_v2(body: str, oauth_key_b64: str) -> str:
    derived = _derive_oauth_key(oauth_key_b64)
    raw = base64.b64decode(body[len("v2:"):])
    iv, tag, ct = raw[:12], raw[-16:], raw[12:-16]
    return aes_gcm_decrypt(derived, iv, ct, tag, b"v2:oauth").decode("utf-8")


# --- Virtual OAuth forge + isolated sandbox --------------------------------

def _real_ancestor(path: pathlib.Path) -> pathlib.Path:
    """Resolve the nearest existing ancestor (following symlinks) and re-append
    the not-yet-existing tail, so guardrail comparisons can't be fooled by a
    symlink planted at a non-existent leaf."""
    cur = path.expanduser().resolve(strict=False)
    tail: list[str] = []
    probe = cur
    while not probe.exists():
        tail.insert(0, probe.name)
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    base = probe.resolve() if probe.exists() else probe
    return base.joinpath(*tail) if tail else base


def _assert_not_symlink(path: pathlib.Path) -> None:
    if path.is_symlink():
        raise SystemExit(f"refusing to follow symlink: {path}")


def _safe_write(path: pathlib.Path, data: str, mode: int = 0o600) -> None:
    _assert_not_symlink(path)
    tmp = path.parent / f".tmp-{secrets.token_hex(6)}"
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)
    with contextlib.suppress(OSError):
        os.chmod(path, mode)


def real_science_data_dir() -> pathlib.Path:
    """The installed instance's data dir (where bin/runtime assets live)."""
    for candidate in science_data_dirs():
        if (candidate / "runtime").is_dir() or (candidate / "bin").is_dir():
            return candidate
    return home() / ".claude-science"


def sandbox_home() -> pathlib.Path:
    override = _env_path("CCSCIENCE_SANDBOX_HOME")
    if override:
        return override
    return app_data_dir() / ".sandbox" / "home"


def sandbox_data_dir() -> pathlib.Path:
    return sandbox_home() / ".claude-science"


def _new_oauth_keys() -> dict[str, str]:
    return {name: base64.b64encode(secrets.token_bytes(32)).decode("ascii") for name in OAUTH_KEY_NAMES}


def _parse_key_file(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        eq = line.find("=")
        if eq <= 0:
            continue
        value = line[eq + 1:].strip()
        if value:
            out[line[:eq].strip()] = value
    return out


def forge_virtual_oauth(auth_dir: pathlib.Path, email: str = VIRTUAL_EMAIL, force: bool = False,
                        access_token: str | None = None) -> dict[str, Any]:
    """Write a self-generated virtual OAuth session into an ISOLATED auth dir so
    Claude Science reports authenticated=true without any real Claude account.
    Hard guardrails refuse to write into the real credential directory.

    access_token is an escape hatch for tests/backward compatibility. Normal
    direct mode uses a throwaway placeholder; the localhost forwarder injects
    the real provider key so long-lived keys are not copied into sandbox files."""
    resolved = _real_ancestor(auth_dir)
    real_dir = _real_ancestor(home() / ".claude-science")
    if resolved == real_dir:
        raise SystemExit(f"refusing to forge into the real credential directory: {real_dir}")
    if ".sandbox" not in resolved.parts and not force:
        raise SystemExit(f"refusing: auth dir {resolved} is not inside a .sandbox/ directory (use force to override)")
    if not email.endswith("localhost.invalid"):
        raise SystemExit(f"refusing: virtual email must end with localhost.invalid (got {email})")

    resolved.mkdir(parents=True, exist_ok=True)
    # Re-check after creation: the dir itself must not be a symlink, and must
    # still not resolve into the real credential directory. This closes the gap
    # where the leaf was created as a symlink between the guardrail and the write.
    _assert_not_symlink(resolved)
    if resolved.resolve() == real_dir:
        raise SystemExit(f"refusing to forge into the real credential directory: {real_dir}")
    with contextlib.suppress(OSError):
        os.chmod(resolved, 0o700)

    key_file = resolved / "encryption.key"
    _assert_not_symlink(key_file)
    if key_file.exists() and not force:
        keys = _parse_key_file(key_file.read_text(encoding="utf-8"))
        for name in OAUTH_KEY_NAMES:
            keys.setdefault(name, base64.b64encode(secrets.token_bytes(32)).decode("ascii"))
    else:
        keys = _new_oauth_keys()
    _safe_write(key_file, "\n".join(f"{name}={keys[name]}" for name in OAUTH_KEY_NAMES) + "\n", 0o600)

    account_uuid = str(uuid.uuid4())
    org_uuid = str(uuid.uuid4())
    real_token = access_token.strip() if isinstance(access_token, str) else ""
    blob = {
        "access_token": real_token or ("sk-ant-virtual-" + secrets.token_hex(24)),
        "refresh_token": "",
        "api_key": None,
        "token_expires_at": "2099-01-01T00:00:00.000Z",
        "provider": "claude_ai",
        "scopes": "user:inference user:file_upload user:profile user:mcp_servers user:plugins",
        "email": email,
        "account_uuid": account_uuid,
        "subscription_type": "max",
        "rate_limit_tier": None,
        "seat_tier": None,
        "org_uuid": org_uuid,
        "billing_type": None,
        "has_extra_usage_enabled": False,
    }
    enc_body = encrypt_token_v2(json.dumps(blob), keys["OAUTH_ENCRYPTION_KEY"])
    # self-check: the daemon must be able to decrypt what we wrote
    if json.loads(decrypt_token_v2(enc_body, keys["OAUTH_ENCRYPTION_KEY"])).get("email") != email:
        raise SystemExit("virtual OAuth self-check failed (decrypt roundtrip mismatch)")

    tok_dir = resolved / ".oauth-tokens"
    _assert_not_symlink(tok_dir)
    tok_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(tok_dir, 0o700)
    for existing in tok_dir.glob("*.enc"):
        _assert_not_symlink(existing)
        existing.unlink()
    user_id = "".join(ch for ch in account_uuid if ch.isalnum() or ch in "_-")
    enc_file = tok_dir / f"{user_id}.enc"
    _safe_write(enc_file, enc_body, 0o600)

    _safe_write(resolved / "active-org.json", json.dumps({"org_uuid": org_uuid}, indent=2) + "\n", 0o600)
    return {"auth_dir": str(resolved), "email": email, "account_uuid": account_uuid,
            "org_uuid": org_uuid, "enc_file": str(enc_file)}


def sandbox_has_valid_token(auth_dir: pathlib.Path) -> bool:
    key_file = auth_dir / "encryption.key"
    tok_dir = auth_dir / ".oauth-tokens"
    if not key_file.is_file() or not tok_dir.is_dir():
        return False
    encs = list(tok_dir.glob("*.enc"))
    if len(encs) != 1:
        return False
    keys = _parse_key_file(key_file.read_text(encoding="utf-8"))
    oauth_key = keys.get("OAUTH_ENCRYPTION_KEY")
    if not oauth_key:
        return False
    try:
        blob = json.loads(decrypt_token_v2(encs[0].read_text(encoding="utf-8"), oauth_key))
    except Exception:
        return False
    return blob.get("provider") == "claude_ai" and bool(blob.get("email"))


def claude_science_bin() -> pathlib.Path | None:
    commands = claude_science_commands()
    return commands[0] if commands else None


def _clone_dir(src: pathlib.Path, dst: pathlib.Path) -> None:
    # Clone into a temp sibling and atomically move it into place, so an
    # interrupted or failed copy never leaves a half-populated dst that the
    # next run would mistake for complete.
    if dst.exists():
        return
    staging = dst.parent / f"{dst.name}.partial-{secrets.token_hex(6)}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        cloned = False
        if is_macos():
            # APFS clone: instant, copy-on-write, does not duplicate disk blocks
            if run(["cp", "-Rc", str(src), str(staging)]).returncode == 0:
                cloned = True
            else:
                shutil.rmtree(staging, ignore_errors=True)
        if not cloned:
            shutil.copytree(src, staging, symlinks=True)
        os.replace(staging, dst)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def ensure_sandbox_runtime() -> None:
    real = real_science_data_dir()
    if not (real / "bin").is_dir():
        raise SystemExit(
            "Claude Science is not installed yet. Open Claude Science once, then try again."
        )
    data = sandbox_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    for asset in SANDBOX_RUNTIME_ASSETS:
        src = real / asset
        if src.is_dir():
            _clone_dir(src, data / asset)


def ensure_sandbox_keychain() -> None:
    """macOS: give the sandbox HOME its own empty login keychain so the daemon's
    keychain mirroring does not prompt against the user's real keychain."""
    if not is_macos():
        return
    kc = sandbox_home() / "Library" / "Keychains" / "login.keychain-db"
    env = dict(os.environ)
    env["HOME"] = str(sandbox_home())
    if not kc.exists():
        kc.parent.mkdir(parents=True, exist_ok=True)
        run(["security", "create-keychain", "-p", "", str(kc)], env=env)
    for args in (
        ["security", "list-keychains", "-d", "user", "-s", str(kc)],
        ["security", "default-keychain", "-d", "user", "-s", str(kc)],
        ["security", "unlock-keychain", "-p", "", str(kc)],
        ["security", "set-keychain-settings", str(kc)],
    ):
        run(args, env=env)


def _proxy_hostport(proxy_url: str) -> str:
    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/]+)", proxy_url)
    return match.group(1) if match else "127.0.0.1"


def _url_host(url: str) -> str:
    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/:]+)", url)
    return match.group(1) if match else ""


def _dead_local_proxy() -> str:
    """A 127.0.0.1 URL on a currently-unbound port. Pointing https_proxy here
    makes the daemon's blocking Anthropic oauth/profile probe fail instantly
    (connection refused) so it treats itself as logged-out — the self-contained
    replacement for the CSSwitch CONNECT fast-fail, with no proxy process."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    finally:
        sock.close()
    return f"http://127.0.0.1:{port}"


def sandbox_launch_env(target: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(sandbox_home())
    base_url = str(target.get("base_url") or "")
    env["ANTHROPIC_BASE_URL"] = base_url
    if target.get("mode") == "direct":
        # Self-contained direct mode: the daemon talks to our localhost
        # forwarder, which injects the real provider key. Point https_proxy at a
        # dead local port so the blocking Anthropic oauth/profile probe fails
        # instantly (daemon treats itself as logged-out), while localhost stays
        # in no_proxy so inference reaches the forwarder.
        host = _url_host(base_url)
        dead = _dead_local_proxy()
        env["https_proxy"] = dead
        env["HTTPS_PROXY"] = dead
        no_proxy = "127.0.0.1,localhost,::1" + (f",{host}" if host else "")
        env["no_proxy"] = no_proxy
        env["NO_PROXY"] = no_proxy
        return env
    # CSSwitch proxy mode: route inference through the local proxy (ANTHROPIC_BASE_URL
    # is the proxy) and fast-fail Anthropic HTTPS via the same proxy host's CONNECT
    # handler so the daemon skips the "Switching organization" hang.
    fastfail = f"http://{_proxy_hostport(base_url)}"
    env["https_proxy"] = fastfail
    env["HTTPS_PROXY"] = fastfail
    env["no_proxy"] = "127.0.0.1,localhost,::1"
    env["NO_PROXY"] = "127.0.0.1,localhost,::1"
    return env


def sandbox_daemon_status() -> dict[str, Any]:
    binary = claude_science_bin()
    if not binary:
        return {"running": False}
    env = dict(os.environ)
    env["HOME"] = str(sandbox_home())
    result = run([str(binary), "status", "--data-dir", str(sandbox_data_dir())], env=env)
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return {"running": False}


def _assert_sandbox_guardrails(port: int) -> None:
    if port == REAL_SCIENCE_PORT:
        raise SystemExit(f"refusing: port {REAL_SCIENCE_PORT} is reserved for the real Claude Science instance")
    if _real_ancestor(sandbox_data_dir()) == _real_ancestor(home() / ".claude-science"):
        raise SystemExit("refusing: sandbox data dir resolves to the real credential directory")


def launched_proxy_path() -> pathlib.Path:
    return sandbox_home() / ".launched-proxy"


def launched_proxy_url() -> str | None:
    try:
        return launched_proxy_path().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def start_sandbox_daemon(port: int, target: dict[str, Any], lang: str = "en") -> None:
    _assert_sandbox_guardrails(port)
    binary = claude_science_bin()
    if not binary:
        raise SystemExit(tr(lang, "science_cli_missing"))
    ensure_sandbox_runtime()
    ensure_sandbox_keychain()
    if target.get("mode") == "direct":
        # Direct mode routes through our localhost forwarder, which injects the
        # real key. Always refresh the sandbox OAuth token with a placeholder so
        # an old token containing a provider key from a previous build is purged.
        # force=False REUSES the existing encryption.key so it stays consistent
        # with the daemon's macOS-Keychain copy — regenerating the key would make
        # the daemon fall back to the stale keychain key ("ensureEncryptionKeys:
        # ... using the macOS Keychain copy") and fail to read the forged token.
        forge_virtual_oauth(sandbox_data_dir(), force=False)
    elif not sandbox_has_valid_token(sandbox_data_dir()):
        forge_virtual_oauth(sandbox_data_dir())
    cmd = [str(binary), "serve", "--data-dir", str(sandbox_data_dir()),
           "--port", str(port), "--no-browser", "--no-auto-update", "--detached"]
    result = run(cmd, env=sandbox_launch_env(target))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:500]
        raise SystemExit(tr(lang, "thirdparty_launch_failed", detail=detail or f"exit {result.returncode}"))
    for _ in range(20):  # wait up to ~10s for the daemon socket to come up
        if sandbox_daemon_status().get("running"):
            with contextlib.suppress(OSError):
                launched_proxy_path().write_text(str(target.get("id") or ""), encoding="utf-8")
            return
        time.sleep(0.5)
    raise SystemExit(tr(lang, "thirdparty_launch_failed", detail="daemon did not become ready within ~10s"))


def stop_sandbox_daemon() -> str:
    binary = claude_science_bin()
    if not binary:
        return "not-installed"
    env = dict(os.environ)
    env["HOME"] = str(sandbox_home())
    result = run([str(binary), "stop", "--data-dir", str(sandbox_data_dir())], env=env)
    return "stopped" if result.returncode == 0 else "not-running"


def sandbox_url(port: int, target: dict[str, Any]) -> str:
    binary = claude_science_bin()
    if not binary:
        raise SystemExit(tr("en", "science_cli_missing"))
    env = sandbox_launch_env(target)
    result = run([str(binary), "url", "--data-dir", str(sandbox_data_dir())], env=env)
    match = re.search(r"https?://[^\s]+", f"{result.stdout}\n{result.stderr}")
    if result.returncode == 0 and match:
        return match.group(0)
    raise SystemExit(tr("en", "science_url_missing"))


# ---------------------------------------------------------------------------
# Self-contained third-party forwarder (no CSSwitch needed)
#
# Claude Science (operon) speaks the Anthropic Messages API, but sends a few
# fields that stricter third-party endpoints reject — notably thinking.type
# "auto" (DeepSeek/MiniMax only accept adaptive/enabled/disabled). This tiny
# local forwarder sits in front of the provider: it normalizes the request,
# injects the user's key, and streams the response back. The pure-Python virtual
# login stays ours; this replaces the need to run a separate CSSwitch proxy.
# Request normalization mirrors CSSwitch's normalize_thinking
# (MIT-licensed, github.com/SuperJJ007/CSSwitch).
# ---------------------------------------------------------------------------


def normalize_thirdparty_request(body: dict[str, Any], host: str) -> dict[str, Any]:
    """Rewrite operon's Anthropic request for stricter third-party endpoints.

    - thinking.type "auto" -> "adaptive" (DeepSeek/MiniMax accept adaptive).
    - DeepSeek rejects a forced tool_choice with thinking enabled → disable.
    - Strip `cache_control` everywhere (tools / system / messages content):
      prompt caching is an Anthropic-only field; third-party endpoints
      (MiniMax, DeepSeek, etc.) reject the request with 400 if it is present
      (verified 2026-07-06: MiniMax returned 2013 "function name or parameters
      is empty" — the wrapper parser bailed on the unknown cache_control
      block before reading the tool schema).
    """
    def strip_cache_control(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("cache_control", None)
            for v in node.values():
                strip_cache_control(v)
        elif isinstance(node, list):
            for v in node:
                strip_cache_control(v)

    strip_cache_control(body)
    normalize_anthropic_tools(body)
    is_deepseek = "deepseek" in host.lower()
    tc = body.get("tool_choice")
    forcing = isinstance(tc, dict) and tc.get("type") in ("any", "tool")
    if forcing and is_deepseek:
        body["thinking"] = {"type": "disabled"}
        return body
    th = body.get("thinking")
    if isinstance(th, dict) and th.get("type") == "auto":
        th = dict(th)
        th["type"] = "adaptive"
        body["thinking"] = th
    return body


def _tool_schema_has_parameters(schema: Any) -> bool:
    if not isinstance(schema, dict) or not schema:
        return False
    props = schema.get("properties")
    if isinstance(props, dict) and props:
        return True
    return any(key not in ("type", "properties", "required", "additionalProperties", "$schema")
               for key in schema)


def normalize_anthropic_tools(body: dict[str, Any]) -> None:
    """Keep Claude Science tool definitions valid for strict Anthropic relays."""
    tools = body.get("tools")
    if not isinstance(tools, list):
        return

    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        fixed = dict(tool)
        fixed["name"] = name
        schema = fixed.get("input_schema")
        if not _tool_schema_has_parameters(schema):
            continue
        fixed_schema = dict(schema)
        if not isinstance(fixed_schema.get("type"), str) or not fixed_schema.get("type"):
            fixed_schema["type"] = "object"
        if fixed_schema.get("type") == "object" and not isinstance(fixed_schema.get("properties"), dict):
            fixed_schema["properties"] = {}
        fixed["input_schema"] = fixed_schema
        normalized.append(fixed)
        names.add(name)

    if normalized:
        body["tools"] = normalized
    else:
        body.pop("tools", None)

    choice = body.get("tool_choice")
    if not isinstance(choice, dict):
        return
    typ = choice.get("type")
    if typ in ("any", "tool") and not normalized:
        body.pop("tool_choice", None)
    elif typ == "tool" and str(choice.get("name") or "") not in names:
        body["tool_choice"] = {"type": "auto"}


_CSSWITCH_PROVIDER_SPECS = [
    (("deepseek",), "https://api.deepseek.com/anthropic",
     ("DEEPSEEK_API_KEY",), "DeepSeek"),
    (("kimi", "moonshot"), "https://api.moonshot.ai/v1",
     ("MOONSHOT_API_KEY", "KIMI_API_KEY"), "Kimi"),
    (("minimax", "minimaxi"), "https://api.minimax.io/anthropic",
     ("MINIMAX_API_KEY", "MINIMAXI_API_KEY"), "MiniMax"),
    (("glm", "zhipu", "bigmodel"), "https://open.bigmodel.cn/api/paas/v4",
     ("BIGMODEL_API_KEY", "ZHIPUAI_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY"), "GLM"),
    (("qwen", "dashscope", "aliyun"), "https://dashscope.aliyuncs.com/compatible-mode/v1",
     ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "ALIYUN_DASHSCOPE_API_KEY"), "Qwen"),
    (("siliconflow",), "https://api.siliconflow.cn/v1",
     ("SILICONFLOW_API_KEY",), "SiliconFlow"),
    (("openrouter",), "https://openrouter.ai/api/v1",
     ("OPENROUTER_API_KEY",), "OpenRouter"),
]


def _env_ref_name(text: str) -> str:
    env_ref = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", text)
    return env_ref.group(1) if env_ref else ""


def _resolve_env_string(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    env_name = _env_ref_name(text)
    if env_name:
        resolved = os.environ.get(env_name, "")
        if resolved and resolved != text:
            return _resolve_env_string(resolved)
        return ""
    return text


def _usable_secret(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    env_name = _env_ref_name(text)
    if env_name:
        resolved = os.environ.get(env_name, "")
        if resolved and resolved != text:
            return _usable_secret(resolved)
        return ""
    low = text.lower()
    placeholders = {"hidden", "<hidden>", "<redacted>", "redacted", "****", "********", "null", "none"}
    return "" if low in placeholders or set(text) == {"*"} else text


def _profile_text(profile: dict[str, Any]) -> str:
    keys = ("template_id", "templateId", "provider", "provider_id", "providerId", "name",
            "display_name", "displayName", "model", "model_id", "modelId", "model_name",
            "modelName", "base_url", "baseUrl", "api_base", "apiBase", "api_url", "apiUrl")
    env_block = _profile_env(profile)
    pieces = [str(profile.get(k) or "") for k in keys]
    pieces.extend(str(k) for k in env_block.keys())
    for key in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "BASE_URL", "API_BASE_URL",
                "ANTHROPIC_MODEL", "OPENAI_MODEL", "MODEL", "MODEL_NAME"):
        value = env_block.get(key)
        if isinstance(value, str):
            pieces.append(value)
    return " ".join(pieces).lower()


def _csswitch_provider_spec(profile: dict[str, Any]) -> tuple[str, tuple[str, ...], str] | None:
    text = _profile_text(profile)
    for aliases, base_url, env_names, label in _CSSWITCH_PROVIDER_SPECS:
        if any(alias in text for alias in aliases):
            return base_url, env_names, label
    return None


def _profile_base_url(profile: dict[str, Any], default: str = "") -> str:
    env_block = profile.get("env") if isinstance(profile.get("env"), dict) else {}
    for container in (profile, env_block):
        for key in ("ANTHROPIC_BASE_URL", "base_url", "baseUrl", "api_base", "apiBase",
                    "api_url", "apiUrl", "endpoint", "url", "openai_base_url",
                    "anthropic_base_url", "OPENAI_BASE_URL", "BASE_URL",
                    "API_BASE_URL", "DEEPSEEK_BASE_URL", "DEEPSEEK_API_BASE",
                    "MOONSHOT_BASE_URL", "MOONSHOT_API_BASE", "KIMI_BASE_URL",
                    "KIMI_API_BASE", "MINIMAX_BASE_URL", "MINIMAX_API_BASE",
                    "MINIMAXI_BASE_URL", "MINIMAXI_API_BASE", "BIGMODEL_BASE_URL",
                    "ZHIPUAI_BASE_URL", "GLM_BASE_URL", "DASHSCOPE_BASE_URL",
                    "QWEN_BASE_URL", "SILICONFLOW_BASE_URL", "OPENROUTER_BASE_URL"):
            value = container.get(key) if isinstance(container, dict) else None
            resolved = _resolve_env_string(value)
            if resolved:
                return resolved
    return default


def _profile_env(profile: dict[str, Any]) -> dict[str, Any]:
    env_block = profile.get("env")
    return env_block if isinstance(env_block, dict) else {}


def _minimax_default_base(profile: dict[str, Any], key_source: str = "") -> str:
    text = " ".join((
        _profile_text(profile),
        " ".join(str(v or "") for v in _profile_env(profile).values()),
        key_source,
    )).lower()
    cn_markers = ("minimaxi", "china", "cn", "zh", "中国", "国内", "大陆", "china-mainland")
    if "MINIMAXI_API_KEY" in key_source or any(marker in text for marker in cn_markers):
        return "https://api.minimaxi.com/anthropic"
    return "https://api.minimax.io/anthropic"


def _profile_default_base(profile: dict[str, Any], default: str, key_source: str = "") -> str:
    if "minimax" in default or "minimaxi" in default or any(alias in _profile_text(profile) for alias in ("minimax", "minimaxi")):
        return _minimax_default_base(profile, key_source)
    return default


def _profile_key_fields(env_names: tuple[str, ...]) -> list[str]:
    generic = (
        "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "api_key", "apiKey",
        "auth_token", "authToken", "access_token", "accessToken", "token", "key",
        "OPENAI_API_KEY", "API_KEY",
    )
    names: list[str] = []
    for key in (*generic, *env_names):
        names.append(key)
        names.append(key.lower())
    return list(dict.fromkeys(names))


def _profile_api_key_details(profile: dict[str, Any], env_names: tuple[str, ...]) -> tuple[str, str]:
    env_block = _profile_env(profile)
    for scope, container in (("profile", profile), ("profile.env", env_block)):
        for key in _profile_key_fields(env_names):
            if isinstance(container, dict):
                secret = _usable_secret(container.get(key))
                if secret:
                    return secret, f"{scope}.{key}"
    for name in env_names:
        secret = _usable_secret(os.environ.get(name))
        if secret:
            return secret, name
    return "", ""


def _profile_api_key(profile: dict[str, Any], env_names: tuple[str, ...]) -> str:
    return _profile_api_key_details(profile, env_names)[0]


_PROVIDER_MODEL_FIELDS = (
    "model", "model_id", "modelId", "model_name", "modelName", "api_model", "apiModel",
    "target_model", "targetModel", "ANTHROPIC_MODEL", "OPENAI_MODEL", "MODEL",
    "MODEL_NAME", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME",
    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME",
    "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME",
)


def _profile_model(profile: dict[str, Any], settings_provider: dict[str, str] | None = None) -> str:
    env_block = _profile_env(profile)
    for container in (profile, env_block):
        if not isinstance(container, dict):
            continue
        for key in _PROVIDER_MODEL_FIELDS:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return strip_context_suffix(value)
    return strip_context_suffix(str(settings_provider and settings_provider.get("model") or ""))


def _all_provider_env_names() -> tuple[str, ...]:
    names: list[str] = []
    for _aliases, _base, env_names, _label in _CSSWITCH_PROVIDER_SPECS:
        names.extend(env_names)
    return tuple(dict.fromkeys(names))


def _provider_env_names_for_base(base_url: str) -> tuple[str, ...]:
    text = base_url.lower()
    host = _url_host(base_url).lower()
    names: list[str] = []
    for aliases, expected_base, env_names, _label in _CSSWITCH_PROVIDER_SPECS:
        expected_host = _url_host(expected_base).lower()
        if (expected_host and expected_host == host) or any(alias in text for alias in aliases):
            names.extend(env_names)
    return tuple(dict.fromkeys(names))


def _settings_api_key_details(env_block: dict[str, Any], base_url: str) -> tuple[str, str]:
    all_env_names = _all_provider_env_names()
    for key in _profile_key_fields(all_env_names):
        secret = _usable_secret(env_block.get(key))
        if secret:
            return secret, key
    for name in _provider_env_names_for_base(base_url):
        secret = _usable_secret(os.environ.get(name))
        if secret:
            return secret, name
    return "", ""


def _settings_provider_model(settings: dict[str, Any], env_block: dict[str, Any]) -> str:
    source_model = strip_context_suffix(str(settings.get("model") or ""))
    tier = _request_tier(source_model)
    candidates: list[str] = []
    if tier:
        up = tier.upper()
        candidates.extend([
            f"ANTHROPIC_DEFAULT_{up}_MODEL",
            f"ANTHROPIC_DEFAULT_{up}_MODEL_NAME",
        ])
    candidates.extend(["ANTHROPIC_MODEL", "OPENAI_MODEL", "MODEL", "MODEL_NAME"])
    for key in candidates:
        value = env_block.get(key)
        if isinstance(value, str) and value.strip():
            return strip_context_suffix(value)
    if source_model and not _request_tier(source_model) and not source_model.startswith("claude-"):
        return source_model
    return ""


def _settings_provider_details() -> dict[str, str] | None:
    settings = load_json(claude_settings_path(), {})
    if not isinstance(settings, dict):
        settings = {}
    env_block = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    base = _profile_base_url({"env": env_block}, "")
    key, key_name = _settings_api_key_details(env_block, base)
    if not (base and key):
        return None
    return {"base_url": base, "key": key, "source": "claude-settings",
            "model": _settings_provider_model(settings, env_block),
            "key_env": key_name}


def _path_mtime(path: pathlib.Path) -> float:
    with contextlib.suppress(OSError):
        return path.stat().st_mtime
    return 0.0


def _same_provider_family(left_base: str, right_base: str) -> bool:
    left_host = _url_host(left_base).lower()
    right_host = _url_host(right_base).lower()
    if left_host and left_host == right_host:
        return True
    left_brand = _provider_brand(left_host)
    right_brand = _provider_brand(right_host)
    return left_brand != "Third-Party" and left_brand == right_brand


def _settings_provider_newer_than_csswitch() -> bool:
    settings_mtime = _path_mtime(claude_settings_path())
    csswitch_mtime = _path_mtime(csswitch_config_path())
    return bool(settings_mtime and (not csswitch_mtime or settings_mtime > csswitch_mtime))


def _provider_matches_profile(base_url: str, profile: dict[str, Any]) -> bool:
    spec = _csswitch_provider_spec(profile)
    if not spec:
        return False
    expected_base, _env_names, label = spec
    text = _profile_text(profile) + " " + label.lower()
    host = _url_host(base_url).lower()
    expected_host = _url_host(expected_base).lower()
    if expected_host and host == expected_host:
        return True
    return any(alias in host for alias in text.split() if len(alias) >= 4)


def _csswitch_profile_provider_details(settings_provider: dict[str, str] | None = None) -> dict[str, str] | None:
    config = load_csswitch_config()
    profile = csswitch_active_profile(config)
    if not profile:
        return None
    spec = _csswitch_provider_spec(profile)
    default_base, env_names, label = spec if spec else ("", (), str(profile.get("name") or "Custom"))
    explicit_base = _profile_base_url(profile, "")
    if explicit_base:
        env_names = tuple(dict.fromkeys((*env_names, *_provider_env_names_for_base(explicit_base))))
    key, key_source = _profile_api_key_details(profile, env_names)
    base = explicit_base or _profile_default_base(profile, default_base, key_source)
    if base and not key and not env_names:
        env_names = _provider_env_names_for_base(base)
        key, key_source = _profile_api_key_details(profile, env_names)
    if spec and not key and settings_provider and _provider_matches_profile(settings_provider.get("base_url", ""), profile):
        key = settings_provider["key"]
        key_source = settings_provider.get("key_env", "claude-settings")
        base = explicit_base or settings_provider["base_url"]
    if not (base and key):
        return None
    model = _profile_model(profile, settings_provider)
    return {"base_url": base, "key": key, "source": "csswitch-profile",
            "model": model, "profile": str(profile.get("name") or profile.get("displayName") or label),
            "key_env": key_source}


def thirdparty_provider_details() -> dict[str, str] | None:
    """Provider details for the direct third-party forwarder.

    Priority: explicit test/CLI env override, then the active CC.Switch profile
    when it can be resolved to a base URL + key, then Claude settings. The
    forwarder re-reads this on every request, so switching profiles is picked up
    live without restarting it.
    """
    env_base = os.environ.get("CCSCIENCE_TP_BASE", "").strip()
    env_key = os.environ.get("CCSCIENCE_TP_KEY", "").strip()
    if env_base and env_key:
        return {"base_url": env_base, "key": env_key, "source": "env-override",
                "model": strip_context_suffix(os.environ.get("CCSCIENCE_TP_MODEL", "")),
                "key_env": "CCSCIENCE_TP_KEY"}
    settings_provider = _settings_provider_details()
    profile_provider = _csswitch_profile_provider_details(settings_provider)
    if profile_provider:
        if settings_provider and not _same_provider_family(
            profile_provider.get("base_url", ""), settings_provider.get("base_url", "")
        ) and _settings_provider_newer_than_csswitch():
            return settings_provider
        return profile_provider
    profile = csswitch_active_profile(load_csswitch_config())
    if profile and _csswitch_provider_spec(profile) and settings_provider and not _provider_matches_profile(
        settings_provider.get("base_url", ""), profile
    ):
        return settings_provider if _settings_provider_newer_than_csswitch() else None
    return settings_provider


def thirdparty_provider() -> tuple[str, str] | None:
    details = thirdparty_provider_details()
    if not details:
        return None
    return details["base_url"], details["key"]


def _thirdparty_settings_env() -> dict[str, Any]:
    settings = load_json(claude_settings_path(), {})
    if not isinstance(settings, dict):
        return {}
    env_block = settings.get("env")
    return env_block if isinstance(env_block, dict) else {}


def _request_tier(model: str | None) -> str:
    low = strip_context_suffix(str(model or "")).lower()
    for tier in ("opus", "sonnet", "haiku", "fable"):
        if tier in low:
            return tier
    return ""


def _provider_model_for_request(req_model: str, provider_base: str = "", selected_model: str = "") -> str:
    """Resolve the real provider model CC.Switch wrote for a Claude tier.

    Claude Science only accepts claude-* ids in the UI, but third-party
    providers often need their own model id on the upstream request. CC.Switch
    records that in ANTHROPIC_DEFAULT_<TIER>_MODEL / ANTHROPIC_MODEL.
    """
    explicit = os.environ.get("CCSCIENCE_TP_MODEL", "").strip()
    if explicit:
        return strip_context_suffix(explicit)
    env_block = _thirdparty_settings_env()
    settings = load_json(claude_settings_path(), {})
    settings_model = settings.get("model") if isinstance(settings, dict) else ""
    tier = _request_tier(req_model) or _request_tier(str(settings_model or ""))
    # The per-tier model wins for the tier actually being requested. CC.Switch
    # writes a distinct ANTHROPIC_DEFAULT_<TIER>_MODEL per tier (e.g.
    # opus->deepseek-v4-pro, haiku->deepseek-v4-flash), so a background/haiku
    # request must resolve to the haiku model — not the single `selected_model`
    # the active profile carries for its headline tier. Checking this before
    # `selected_model` keeps per-tier mapping working; single-model providers
    # (no per-tier env) simply fall through to `selected_model` below.
    if tier:
        up = tier.upper()
        for key in (f"ANTHROPIC_DEFAULT_{up}_MODEL", f"ANTHROPIC_DEFAULT_{up}_MODEL_NAME"):
            value = env_block.get(key)
            if isinstance(value, str) and value.strip():
                return strip_context_suffix(value)
    if selected_model:
        return strip_context_suffix(selected_model)
    if provider_base:
        profile_provider = _csswitch_profile_provider_details(_settings_provider_details())
        if profile_provider and profile_provider.get("base_url") == provider_base:
            model = profile_provider.get("model", "")
            if model:
                return strip_context_suffix(model)
    for key in ("ANTHROPIC_MODEL", "OPENAI_MODEL", "MODEL", "MODEL_NAME"):
        value = env_block.get(key)
        if isinstance(value, str) and value.strip():
            return strip_context_suffix(value)
    return ""


def _is_openai_compatible_base(base_url: str) -> bool:
    parsed = urllib.parse.urlparse(base_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/").lower()
    if "anthropic" in path:
        return False
    if path.endswith("/v1") or path.endswith("/openai"):
        return True
    # Kimi's official platform documents OpenAI-compatible Chat Completions;
    # many relays expose the same shape under brand-specific hosts.
    return any(key in host for key in (
        "moonshot", "kimi", "openai", "openrouter", "deepseek", "minimax",
        "minimaxi", "bigmodel", "zhipu", "dashscope", "qwen", "siliconflow",
    ))


def _openai_chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    parsed = urllib.parse.urlparse(base)
    path = parsed.path.rstrip("/").lower()
    if path.endswith("/chat/completions"):
        return base
    if re.search(r"/v\d+$", path):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _anthropic_endpoint_url(base_url: str, request_path: str) -> str:
    base = base_url.rstrip("/")
    req = request_path if request_path.startswith("/") else "/" + request_path
    path, sep, query = req.partition("?")
    query = sep + query if sep else ""
    base_path = urllib.parse.urlparse(base).path.rstrip("/").lower()
    if path.startswith("/v1/") and base_path.endswith("/v1"):
        return base + path[len("/v1"):] + query
    if path == "/v1/messages" and base_path.endswith("/v1/messages"):
        return base + query
    if path == "/v1/messages/count_tokens" and base_path.endswith("/v1/messages/count_tokens"):
        return base + query
    return base + req


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                typ = block.get("type")
                if typ == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif typ == "tool_result":
                    parts.append(_content_text(block.get("content")))
    return "\n".join(p for p in parts if p)


def _anthropic_source_data_url(source: Any) -> str:
    if not isinstance(source, dict):
        return ""
    typ = str(source.get("type") or "").lower()
    if typ in ("url", "uri"):
        return str(source.get("url") or source.get("uri") or "").strip()
    data = source.get("data")
    media_type = str(source.get("media_type") or source.get("mediaType") or "").strip()
    if typ == "base64" and isinstance(data, str) and data.strip() and media_type:
        return f"data:{media_type};base64,{data.strip()}"
    return ""


def _anthropic_block_to_openai_part(block: Any) -> dict[str, Any] | None:
    if isinstance(block, str):
        return {"type": "text", "text": block}
    if not isinstance(block, dict):
        return None
    typ = block.get("type")
    if typ == "text" and isinstance(block.get("text"), str):
        return {"type": "text", "text": block["text"]}
    if typ == "image":
        url = _anthropic_source_data_url(block.get("source"))
        return {"type": "image_url", "image_url": {"url": url}} if url else None
    if typ == "video":
        url = _anthropic_source_data_url(block.get("source"))
        return {"type": "video_url", "video_url": {"url": url}} if url else None
    return None


def _anthropic_content_to_openai_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [part for part in (_anthropic_block_to_openai_part(block) for block in content) if part]
    return _openai_parts_to_content(parts) if parts else _content_text(content)


def _openai_parts_to_content(parts: list[dict[str, Any]]) -> Any:
    if not parts:
        return ""
    if all(part.get("type") == "text" for part in parts):
        return "\n".join(str(part.get("text") or "") for part in parts if part.get("text"))
    return parts


def _anthropic_tools_to_openai(tools: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(tools, list):
        return out
    for tool in tools:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        fn: dict[str, Any] = {
            "name": str(tool["name"]),
            "parameters": tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {
                "type": "object",
                "properties": {},
            },
        }
        if isinstance(tool.get("description"), str):
            fn["description"] = tool["description"]
        out.append({"type": "function", "function": fn})
    return out


def _anthropic_tool_choice_to_openai(choice: Any) -> Any:
    if not isinstance(choice, dict):
        return None
    typ = choice.get("type")
    if typ in ("none", "auto"):
        return typ
    if typ == "any":
        return "required"
    if typ == "tool" and choice.get("name"):
        return {"type": "function", "function": {"name": str(choice["name"])}}
    return None


def _rough_count_tokens(value: Any) -> int:
    text = ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    elif value is not None:
        text = str(value)
    # Conservative-enough local estimate for compatibility probes: CJK text is
    # denser than English, and JSON/tool schemas add structural overhead.
    return max(1, (len(text) + 3) // 4) if text else 0


def estimate_anthropic_input_tokens(body: dict[str, Any]) -> int:
    total = 0
    for key in ("model", "system", "messages", "tools", "tool_choice", "thinking"):
        if key in body:
            total += _rough_count_tokens(body[key])
    return max(1, total)


def _anthropic_messages_to_openai(body: dict[str, Any], preserve_reasoning: bool = False,
                                  reasoning_details: bool = False,
                                  include_tool_names: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    tool_names_by_id: dict[str, str] = {}
    system_text = _content_text(body.get("system"))
    if system_text:
        out.append({"role": "system", "content": system_text})
    messages = body.get("messages")
    if not isinstance(messages, list):
        return out
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user")
        content = msg.get("content")
        if isinstance(content, str):
            out.append({"role": role if role in ("user", "assistant") else "user", "content": content})
            continue
        if not isinstance(content, list):
            continue
        if role == "assistant":
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                typ = block.get("type")
                if typ == "text" and isinstance(block.get("text"), str):
                    text_parts.append(block["text"])
                elif typ == "thinking" and isinstance(block.get("thinking"), str):
                    reasoning_parts.append(block["thinking"])
                elif typ == "tool_use" and block.get("id") and block.get("name"):
                    tool_names_by_id[str(block["id"])] = str(block["name"])
                    tool_calls.append({
                        "id": str(block["id"]),
                        "type": "function",
                        "function": {
                            "name": str(block["name"]),
                            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        },
                    })
            item: dict[str, Any] = {"role": "assistant",
                                    "content": "\n".join(text_parts) or ("" if reasoning_parts else None)}
            if preserve_reasoning and reasoning_parts:
                reasoning_text = "".join(reasoning_parts)
                item["reasoning_content"] = reasoning_text
                if reasoning_details:
                    item["reasoning_details"] = [{"type": "text", "text": reasoning_text}]
            if tool_calls:
                item["tool_calls"] = tool_calls
            out.append(item)
            continue
        pending_parts: list[dict[str, Any]] = []
        for block in content:
            part = _anthropic_block_to_openai_part(block)
            typ = block.get("type") if isinstance(block, dict) else None
            if part:
                pending_parts.append(part)
            elif typ == "tool_result" and block.get("tool_use_id"):
                if pending_parts:
                    out.append({"role": "user", "content": _openai_parts_to_content(pending_parts)})
                    pending_parts = []
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": str(block["tool_use_id"]),
                    "content": _anthropic_content_to_openai_content(block.get("content")),
                }
                name = tool_names_by_id.get(str(block["tool_use_id"]))
                if include_tool_names and name:
                    tool_msg["name"] = name
                out.append(tool_msg)
        if pending_parts:
            out.append({"role": "user", "content": _openai_parts_to_content(pending_parts)})
    return out


def _is_kimi_host(host: str) -> bool:
    low = host.lower()
    return "moonshot" in low or "kimi" in low


def _is_deepseek_host(host: str) -> bool:
    return "deepseek" in host.lower()


def _is_minimax_host(host: str) -> bool:
    low = host.lower()
    return "minimax" in low or "minimaxi" in low


def _is_kimi_model(model: str) -> bool:
    return strip_context_suffix(model).lower().startswith("kimi-")


def _kimi_always_thinking(model: str) -> bool:
    return "kimi-k2.7-code" in strip_context_suffix(model).lower()


def _openai_tool_choice_is_forced(choice: Any) -> bool:
    return choice == "required" or isinstance(choice, dict)


def _normalize_kimi_tool_choice(model: str, tool_choice: Any) -> Any:
    if _kimi_always_thinking(model) and _openai_tool_choice_is_forced(tool_choice):
        return "auto"
    return tool_choice


def _kimi_thinking_payload(model: str, thinking: Any) -> dict[str, Any] | None:
    if not isinstance(thinking, dict):
        return None
    # Kimi K2.7 Code always thinks and the docs say not to pass `thinking`.
    if _kimi_always_thinking(model):
        return None
    typ = thinking.get("type")
    if typ not in ("enabled", "disabled"):
        return None
    out = {"type": typ}
    if typ == "enabled" and thinking.get("keep") == "all":
        out["keep"] = "all"
    return out


def _deepseek_thinking_payload(thinking: Any) -> dict[str, Any] | None:
    if not isinstance(thinking, dict):
        return None
    typ = thinking.get("type")
    if typ == "disabled":
        return {"type": "disabled"}
    if typ in ("enabled", "adaptive", "auto"):
        out = {"type": "enabled"}
        effort = thinking.get("reasoning_effort") or thinking.get("effort")
        if effort in ("high", "max", "low", "medium", "xhigh"):
            out["reasoning_effort"] = effort
        return out
    return None


def _minimax_thinking_payload(thinking: Any) -> dict[str, Any] | None:
    if not isinstance(thinking, dict):
        return None
    typ = thinking.get("type")
    if typ == "disabled":
        return {"type": "disabled"}
    if typ in ("adaptive", "enabled", "auto"):
        return {"type": "adaptive"}
    return None


def _anthropic_to_openai_request(body: dict[str, Any], provider_model: str, host: str) -> dict[str, Any]:
    model = provider_model or strip_context_suffix(str(body.get("model") or ""))
    is_kimi = _is_kimi_host(host)
    is_deepseek = _is_deepseek_host(host)
    is_minimax = _is_minimax_host(host)
    is_kimi_model = is_kimi and _is_kimi_model(model)
    out: dict[str, Any] = {
        "model": model,
        "messages": _anthropic_messages_to_openai(body, preserve_reasoning=is_kimi or is_deepseek or is_minimax,
                                                  reasoning_details=is_minimax,
                                                  include_tool_names=is_kimi),
    }
    field_map = {
        "max_tokens": "max_tokens",
        "temperature": "temperature",
        "top_p": "top_p",
        "stream": "stream",
    }
    for src, dst in field_map.items():
        if src in body:
            # Kimi K2.x has fixed sampling defaults; forwarding arbitrary Claude
            # Science temperature/top_p values can make Moonshot reject the call.
            if is_kimi_model and src in ("temperature", "top_p"):
                continue
            out[dst] = body[src]
    if body.get("stop_sequences"):
        out["stop"] = body["stop_sequences"]
    tools = _anthropic_tools_to_openai(body.get("tools"))
    if tools:
        out["tools"] = tools
    tool_choice = _anthropic_tool_choice_to_openai(body.get("tool_choice"))
    if is_kimi_model:
        tool_choice = _normalize_kimi_tool_choice(model, tool_choice)
    if tool_choice is not None:
        out["tool_choice"] = tool_choice
    # Kimi exposes reasoning via `reasoning_content`. Its `thinking.type` accepts
    # enabled/disabled, not Anthropic/MiniMax's adaptive mode, so omit auto/adaptive.
    if is_kimi:
        th = _kimi_thinking_payload(model, body.get("thinking"))
        # Kimi thinking mode only allows tool_choice auto/none. Claude Science may
        # force a tool via Anthropic's `any`/`tool`; disable thinking to keep the
        # tool call request valid when the model supports disabling it.
        if is_kimi_model and _openai_tool_choice_is_forced(tool_choice) and not _kimi_always_thinking(model):
            th = {"type": "disabled"}
        if th:
            out["thinking"] = th
    elif is_deepseek:
        th = _deepseek_thinking_payload(body.get("thinking"))
        if th:
            out["thinking"] = th
    elif is_minimax:
        th = _minimax_thinking_payload(body.get("thinking"))
        if th:
            out["thinking"] = th
        out["reasoning_split"] = True
    return out


def _openai_stop_reason(reason: Any, has_tools: bool = False) -> str:
    if has_tools or reason == "tool_calls":
        return "tool_use"
    if reason == "length":
        return "max_tokens"
    if reason == "stop":
        return "end_turn"
    return "end_turn"


def _openai_tool_content(tool_call: dict[str, Any]) -> dict[str, Any] | None:
    fn = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    name = fn.get("name")
    if not name:
        return None
    args = fn.get("arguments") or "{}"
    if isinstance(args, str):
        with contextlib.suppress(Exception):
            args = json.loads(args or "{}")
    if not isinstance(args, dict):
        args = {}
    return {
        "type": "tool_use",
        "id": str(tool_call.get("id") or ("toolu_" + secrets.token_hex(8))),
        "name": str(name),
        "input": args,
    }


def _openai_reasoning_details_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = item.get("text") or item.get("content")
            if isinstance(text, str) and text:
                parts.append(text)
    return "".join(parts)


def _openai_reasoning_text(node: dict[str, Any]) -> str:
    for key in ("reasoning_content", "reasoning", "reasoning_text"):
        val = node.get(key)
        if isinstance(val, str) and val:
            return val
    return _openai_reasoning_details_text(node.get("reasoning_details"))


def _openai_stream_reasoning_delta(node: dict[str, Any], previous_details_text: str) -> tuple[str, str]:
    for key in ("reasoning_content", "reasoning", "reasoning_text"):
        val = node.get(key)
        if isinstance(val, str) and val:
            return val, previous_details_text
    current = _openai_reasoning_details_text(node.get("reasoning_details"))
    if not current:
        return "", previous_details_text
    if previous_details_text and current.startswith(previous_details_text):
        return current[len(previous_details_text):], current
    return current, current


def _openai_to_anthropic_response(blob: bytes, req_model: str) -> bytes:
    data = json.loads(blob.decode("utf-8"))
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content: list[dict[str, Any]] = []
    reasoning = _openai_reasoning_text(message)
    if reasoning:
        content.append({"type": "thinking", "thinking": reasoning, "signature": ""})
    text = message.get("content")
    if isinstance(text, str) and text:
        content.append({"type": "text", "text": text})
    for tool_call in message.get("tool_calls") or []:
        if isinstance(tool_call, dict):
            block = _openai_tool_content(tool_call)
            if block:
                content.append(block)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    out = {
        "id": str(data.get("id") or ("msg_" + secrets.token_hex(12))),
        "type": "message",
        "role": "assistant",
        "model": str(data.get("model") or req_model),
        "content": content,
        "stop_reason": _openai_stop_reason(choice.get("finish_reason"), any(c.get("type") == "tool_use" for c in content)),
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }
    return json.dumps(out, ensure_ascii=False).encode("utf-8")


def _sse_event(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def _iter_openai_sse_payloads(chunks: Any) -> Any:
    buf = b""
    while True:
        chunk = chunks.read(4096)
        if not chunk:
            break
        buf += chunk
        buf = buf.replace(b"\r\n", b"\n")
        while b"\n\n" in buf:
            raw, buf = buf.split(b"\n\n", 1)
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith(b"data:"):
                    payload = line[5:].strip()
                    if payload:
                        yield payload
    for line in buf.splitlines():
        line = line.strip()
        if line.startswith(b"data:"):
            payload = line[5:].strip()
            if payload:
                yield payload


def _write_chunk(wfile: Any, chunk: bytes) -> None:
    if not chunk:
        return
    wfile.write(hex(len(chunk))[2:].encode() + b"\r\n" + chunk + b"\r\n")
    wfile.flush()


def thirdparty_forwarder_base_url(port: int = THIRDPARTY_FWD_PORT) -> str:
    return f"http://127.0.0.1:{port}"


def _open_upstream(req: urllib.request.Request, timeout: int = 300) -> Any:
    """Open the connection to the third-party provider.

    Verify TLS by default, but many third-party relays (中转) serve a
    self-signed / private-CA certificate chain. urllib then raises
    CERTIFICATE_VERIFY_FAILED, which operon surfaces to the user as
    "Claude is temporarily unavailable — retrying". Since this forwarder is
    bound to localhost and the provider is one the user explicitly configured
    (their own base_url + key), fall back to an unverified connection on a cert
    verification error — the same posture as `curl -k`. Set
    CCSCIENCE_TP_STRICT_TLS=1 to keep verification strict and fail loudly."""
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        raise  # a real HTTP status from the provider — surface it as-is
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        cert_error = isinstance(reason, ssl.SSLCertVerificationError) or \
            "CERTIFICATE_VERIFY_FAILED" in str(reason)
        strict = os.environ.get("CCSCIENCE_TP_STRICT_TLS", "").lower() in ("1", "true", "yes")
        if not cert_error or strict:
            raise
        insecure = ssl.create_default_context()
        insecure.check_hostname = False
        insecure.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=timeout, context=insecure)


# The real model ids seen in upstream responses. operon always sends a claude-*
# id; the provider maps it to its own model and echoes the real one back (and it
# can differ per tier, e.g. opus->deepseek-v4-pro, haiku->deepseek-v4-flash). We
# surface these to the web UI (see /thirdparty-label) so the model picker shows
# the model actually answering, not the Claude tier label.
_LAST_UPSTREAM_MODEL = ""
_TIER_MODELS: dict[str, str] = {}  # claude-* request id -> real response model
_LAST_PROVIDER_STATE = ""  # detect CC.Switch provider/model switches to purge stale names

_PROVIDER_BRANDS = {
    "deepseek": "DeepSeek", "minimaxi": "MiniMax", "minimax": "MiniMax",
    "moonshot": "Moonshot", "kimi": "Kimi", "bigmodel": "GLM", "zhipu": "GLM",
    "dashscope": "Qwen", "qwen": "Qwen", "siliconflow": "SiliconFlow",
    "openrouter": "OpenRouter", "openai": "OpenAI", "anthropic": "Anthropic",
}


def _provider_brand(host: str) -> str:
    """A human brand for a provider host, e.g. api.deepseek.com -> "DeepSeek"."""
    low = (host or "").lower()
    for key, brand in _PROVIDER_BRANDS.items():
        if key in low:
            return brand
    parts = [p for p in low.split(".") if p and p not in
             ("api", "www", "gateway", "com", "cn", "net", "io", "ai", "co", "org")]
    return parts[0].capitalize() if parts else "Third-Party"


def _pretty_model(brand: str, model: str) -> str:
    """Human label for the model picker, e.g. ("DeepSeek","deepseek-v4-pro") ->
    "DeepSeek V4 Pro". Falls back to the brand when no model is known yet."""
    if not model:
        return brand or "Third-Party"
    words = []
    for tok in re.split(r"[-_ ]+", model):
        if not tok:
            continue
        if brand and tok.lower() == brand.lower():
            words.append(brand)
        elif len(tok) <= 4 and re.fullmatch(r"[a-z]?\d[\w.]*", tok.lower()):
            words.append(tok.upper())          # version tokens: v4, m2, 4o ...
        else:
            words.append(tok.capitalize())
    return " ".join(words) or (brand or model)


def _record_upstream_model(req_model: str, blob: bytes) -> None:
    """Capture the real model id from an upstream response body / SSE chunk and
    remember which claude-* tier it answered for."""
    global _LAST_UPSTREAM_MODEL
    m = re.search(rb'"model"\s*:\s*"([^"]+)"', blob or b"")
    if not m:
        return
    val = m.group(1).decode("utf-8", "replace").strip()
    if not val:
        return
    _LAST_UPSTREAM_MODEL = val
    if req_model:
        _TIER_MODELS[req_model] = val


class ThirdpartyForwardHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ccscience-forwarder"

    def log_message(self, *a: Any) -> None:
        pass

    def _reply(self, code: int, body: bytes, ct: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        # The injected web-UI script reads /thirdparty-label cross-origin
        # (operon page on :8990 -> forwarder on :19784); allow it. Harmless for
        # the server-to-server /v1/* responses.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        with contextlib.suppress(OSError):
            self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/health":
            self._reply(200, json.dumps({
                "ok": True,
                "adapter": "thirdparty-forwarder",
                "version": VERSION,
                "forwarder_revision": THIRDPARTY_FWD_REVISION,
                "pid": os.getpid(),
            }).encode())
            return
        # operon fetches <ANTHROPIC_BASE_URL>/v1/models to learn which models are
        # runnable; if that fetch fails it marks every model "unavailable" and
        # rejects requests. Answer with the Claude tier ids operon already knows
        # — third-party endpoints (DeepSeek/MiniMax) map claude-* to their own
        # models, so these stay valid targets.
        if self.path.startswith("/v1/models"):
            models = [{"type": "model", "id": mid, "display_name": name}
                      for mid, name in (("claude-opus-4-8", "Claude Opus 4.8"),
                                        ("claude-sonnet-5", "Claude Sonnet 5"),
                                        ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
                                        ("claude-haiku-4-5", "Claude Haiku 4.5"))]
            self._reply(200, json.dumps({"data": models, "has_more": False}).encode())
            return
        if self.path.startswith("/thirdparty-label"):
            # The injected web-UI script asks who is really answering, so the
            # model picker can show the provider's model instead of "Opus 4.8".
            # `tiers` maps each claude-* id to the real model it answered with
            # (may differ per tier); `display` is the fallback for tiers not yet
            # seen. Names only — the id the UI sends stays claude-*.
            global _LAST_PROVIDER_STATE, _LAST_UPSTREAM_MODEL, _TIER_MODELS
            brand = ""
            provider = thirdparty_provider_details()
            prov_base = provider.get("base_url", "") if provider else ""
            prov_model = provider.get("model", "") if provider else ""
            if provider:
                brand = _provider_brand(_url_host(prov_base))
            # When the user switches CC.Switch profiles or models (e.g. DeepSeek
            # Pro -> Flash), old process-level model names are stale. Drop them
            # so the UI falls back to the current provider/model until a new
            # request repopulates tier-specific real names.
            state = prov_base + "\n" + prov_model
            if prov_base and state != _LAST_PROVIDER_STATE:
                _LAST_PROVIDER_STATE = state
                _LAST_UPSTREAM_MODEL = ""
                _TIER_MODELS.clear()
            tiers = {cid: _pretty_model(brand, real) for cid, real in _TIER_MODELS.items()}
            fallback_model = _LAST_UPSTREAM_MODEL or prov_model
            self._reply(200, json.dumps({
                "brand": brand,
                "display": _pretty_model(brand, fallback_model),
                "tiers": tiers,
                # Only the no-login sandbox routes through us; the injected script
                # uses this to avoid relabelling the *real* Claude Science UI (a
                # different port) when a third-party is also configured for it.
                "sandbox_port": _int_port(os.environ.get("CCSCIENCE_SANDBOX_PORT"), SANDBOX_PORT_DEFAULT),
            }).encode())
            return
        self._reply(404, b'{"type":"error","error":{"message":"not found"}}')

    def _relay_openai_stream(self, up: Any, req_model: str, provider_model: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        message_id = "msg_" + secrets.token_hex(12)
        model = provider_model or req_model
        text_open = False
        thinking_open = False
        next_index = 0
        text_index = 0
        thinking_index = 0
        tool_buffers: dict[int, dict[str, Any]] = {}
        stop_reason = "end_turn"
        output_tokens = 0
        reasoning_details_text = ""

        start = {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }
        _write_chunk(self.wfile, _sse_event("message_start", start))
        try:
            with up:
                for payload in _iter_openai_sse_payloads(up):
                    if payload == b"[DONE]":
                        break
                    _record_upstream_model(req_model, payload)
                    try:
                        data = json.loads(payload.decode("utf-8"))
                    except Exception:
                        continue
                    if data.get("model"):
                        model = str(data["model"])
                    usage = data.get("usage")
                    if isinstance(usage, dict):
                        output_tokens = int(usage.get("completion_tokens") or output_tokens)
                    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
                    if not choices:
                        continue
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                    reasoning, reasoning_details_text = _openai_stream_reasoning_delta(delta, reasoning_details_text)
                    if reasoning:
                        if not thinking_open:
                            thinking_index = next_index
                            next_index += 1
                            _write_chunk(self.wfile, _sse_event("content_block_start", {
                                "type": "content_block_start",
                                "index": thinking_index,
                                "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                            }))
                            thinking_open = True
                        _write_chunk(self.wfile, _sse_event("content_block_delta", {
                            "type": "content_block_delta",
                            "index": thinking_index,
                            "delta": {"type": "thinking_delta", "thinking": reasoning},
                        }))
                    text = delta.get("content")
                    if isinstance(text, str) and text:
                        if thinking_open:
                            _write_chunk(self.wfile, _sse_event("content_block_stop", {
                                "type": "content_block_stop",
                                "index": thinking_index,
                            }))
                            thinking_open = False
                        if not text_open:
                            text_index = next_index
                            next_index += 1
                            _write_chunk(self.wfile, _sse_event("content_block_start", {
                                "type": "content_block_start",
                                "index": text_index,
                                "content_block": {"type": "text", "text": ""},
                            }))
                            text_open = True
                        _write_chunk(self.wfile, _sse_event("content_block_delta", {
                            "type": "content_block_delta",
                            "index": text_index,
                            "delta": {"type": "text_delta", "text": text},
                        }))
                    for tool_delta in delta.get("tool_calls") or []:
                        if not isinstance(tool_delta, dict):
                            continue
                        idx = int(tool_delta.get("index") or 0)
                        buf = tool_buffers.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tool_delta.get("id"):
                            buf["id"] = str(tool_delta["id"])
                        fn = tool_delta.get("function") if isinstance(tool_delta.get("function"), dict) else {}
                        if fn.get("name"):
                            buf["name"] = str(fn["name"])
                        if isinstance(fn.get("arguments"), str):
                            buf["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        stop_reason = _openai_stop_reason(choice.get("finish_reason"), bool(tool_buffers))
            if thinking_open:
                _write_chunk(self.wfile, _sse_event("content_block_stop", {
                    "type": "content_block_stop",
                    "index": thinking_index,
                }))
            if text_open:
                _write_chunk(self.wfile, _sse_event("content_block_stop", {
                    "type": "content_block_stop",
                    "index": text_index,
                }))
            for _, buf in sorted(tool_buffers.items()):
                args_json = str(buf.get("arguments") or "{}")
                with contextlib.suppress(Exception):
                    parsed_args = json.loads(args_json)
                    if isinstance(parsed_args, dict):
                        args_json = json.dumps(parsed_args, ensure_ascii=False, separators=(",", ":"))
                block = {
                    "type": "tool_use",
                    "id": str(buf.get("id") or ("toolu_" + secrets.token_hex(8))),
                    "name": str(buf.get("name") or "tool"),
                    "input": {},
                }
                idx = next_index
                next_index += 1
                _write_chunk(self.wfile, _sse_event("content_block_start", {
                    "type": "content_block_start",
                    "index": idx,
                    "content_block": block,
                }))
                _write_chunk(self.wfile, _sse_event("content_block_delta", {
                    "type": "content_block_delta",
                    "index": idx,
                    "delta": {"type": "input_json_delta", "partial_json": args_json},
                }))
                _write_chunk(self.wfile, _sse_event("content_block_stop", {
                    "type": "content_block_stop",
                    "index": idx,
                }))
            _write_chunk(self.wfile, _sse_event("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": output_tokens},
            }))
            _write_chunk(self.wfile, _sse_event("message_stop", {"type": "message_stop"}))
            self.wfile.write(b"0\r\n\r\n")
        except (OSError, http.client.HTTPException):
            # Upstream relay closed mid-stream (IncompleteRead is an
            # HTTPException, not an OSError) or operon hung up. Swallow it like a
            # client disconnect instead of letting the worker thread traceback.
            pass

    def do_POST(self) -> None:
        provider = thirdparty_provider_details()
        if not provider:
            self._reply(503, b'{"type":"error","error":{"message":"no third-party provider configured"}}')
            return
        base, key = provider["base_url"], provider["key"]
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b"{}"
        stream = "text/event-stream" in (self.headers.get("Accept") or "")
        req_model = ""
        provider_model = ""
        openai_mode = _is_openai_compatible_base(base)
        try:
            body = json.loads(raw)
            req_model = str(body.get("model") or "")
            normalize_thirdparty_request(body, _url_host(base))
            provider_model = _provider_model_for_request(req_model, base, provider.get("model", ""))
            if provider_model:
                body["model"] = provider_model
            stream = bool(body.get("stream"))
            if self.path.startswith("/v1/messages/count_tokens"):
                self._reply(200, json.dumps({
                    "input_tokens": estimate_anthropic_input_tokens(body),
                }).encode())
                return
            if openai_mode:
                body = _anthropic_to_openai_request(body, provider_model, _url_host(base))
            raw = json.dumps(body, ensure_ascii=False).encode()
        except (ValueError, TypeError):
            pass  # forward non-JSON verbatim
        if openai_mode:
            url = _openai_chat_url(base)
            headers = {"content-type": "application/json", "authorization": f"Bearer {key}"}
        else:
            url = _anthropic_endpoint_url(base, self.path)
            headers = {"content-type": "application/json", "anthropic-version": "2023-06-01",
                       "x-api-key": key, "authorization": f"Bearer {key}"}
            beta = self.headers.get("anthropic-beta")
            if beta:
                headers["anthropic-beta"] = beta
        req = urllib.request.Request(url, data=raw, method="POST", headers=headers)
        try:
            up = _open_upstream(req, timeout=300)
        except urllib.error.HTTPError as exc:
            self._reply(exc.code, exc.read(), exc.headers.get("Content-Type", "application/json"))
            return
        except Exception as exc:  # noqa: BLE001 — surface any network error to the client
            self._reply(502, json.dumps({"type": "error", "error": {"message": str(exc)}}).encode())
            return
        ct = up.headers.get("Content-Type", "application/json")
        if not stream:
            with up:
                data = up.read()
            _record_upstream_model(req_model, data)  # note the real model that answered
            if openai_mode:
                try:
                    data = _openai_to_anthropic_response(data, req_model)
                    ct = "application/json"
                except Exception as exc:
                    self._reply(502, json.dumps({"type": "error", "error": {"message": str(exc)}}).encode())
                    return
            self._reply(up.getcode() or 200, data, ct)
            return
        if openai_mode:
            self._relay_openai_stream(up, req_model, provider_model)
            return
        # Streaming: relay the upstream SSE with chunked transfer, like CSSwitch.
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        sniffed = False
        try:
            with up:
                while True:
                    chunk = up.read(4096)
                    if not chunk:
                        break
                    if not sniffed:
                        # message_start (first event) carries the real model id.
                        _record_upstream_model(req_model, chunk)
                        sniffed = True
                    _write_chunk(self.wfile, chunk)
            self.wfile.write(b"0\r\n\r\n")
        except (OSError, http.client.HTTPException):
            pass  # client hung up, or upstream relay closed mid-stream (IncompleteRead)


def serve_thirdparty_forwarder(port: int = THIRDPARTY_FWD_PORT) -> None:
    with contextlib.suppress(OSError):
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), ThirdpartyForwardHandler)
        httpd.serve_forever()


def _thirdparty_forwarder_health(port: int = THIRDPARTY_FWD_PORT) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.6) as res:
            status = getattr(res, "status", None) or res.getcode()
            if status != 200:
                return None
            payload = json.loads(res.read(4096).decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def thirdparty_forwarder_healthy(port: int = THIRDPARTY_FWD_PORT) -> bool:
    payload = _thirdparty_forwarder_health(port)
    return bool(
        payload
        and payload.get("ok") is True
        and payload.get("adapter") == "thirdparty-forwarder"
        and payload.get("version") == VERSION
        and payload.get("forwarder_revision") == THIRDPARTY_FWD_REVISION
    )


def _listening_pids_on_port(port: int) -> list[int]:
    if is_windows():
        try:
            completed = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2,
            )
        except Exception:
            return []
        pids: list[int] = []
        for line in completed.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].lower() != "tcp" or parts[-2].upper() != "LISTENING":
                continue
            local_addr, pid_text = parts[1], parts[-1]
            if local_addr.endswith(f":{port}"):
                with contextlib.suppress(ValueError):
                    pids.append(int(pid_text))
        return list(dict.fromkeys(pids))
    if not shutil.which("lsof"):
        return []
    try:
        completed = subprocess.run(
            ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2,
        )
    except Exception:
        return []
    pids = []
    for line in completed.stdout.splitlines():
        with contextlib.suppress(ValueError):
            pids.append(int(line.strip()))
    return list(dict.fromkeys(pids))


def _process_command(pid: int) -> str:
    if is_windows():
        try:
            completed = subprocess.run(
                ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/value"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2,
            )
        except Exception:
            return ""
        for line in completed.stdout.splitlines():
            if line.startswith("CommandLine="):
                return line.partition("=")[2].strip()
        return ""
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2,
        )
    except Exception:
        return ""
    return completed.stdout.strip()


def _looks_like_ccscience_process(command: str) -> bool:
    value = command.lower()
    return any(marker in value for marker in (
        "serve-forwarder",
        "ccscience_sync.py",
        "ccscience_sync",
        "ccscience-sync",
    ))


def _terminate_process_on_port(port: int = THIRDPARTY_FWD_PORT) -> bool:
    """Best-effort cleanup for an old ccscience-sync forwarder occupying a port."""
    sent_signal = False
    current_pid = os.getpid()
    for pid in _listening_pids_on_port(port):
        if pid == current_pid:
            continue
        command = _process_command(pid)
        if not command or not _looks_like_ccscience_process(command):
            continue
        try:
            if is_windows():
                subprocess.run(["taskkill", "/PID", str(pid), "/T"], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=2)
            else:
                os.kill(pid, signal.SIGTERM)
            sent_signal = True
        except Exception:
            continue
    if not sent_signal:
        return False
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if not _listening_pids_on_port(port):
            return True
        time.sleep(0.1)
    return True


def forwarder_command() -> list[str]:
    executable = ensure_frozen_install_target() if is_frozen() else pathlib.Path(sys.executable)
    if is_frozen():
        return [str(executable), "serve-forwarder"]
    return [str(executable), str(pathlib.Path(__file__).resolve()), "serve-forwarder"]


def ensure_thirdparty_forwarder() -> None:
    """Make sure our hidden forwarder is listening; spawn a detached one if not.
    It also runs inside the always-on helper, so normally it is already up."""
    if thirdparty_forwarder_healthy():
        return
    _terminate_process_on_port(THIRDPARTY_FWD_PORT)
    if thirdparty_forwarder_healthy():
        return
    with contextlib.suppress(Exception):
        subprocess.Popen(forwarder_command(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        if thirdparty_forwarder_healthy():
            return
        time.sleep(0.1)
    raise SystemExit("third-party forwarder did not become ready")


def thirdparty_target() -> dict[str, Any] | None:
    """Decide how the no-login sandbox reaches a third-party model.

    Priority 1 — DIRECT (self-contained, no CSSwitch needed): a provider entry
    that ccswitch / Claude Code wrote into ~/.claude/settings.json.env
    (ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY). Inference
    goes through our localhost forwarder, which injects the key at request time.
    Priority 2 — CSSWITCH-PROXY: a running CSSwitch local proxy holds the key.
    Returns None when neither source is available."""
    provider = thirdparty_provider_details()
    if provider:
        base, key = provider["base_url"], provider["key"]
        settings = load_json(claude_settings_path(), {})
        model = provider.get("model") or (strip_context_suffix(str(settings.get("model") or "")) if isinstance(settings, dict) else "")
        digest = hashlib.sha256((base + "\n" + key + "\n" + model).encode("utf-8")).hexdigest()[:16]
        # Route through OUR local forwarder (it normalizes the request + injects
        # the key), not straight at the provider.
        return {"mode": "direct", "base_url": thirdparty_forwarder_base_url(),
                "provider_base": base, "access_token": None, "model": model,
                "host": "127.0.0.1", "id": f"direct:{digest}"}
    config = load_csswitch_config()
    proxy_url = csswitch_proxy_url(config)
    bridge = csswitch_bridge_payload(check_health=True)
    if bridge.get("enabled") and bridge.get("proxy_running") and proxy_url:
        return {"mode": "csswitch-proxy", "base_url": proxy_url, "access_token": None,
                "model": str(bridge.get("model") or ""), "host": _proxy_hostport(proxy_url),
                "id": f"proxy:{proxy_url}"}
    return None


def open_thirdparty(lang: str = "en", restart: bool = False) -> tuple[str, dict[str, Any]]:
    """Forge + launch (or reuse) the isolated no-login sandbox pointed at a
    third-party model, then return a fresh browser URL. Prefers a self-contained
    direct provider (ccswitch/Claude Code env); otherwise a running CSSwitch
    local proxy."""
    target = thirdparty_target()
    if not target:
        raise SystemExit(tr(lang, "thirdparty_needs_source"))
    if target["mode"] == "direct":
        # Our hidden forwarder must be up before the daemon points at it.
        ensure_thirdparty_forwarder()
    port = _int_port(os.environ.get("CCSCIENCE_SANDBOX_PORT"), SANDBOX_PORT_DEFAULT)
    running = sandbox_daemon_status().get("running")
    # A live daemon has its target baked in at launch; if the target changed
    # (proxy endpoint, or the direct provider/key), reuse would misroute
    # inference, so restart to pick up the new one.
    stale = running and launched_proxy_url() not in (None, target["id"])
    if restart or stale:
        stop_sandbox_daemon()
        running = False
    if not running:
        start_sandbox_daemon(port, target, lang)
    url = sandbox_url(port, target)
    # Never hand the real key back to callers/log output.
    return url, {"mode": target["mode"], "base_url": target["base_url"],
                 "model": target["model"], "host": target["host"]}


def strip_context_suffix(model: str) -> str:
    return re.sub(r"\[[^\]]+\]$", "", model.strip())


def normalize_model(model: str | None) -> str | None:
    if not model:
        return None
    model = strip_context_suffix(model)
    model = re.sub(r"^(?:[a-z-]+/)+", "", model, flags=re.I)
    return model.strip()


def map_model(source_model: str | None, config: dict[str, Any]) -> str | None:
    source = normalize_model(source_model)
    if not source:
        return None

    overrides = config.get("model_map", {})
    if isinstance(overrides, dict):
        for key in (source_model, source, source.lower()):
            if isinstance(key, str) and key in overrides and overrides[key]:
                return str(overrides[key])

    low = source.lower()
    if low.startswith("claude-") and "[" not in low:
        return source
    if "opus" in low:
        return "claude-opus-4-8"
    if "sonnet-5" in low or low == "sonnet" or "sonnet" in low and "4" not in low:
        return "claude-sonnet-5"
    if "sonnet-4-6" in low or "4.6" in low:
        return "claude-sonnet-4-6"
    if "sonnet-4" in low:
        return "claude-sonnet-4-6"
    if "haiku" in low:
        return "claude-haiku-4-5"
    if "fable" in low:
        return "claude-fable-5"
    return source


def map_effort(value: str | None) -> str | None:
    if not value:
        return None
    low = value.strip().lower()
    aliases = {
        "low": "low",
        "medium": "medium",
        "med": "medium",
        "high": "high",
        "max": "high",
    }
    return aliases.get(low)


def current_model_payload() -> dict[str, Any]:
    settings = load_json(claude_settings_path(), {})
    if not isinstance(settings, dict):
        settings = {}
    config = load_user_config()
    bridge = csswitch_bridge_payload(check_health=False)
    source_model = settings.get("model")
    source_effort = settings.get("effortLevel") or settings.get("effort")
    # ccswitch writes a self-contained provider entry into settings.json.env
    # (ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN + ANTHROPIC_DEFAULT_*_MODEL).
    # When present, ccswitch is asking us to route inference to that provider.
    # Normal signed-in launches can pass it through natively; no-login launches
    # use our localhost forwarder so provider quirks can be normalized.
    env_block = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    selected_provider = thirdparty_provider_details()
    active_profile = csswitch_active_profile(load_csswitch_config())
    if selected_provider and selected_provider.get("source") == "claude-settings" and active_profile and \
            _csswitch_provider_spec(active_profile) and not _provider_matches_profile(
                selected_provider.get("base_url", ""), active_profile
            ) and _settings_provider_newer_than_csswitch():
        bridge["stale"] = True
    direct_base = selected_provider["base_url"] if selected_provider else ""
    direct_key_env = selected_provider.get("key_env", "") if selected_provider else (
        "ANTHROPIC_AUTH_TOKEN" if env_block.get("ANTHROPIC_AUTH_TOKEN") else (
            "ANTHROPIC_API_KEY" if env_block.get("ANTHROPIC_API_KEY") else ""
        )
    )
    # ccswitch / Claude Code is the model source of truth: the injected value must
    # be a valid Claude Science model id (claude-*). When ccswitch sets a
    # per-tier override (ANTHROPIC_DEFAULT_<TIER>_MODEL), surface it so the UI
    # label is honest; otherwise inject the mapped Claude Science tier id.
    direct_tier_model = ""
    if selected_provider and selected_provider.get("model"):
        direct_tier_model = selected_provider["model"]
    elif direct_base:
        tier = strip_context_suffix(str(source_model) or "").lower()
        for key, value in env_block.items():
            if not isinstance(value, str) or not value:
                continue
            if not key.startswith("ANTHROPIC_DEFAULT_") or not key.endswith("_MODEL"):
                continue
            tier_name = key[len("ANTHROPIC_DEFAULT_"):-len("_MODEL")].lower()
            if tier and tier_name == tier:
                direct_tier_model = strip_context_suffix(value)
                break
    source = "claude-settings"
    target_model = map_model(str(source_model) if source_model else None, config)
    if not target_model and bridge.get("enabled") and bridge.get("model"):
        source = "csswitch-profile"
        source_model = bridge.get("model")
        target_model = str(bridge.get("model") or "")
    target_effort = map_effort(str(source_effort) if source_effort else None)
    return {
        "ok": bool(target_model),
        "source": source,
        "source_model": source_model,
        "model": target_model,
        "source_effort": source_effort,
        "effort": target_effort,
        "settings_path": str(claude_settings_path()),
        "csswitch": bridge,
        "upstream_mode": "direct" if selected_provider else "csswitch-proxy",
        "upstream_source": selected_provider.get("source", "") if selected_provider else "",
        "upstream_base_url": direct_base,
        "upstream_provider_model": direct_tier_model,
        "upstream_key_env": direct_key_env or "",
        "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


def runtime_indexes() -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    for data_dir in science_data_dirs():
        pattern = str(data_dir / "runtime" / "*" / "web-dist" / "index.html")
        paths.extend(pathlib.Path(p) for p in glob.glob(pattern))
    paths = _unique_paths(paths)
    paths.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return paths


def injection_script(port: int) -> str:
    endpoint = f"http://127.0.0.1:{port}/model"
    label_endpoint = f"http://127.0.0.1:{THIRDPARTY_FWD_PORT}/thirdparty-label"
    return f"""{MARKER_START}
    <script>
      (function () {{
        var endpoint = {json.dumps(endpoint)};
        var labelEndpoint = {json.dumps(label_endpoint)};
        var modelKey = "operon-default-model";
        var effortKey = "operon-default-effort";
        var currentModel = null;
        var currentEffort = null;
        var syncTimer = null;

        function apply(payload) {{
          if (!payload || !payload.model) return;
          currentModel = String(payload.model);
          try {{ localStorage.setItem(modelKey, currentModel); }} catch (e) {{}}
          if (payload.effort) {{
            currentEffort = String(payload.effort);
            try {{ localStorage.setItem(effortKey, currentEffort); }} catch (e) {{}}
          }}
        }}

        function syncBlocking() {{
          try {{
            var xhr = new XMLHttpRequest();
            xhr.open("GET", endpoint, false);
            xhr.setRequestHeader("Accept", "application/json");
            xhr.send(null);
            if (xhr.status >= 200 && xhr.status < 300) {{
              apply(JSON.parse(xhr.responseText));
            }}
          }} catch (e) {{}}
        }}

        function syncAsync() {{
          try {{
            fetch(endpoint, {{ cache: "no-store" }})
              .then(function (r) {{ return r.ok ? r.json() : null; }})
              .then(apply)
              .catch(function () {{}});
          }} catch (e) {{}}
        }}

        function scheduleSync() {{
          if (syncTimer) return;
          syncTimer = setTimeout(function () {{
            syncTimer = null;
            syncAsync();
          }}, 50);
        }}

        function modelFromStorage() {{
          try {{ return currentModel || localStorage.getItem(modelKey); }}
          catch (e) {{ return currentModel; }}
        }}

        function effortFromStorage() {{
          try {{ return currentEffort || localStorage.getItem(effortKey); }}
          catch (e) {{ return currentEffort; }}
        }}

        function patchRequest(input, init) {{
          var body = init && init.body;
          var model = modelFromStorage();
          if (model && typeof body === "string" && body.charAt(0) === "{{") {{
            var parsed = JSON.parse(body);
            parsed.model = model;
            var effort = effortFromStorage();
            if (effort) parsed.effort = effort;
            return Object.assign({{}}, init, {{ body: JSON.stringify(parsed) }});
          }}
          return init;
        }}

        function shouldPatch(url) {{
          try {{
            var u = new URL(url, location.href);
            if (u.origin !== location.origin) return false;
            return /\\/request$/.test(u.pathname) ||
              /\\/frames\\/[^/]+\\/(aside|resume|fork)$/.test(u.pathname);
          }} catch (e) {{
            return false;
          }}
        }}

        // The model picker's names come from operon's own /api/models. When a
        // third-party provider is answering, relabel those names to the real
        // model (id stays claude-* so requests are unaffected — display only).
        function isModelsUrl(url) {{
          try {{
            var u = new URL(url, location.href);
            return u.origin === location.origin && /\\/api\\/models$/.test(u.pathname);
          }} catch (e) {{ return false; }}
        }}

        function relabelModels(payload, label) {{
          if (!payload || !label) return payload;
          // Only relabel the no-login sandbox UI (the port the forwarder serves),
          // never the real Claude Science UI running on another port.
          if (label.sandbox_port &&
              String(location.port) !== String(label.sandbox_port)) return payload;
          var tiers = label.tiers || {{}};
          var fallback = label.display || label.brand;
          try {{
            var groups = payload.models;
            if (groups) {{
              Object.keys(groups).forEach(function (k) {{
                var list = groups[k];
                if (Array.isArray(list)) {{
                  list.forEach(function (m) {{
                    if (!m || !m.id) return;
                    var name = tiers[m.id] || fallback;
                    if (name) m.name = name;
                  }});
                }}
              }});
            }}
          }} catch (e) {{}}
          return payload;
        }}

        syncBlocking();
        try {{ window.addEventListener("focus", scheduleSync); }} catch (e) {{}}
        try {{
          document.addEventListener("visibilitychange", function () {{
            if (!document.hidden) scheduleSync();
          }});
        }} catch (e) {{}}
        try {{ document.addEventListener("pointerdown", scheduleSync, true); }} catch (e) {{}}
        try {{ document.addEventListener("keydown", scheduleSync, true); }} catch (e) {{}}

        var originalFetch = window.fetch;
        if (originalFetch && !originalFetch.__ccscienceSyncPatched) {{
          var patchedFetch = function (input, init) {{
            try {{
              var self = this;
              var url = typeof input === "string" ? input : input && input.url;
              var method = (init && init.method) ||
                (input && input.method) ||
                "GET";
              if (url && String(method).toUpperCase() === "GET" && isModelsUrl(url)) {{
                return originalFetch.call(window, labelEndpoint, {{ cache: "no-store" }})
                  .then(function (r) {{ return r.ok ? r.json() : null; }})
                  .catch(function () {{ return null; }})
                  .then(function (label) {{
                    return originalFetch.call(self, input, init).then(function (resp) {{
                      if (!resp.ok || !label) return resp;
                      return resp.clone().json().then(function (payload) {{
                        var relabeled = JSON.stringify(relabelModels(payload, label));
                        return new Response(relabeled, {{
                          status: resp.status,
                          statusText: resp.statusText,
                          headers: {{ "Content-Type": "application/json" }}
                        }});
                      }}).catch(function () {{ return resp; }});
                    }});
                  }});
              }}
              if (url && String(method).toUpperCase() !== "GET" && shouldPatch(url)) {{
                return originalFetch.call(window, endpoint, {{ cache: "no-store" }})
                  .then(function (r) {{ return r.ok ? r.json() : null; }})
                  .then(function (payload) {{
                    apply(payload);
                    return originalFetch.call(self, input, patchRequest(input, init));
                  }})
                  .catch(function () {{
                    return originalFetch.call(self, input, patchRequest(input, init));
                  }});
              }}
            }} catch (e) {{}}
            return originalFetch.call(this, input, init);
          }};
          patchedFetch.__ccscienceSyncPatched = true;
          window.fetch = patchedFetch;
        }}
      }})();
    </script>
{MARKER_END}"""


def patch_index(path: pathlib.Path, port: int) -> str:
    text = path.read_text(encoding="utf-8")
    script = injection_script(port)
    if MARKER_START in text and MARKER_END in text:
        new_text = re.sub(
            re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
            script,
            text,
            flags=re.S,
        )
        action = "updated"
    else:
        backup = path.with_suffix(path.suffix + ".ccscience-sync.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        match = re.search(r"\n\s*<script type=\"module\"[^>]+assets/index-[^\"]+\.js\"></script>", text)
        if not match:
            raise SystemExit(f"Could not find Claude Science module script in {path}")
        new_text = text[: match.start()] + "\n" + script + text[match.start() :]
        action = "installed"
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return action


def unpatch_index(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    if MARKER_START not in text:
        return "not-installed"
    new_text = re.sub(
        r"\n?\s*" + re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        "",
        text,
        flags=re.S,
    )
    path.write_text(new_text, encoding="utf-8")
    return "removed"


class ModelHandler(http.server.BaseHTTPRequestHandler):
    server_version = "ccscience-sync/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type")
        self.send_header("Cache-Control", "no-store")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] not in ("/model", "/health"):
            self.send_response(404)
            self.cors()
            self.end_headers()
            self.wfile.write(b"not found\n")
            return
        payload = current_model_payload()
        if self.path.startswith("/health"):
            payload = {"ok": True, "model": payload.get("model")}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(port: int) -> None:
    # Host the hidden third-party forwarder alongside the model helper so the
    # no-login sandbox has it available without a separate process.
    threading.Thread(target=serve_thirdparty_forwarder, daemon=True).start()
    address = ("127.0.0.1", port)
    httpd = http.server.ThreadingHTTPServer(address, ModelHandler)
    print(f"ccscience-sync serving on http://127.0.0.1:{port}/model", flush=True)
    httpd.serve_forever()


def run(cmd: list[str], check: bool = False, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check, env=env)


def helper_command(port: int, background: bool = False) -> list[str]:
    executable = ensure_frozen_install_target() if is_frozen() else pathlib.Path(sys.executable)
    if is_frozen():
        return [str(executable), "serve", "--port", str(port)]
    if background and is_windows() and executable.name.lower() == "python.exe":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
    return [str(executable), str(pathlib.Path(__file__).resolve()), "serve", "--port", str(port)]


def install_launch_agent(port: int) -> str:
    plist = launch_agent_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)
    data = {
        "Label": MACOS_LABEL,
        "ProgramArguments": helper_command(port),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
        "WorkingDirectory": str(pathlib.Path(__file__).resolve().parent),
    }
    plist.write_bytes(plistlib.dumps(data))
    uid = str(os.getuid())
    run(["launchctl", "bootout", f"gui/{uid}", str(plist)])
    boot = run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)])
    if boot.returncode != 0:
        return f"written, but launchctl bootstrap failed: {boot.stderr.strip() or boot.stdout.strip()}"
    kick = run(["launchctl", "kickstart", "-k", f"gui/{uid}/{MACOS_LABEL}"])
    if kick.returncode != 0:
        return f"loaded, but kickstart failed: {kick.stderr.strip() or kick.stdout.strip()}"
    return "loaded"


def uninstall_launch_agent(label: str = MACOS_LABEL) -> str:
    plist = launch_agent_path(label)
    uid = str(os.getuid())
    run(["launchctl", "bootout", f"gui/{uid}", str(plist)])
    if plist.exists():
        plist.unlink()
        return "removed"
    return "not-installed"


def vbs_quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def windows_startup_script(port: int) -> str:
    command = " ".join(vbs_quote(part) for part in helper_command(port, background=True))
    return "\r\n".join(
        [
            "Set shell = CreateObject(\"WScript.Shell\")",
            f"shell.Run {vbs_quote(command)}, 0, False",
            "",
        ]
    )


def install_windows_startup(port: int) -> str:
    if not is_windows():
        return "unsupported"
    path = windows_startup_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    app_data_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(windows_startup_script(port), encoding="utf-8")
    start = run(["wscript.exe", str(path)])
    if start.returncode != 0:
        return f"written, but start failed: {start.stderr.strip() or start.stdout.strip()}"
    return "installed"


def uninstall_windows_startup() -> str:
    path = windows_startup_path()
    if path.exists():
        path.unlink()
        return "removed"
    return "not-installed"


def install_autostart(port: int) -> str:
    if is_macos():
        return install_launch_agent(port)
    if is_windows():
        return install_windows_startup(port)
    return "unsupported on this platform; run 'ccscience-sync serve' manually"


def uninstall_autostart() -> str:
    if is_macos():
        return uninstall_launch_agent()
    if is_windows():
        return uninstall_windows_startup()
    return "unsupported"


def autostart_status() -> str:
    if is_macos():
        plist = launch_agent_path()
        if plist.exists():
            return f"installed ({plist})"
        return f"not-installed ({plist})"
    if is_windows():
        path = windows_startup_path()
        return f"{'installed' if path.exists() else 'not-installed'} ({path})"
    return "unsupported"


def helper_status(port: int) -> str:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/model", timeout=1.0) as res:
            payload = json.loads(res.read().decode("utf-8"))
        return f"running ({payload.get('model') or 'no model'})"
    except Exception:
        return "not-running"


def patch_status(path: pathlib.Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "missing"
    return "installed" if MARKER_START in text else "not-installed"


def cmd_model(_: argparse.Namespace) -> int:
    print(json.dumps(current_model_payload(), ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    serve(args.port)
    return 0


def cmd_serve_forwarder(args: argparse.Namespace) -> int:
    serve_thirdparty_forwarder(args.port)
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    indexes = runtime_indexes()
    if not indexes:
        searched = "\n  ".join(str(path) for path in science_data_dirs())
        raise SystemExit(f"No Claude Science runtime index.html found under:\n  {searched}")
    targets = indexes if args.all else indexes[:1]
    for path in targets:
        print(f"{patch_index(path, args.port)}: {path}")
    if not args.no_agent:
        print(f"autostart: {install_autostart(args.port)}")
        time.sleep(0.5)
        print(f"helper: {helper_status(args.port)}")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    for path in runtime_indexes():
        print(f"{unpatch_index(path)}: {path}")
    if not args.keep_agent:
        print(f"autostart: {uninstall_autostart()}")
    print(f"thirdparty sandbox: {stop_sandbox_daemon()}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    payload = current_model_payload()
    bridge = csswitch_bridge_payload(check_health=True)
    print(f"source model: {payload.get('source_model')}")
    print(f"science model: {payload.get('model')}")
    print(f"effort: {payload.get('effort')}")
    if bridge.get("enabled"):
        stale_note = " (stale local config; using newer Claude settings)" if payload.get("csswitch", {}).get("stale") else ""
        print(f"csswitch profile: {bridge.get('profile') or bridge.get('template_id') or 'unknown'}{stale_note}")
        print(f"csswitch model: {bridge.get('model') or '(uses Claude Code model)'}")
        print(f"csswitch proxy: {'running' if bridge.get('proxy_running') else 'not-running'} ({bridge.get('proxy_url') or bridge.get('config_path')})")
    else:
        print(f"csswitch proxy: disabled ({bridge.get('mode')})")
    if payload.get("upstream_source"):
        print(f"thirdparty provider: {payload.get('upstream_source')} ({payload.get('upstream_base_url')})")
        print(f"thirdparty model: {payload.get('upstream_provider_model') or '(uses request model)'}")
        print(f"thirdparty key: {payload.get('upstream_key_env') or '(configured)'}")
        health = _thirdparty_forwarder_health()
        if health:
            print(f"thirdparty forwarder: running (rev {health.get('forwarder_revision')}, pid {health.get('pid')})")
        else:
            print("thirdparty forwarder: not-running")
    sandbox = sandbox_daemon_status()
    if sandbox.get("running"):
        print(f"thirdparty sandbox: running (port {sandbox.get('port')})")
    else:
        forged = sandbox_has_valid_token(sandbox_data_dir())
        print(f"thirdparty sandbox: not-running ({'forged' if forged else 'not-forged'})")
    print(f"helper: {helper_status(args.port)}")
    print(f"autostart: {autostart_status()}")
    indexes = runtime_indexes()
    if not indexes:
        searched = ", ".join(str(path) for path in science_data_dirs())
        print(f"runtime: not found under {searched}")
    for path in indexes[:5]:
        print(f"runtime patch: {patch_status(path)} ({path})")
    return 0


def cmd_open_science(args: argparse.Namespace) -> int:
    lang = detect_language()
    env, _bridge = science_launch_environment()
    if env and env.get("ANTHROPIC_BASE_URL") == thirdparty_forwarder_base_url():
        ensure_thirdparty_forwarder()
    url = fresh_claude_science_url(lang, env=env)
    if args.print_only:
        print(url)
    else:
        webbrowser.open(url)
        print(f"opened: {url}")
    return 0


def cmd_open_thirdparty(args: argparse.Namespace) -> int:
    lang = detect_language()
    url, _bridge = open_thirdparty(lang, restart=args.restart)
    if args.print_only:
        print(url)
    else:
        webbrowser.open(url)
        print(f"opened: {url}")
    return 0


def cmd_stop_thirdparty(_: argparse.Namespace) -> int:
    print(f"thirdparty sandbox: {stop_sandbox_daemon()}")
    return 0


def capture_output(func: Any) -> tuple[int, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = func()
            code = int(result or 0)
        except SystemExit as exc:
            code = int(exc.code or 0) if isinstance(exc.code, int) else 1
            if exc.code and not isinstance(exc.code, int):
                print(exc.code, file=sys.stderr)
        except Exception:
            code = 1
            traceback.print_exc()
    output = stdout.getvalue()
    errors = stderr.getvalue()
    return code, (output + errors).strip()


def localize_cli_output(text: str, lang: str) -> str:
    if lang != "zh":
        return text
    replacements = [
        ("source model:", "来源模型："),
        ("science model:", "Claude Science 模型："),
        ("csswitch profile:", "CSSwitch 配置："),
        ("csswitch model:", "CSSwitch 模型："),
        ("csswitch proxy:", "CSSwitch 代理："),
        ("thirdparty provider:", "第三方来源："),
        ("thirdparty model:", "第三方模型："),
        ("thirdparty key:", "第三方密钥来源："),
        ("thirdparty forwarder:", "第三方转发器："),
        ("thirdparty sandbox:", "第三方免登录沙箱："),
        ("not-forged", "未伪造登录"),
        ("forged", "已伪造登录"),
        ("effort:", "推理强度："),
        ("helper:", "后台服务："),
        ("autostart:", "自启动："),
        ("runtime patch:", "运行时补丁："),
        ("runtime:", "运行时："),
        ("updated:", "已更新："),
        ("not-installed:", "未安装："),
        ("installed:", "已安装："),
        ("removed:", "已移除："),
        ("not-running", "未运行"),
        ("disabled", "未启用"),
        ("unknown", "未知"),
        ("(stale local config; using newer Claude settings)", "（本地配置已旧，正在使用更新的 Claude settings）"),
        ("(uses Claude Code model)", "（使用 Claude Code 模型）"),
        ("not-installed", "未安装"),
        ("running", "运行中"),
        ("installed", "已安装"),
        ("loaded", "已加载"),
        ("missing", "缺失"),
        ("not found under", "未找到，已搜索"),
        ("no model", "没有模型"),
    ]
    localized = text
    for old, new in replacements:
        localized = localized.replace(old, new)
    return localized.replace("： ", "：")


def gui_install(lang: str) -> tuple[int, str]:
    code, text = capture_output(lambda: cmd_install(argparse.Namespace(port=DEFAULT_PORT, all=False, no_agent=False)))
    return code, localize_cli_output(text, lang)


def gui_status(lang: str) -> tuple[int, str]:
    code, text = capture_output(lambda: cmd_status(argparse.Namespace(port=DEFAULT_PORT)))
    return code, localize_cli_output(text, lang)


def gui_open_science(lang: str) -> tuple[int, str]:
    def action() -> int:
        url, bridge = open_claude_science(lang)
        if bridge.get("enabled") and bridge.get("proxy_running"):
            model = bridge.get("model") or tr(lang, "no_output")
            print(tr(lang, "bridge_active", profile=bridge.get("profile") or "CSSwitch", model=model))
        else:
            print(tr(lang, "bridge_inactive"))
        print(tr(lang, "opened_science", url=url))
        return 0

    code, text = capture_output(action)
    return code, text


def gui_open_thirdparty(lang: str) -> tuple[int, str]:
    def action() -> int:
        url, bridge = open_thirdparty(lang)
        # The CLI path (cmd_open_thirdparty) opens the browser itself; the GUI
        # button must do the same so a click actually lands the user in the
        # no-login web UI instead of only printing the URL.
        with contextlib.suppress(Exception):
            webbrowser.open(url)
        print(tr(lang, "opened_thirdparty", url=url, email=VIRTUAL_EMAIL,
                 model=bridge.get("model") or "CSSwitch"))
        return 0

    return capture_output(action)


def gui_uninstall(lang: str) -> tuple[int, str]:
    code, text = capture_output(lambda: cmd_uninstall(argparse.Namespace(keep_agent=False)))
    return code, localize_cli_output(text, lang)


def launch_gui() -> int:
    lang = detect_language()
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except Exception as exc:
        print(tr(lang, "gui_error", error=exc), file=sys.stderr)
        print(tr(lang, "gui_fallback"), file=sys.stderr)
        return 2

    root = tk.Tk()
    root.title(f"ccscience-sync {VERSION}")
    root.geometry("720x520")
    root.minsize(640, 440)

    # Give the window / Dock / taskbar the app icon. On packaged macOS the .app
    # already gets its icon from the bundled .icns; iconphoto covers the source
    # run and the Windows title bar / taskbar. Best-effort: never block the GUI.
    with contextlib.suppress(Exception):
        icon_file = resource_path("icon.png")
        if icon_file is not None:
            icon_image = tk.PhotoImage(file=str(icon_file))
            root.iconphoto(True, icon_image)
            root._app_icon = icon_image  # keep a reference so Tk doesn't GC it

    title = ttk.Label(root, text="ccscience-sync", font=("TkDefaultFont", 18, "bold"))
    title.pack(anchor="w", padx=18, pady=(16, 4))

    subtitle = ttk.Label(
        root,
        text=tr(lang, "subtitle"),
        wraplength=660,
    )
    subtitle.pack(anchor="w", padx=18, pady=(0, 14))

    style = ttk.Style()
    with contextlib.suppress(Exception):
        style.configure("Primary.TButton", font=("TkDefaultFont", 14, "bold"), padding=(12, 10))
        style.configure("Use.TButton", font=("TkDefaultFont", 12), padding=(8, 6))

    # Primary call-to-action: the one button a first-time user must click.
    primary_frame = ttk.Frame(root)
    primary_frame.pack(fill="x", padx=18, pady=(0, 8))

    # Secondary "use it" actions.
    use_frame = ttk.Frame(root)
    use_frame.pack(fill="x", padx=18, pady=(0, 10))

    output = tk.Text(root, height=12, wrap="char")
    output.pack(fill="both", expand=True, padx=18, pady=(0, 8))

    # Utility actions, kept visually quiet so beginners are not overwhelmed.
    util_frame = ttk.Frame(root)
    util_frame.pack(fill="x", padx=18, pady=(0, 8))

    status_var = tk.StringVar(value=tr(lang, "ready"))
    status = ttk.Label(root, textvariable=status_var)
    status.pack(anchor="w", padx=18, pady=(0, 12))

    buttons: list[ttk.Button] = []

    def set_output(text: str) -> None:
        output.configure(state="normal")
        output.delete("1.0", "end")
        output.insert("1.0", text or tr(lang, "no_output"))
        output.configure(state="disabled")

    def set_busy(is_busy: bool) -> None:
        for button in buttons:
            button.configure(state="disabled" if is_busy else "normal")

    def run_action(label: str, action: Any) -> None:
        status_var.set(f"{label}...")
        set_busy(True)
        set_output("")

        def worker() -> None:
            code, text = action()

            def finish() -> None:
                set_output(text)
                set_busy(False)
                if code == 0:
                    status_var.set(tr(lang, "finished", action=label))
                    if label == tr(lang, "install_action"):
                        messagebox.showinfo(
                            "ccscience-sync",
                            tr(lang, "installed_message"),
                        )
                else:
                    status_var.set(tr(lang, "failed", action=label))
                    messagebox.showerror("ccscience-sync", text or tr(lang, "failed", action=label))

            root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    install_button = ttk.Button(
        primary_frame,
        text=tr(lang, "install_primary"),
        style="Primary.TButton",
        command=lambda: run_action(tr(lang, "install_action"), lambda: gui_install(lang)),
    )
    install_button.pack(fill="x")

    open_science_button = ttk.Button(
        use_frame,
        text=tr(lang, "open_science"),
        style="Use.TButton",
        command=lambda: run_action(tr(lang, "open_science_action"), lambda: gui_open_science(lang)),
    )
    open_thirdparty_button = ttk.Button(
        use_frame,
        text=tr(lang, "open_thirdparty"),
        style="Use.TButton",
        command=lambda: run_action(tr(lang, "open_thirdparty_action"), lambda: gui_open_thirdparty(lang)),
    )
    open_science_button.pack(side="left", fill="x", expand=True, padx=(0, 6))
    open_thirdparty_button.pack(side="left", fill="x", expand=True)

    status_button = ttk.Button(
        util_frame,
        text=tr(lang, "status"),
        command=lambda: run_action(tr(lang, "status_action"), lambda: gui_status(lang)),
    )
    uninstall_button = ttk.Button(
        util_frame,
        text=tr(lang, "uninstall"),
        command=lambda: run_action(tr(lang, "uninstall_action"), lambda: gui_uninstall(lang)),
    )
    quit_button = ttk.Button(util_frame, text=tr(lang, "quit"), command=root.destroy)
    status_button.pack(side="left")
    uninstall_button.pack(side="left", padx=(8, 0))
    quit_button.pack(side="right")

    for button in (install_button, open_science_button, open_thirdparty_button,
                   status_button, uninstall_button, quit_button):
        buttons.append(button)

    set_output(tr(lang, "initial"))
    root.after(200, lambda: run_action(tr(lang, "status_action"), lambda: gui_status(lang)))
    root.mainloop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync ccswitch/Claude Code model into Claude Science")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("model", help="print the current mapped model as JSON")
    p.set_defaults(func=cmd_model)

    p = sub.add_parser("serve", help="run the localhost model helper")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("serve-forwarder", help="run the hidden third-party normalizing forwarder")
    p.add_argument("--port", type=int, default=THIRDPARTY_FWD_PORT)
    p.set_defaults(func=cmd_serve_forwarder)

    p = sub.add_parser("install", help="patch Claude Science and install the helper autostart entry")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--all", action="store_true", help="patch all installed runtime builds")
    p.add_argument("--no-agent", action="store_true", help="only patch index.html; kept for backward compatibility")
    p.add_argument("--no-autostart", dest="no_agent", action="store_true", help="only patch index.html")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall", help="remove the patch and helper autostart entry")
    p.add_argument("--keep-agent", action="store_true")
    p.add_argument("--keep-autostart", dest="keep_agent", action="store_true")
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("status", help="show sync status")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("open-science", help="open Claude Science with a fresh one-time URL")
    p.add_argument("--print-only", action="store_true", help="print the URL instead of opening a browser")
    p.set_defaults(func=cmd_open_science)

    p = sub.add_parser(
        "open-thirdparty",
        help="open an isolated no-login Claude Science that uses your CSSwitch third-party API",
    )
    p.add_argument("--print-only", action="store_true", help="print the URL instead of opening a browser")
    p.add_argument("--restart", action="store_true", help="restart the sandbox daemon before opening")
    p.set_defaults(func=cmd_open_thirdparty)

    p = sub.add_parser("stop-thirdparty", help="stop the isolated no-login Claude Science sandbox")
    p.set_defaults(func=cmd_stop_thirdparty)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        return launch_gui()
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
