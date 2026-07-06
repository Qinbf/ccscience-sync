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
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
import webbrowser
from typing import Any


APP_NAME = "ccscience-sync"
VERSION = "0.4.0"
DEFAULT_PORT = 19783
THIRDPARTY_FWD_PORT = 19784  # our own hidden normalizing forwarder (no CSSwitch)
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
            "Third-party no-login mode needs a third-party model source.\n"
            "Either configure a third-party API (base URL + key) in ccswitch / Claude Code, "
            "or open CSSwitch, pick a profile, and keep its local proxy running. Then try again."
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
            "第三方免登录需要一个第三方模型来源。\n"
            "在 ccswitch / Claude Code 里配好第三方 API（base_url + key），"
            "或打开 CSSwitch 选一个配置并保持其本地代理运行，然后重试。"
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


def csswitch_active_profile(config: dict[str, Any]) -> dict[str, Any] | None:
    active_id = str(config.get("active_id") or "")
    profiles = config.get("profiles")
    if not active_id or not isinstance(profiles, list):
        return None
    for profile in profiles:
        if isinstance(profile, dict) and profile.get("id") == active_id:
            return profile
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
    model = str(profile.get("model") or "").strip() if profile else ""
    payload = {
        "enabled": enabled,
        "mode": mode or "missing",
        "profile": str(profile.get("name") or profile.get("template_id") or "") if profile else "",
        "template_id": str(profile.get("template_id") or "") if profile else "",
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
    # If ccswitch wrote its own ANTHROPIC_* env (e.g. MiniMax direct), honor it
    # verbatim and skip the CSSwitch proxy — ccswitch is the authority for that
    # provider and the proxy would just double-route.
    settings = load_json(claude_settings_path(), {})
    env_block = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    direct_base = str(env_block.get("ANTHROPIC_BASE_URL") or "").strip()
    if direct_base:
        env = dict(os.environ)
        env["ANTHROPIC_BASE_URL"] = direct_base
        if env_block.get("ANTHROPIC_AUTH_TOKEN"):
            env["ANTHROPIC_AUTH_TOKEN"] = str(env_block["ANTHROPIC_AUTH_TOKEN"])
        elif env_block.get("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = str(env_block["ANTHROPIC_API_KEY"])
        # Forward every other ANTHROPIC_* override ccswitch set (provider-specific
        # default models, timeouts, beta flags, etc.).
        for key, value in env_block.items():
            if isinstance(value, str) and key.startswith("ANTHROPIC_"):
                env[key] = value
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
# OAuth session: a token whose access_token the CSSwitch proxy strips anyway,
# with a far-future expiry so it is never refreshed online. All inference then
# flows to ANTHROPIC_BASE_URL (the CSSwitch proxy), which swaps in the real
# third-party key. This never touches the real ~/.claude-science.
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

    In self-contained direct mode, access_token is the real third-party API key:
    Claude Science resolves credentials OAuth-only and sends this token as the
    request Authorization, so embedding the key here lets inference reach the
    provider with no proxy in the path. When omitted, a throwaway placeholder is
    used (the CSSwitch proxy swaps in the real key instead)."""
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
        # Self-contained direct mode: the real third-party key rides inside the
        # forged OAuth token, so the daemon talks straight to the provider. Point
        # https_proxy at a dead local port so the blocking Anthropic oauth/profile
        # probe fails instantly (daemon treats itself as logged-out), and put the
        # provider host in no_proxy so inference bypasses that dead proxy and
        # reaches the provider directly. No CSSwitch, no proxy process.
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
    access_token = str(target.get("access_token") or "")
    if access_token:
        # Direct mode: refresh the token so it carries the current real key (a
        # stale throwaway token from a prior proxy-mode run must not linger).
        # force=False REUSES the existing encryption.key so it stays consistent
        # with the daemon's macOS-Keychain copy — regenerating the key would make
        # the daemon fall back to the stale keychain key ("ensureEncryptionKeys:
        # ... using the macOS Keychain copy") and fail to read the forged token.
        forge_virtual_oauth(sandbox_data_dir(), access_token=access_token, force=False)
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
    thinking.type "auto" -> "adaptive" (DeepSeek/MiniMax accept adaptive); for
    DeepSeek a forced tool_choice conflicts with thinking, so disable it."""
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


def thirdparty_provider() -> tuple[str, str] | None:
    """(base_url, key) for the direct third-party. Priority: an explicit env
    override (CCSCIENCE_TP_BASE / CCSCIENCE_TP_KEY — also the test hook), then the
    provider entry ccswitch / Claude Code wrote into ~/.claude/settings.json.env."""
    base = os.environ.get("CCSCIENCE_TP_BASE", "").strip()
    key = os.environ.get("CCSCIENCE_TP_KEY", "").strip()
    if base and key:
        return base, key
    settings = load_json(claude_settings_path(), {})
    if not isinstance(settings, dict):
        settings = {}
    env_block = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    base = str(env_block.get("ANTHROPIC_BASE_URL") or "").strip()
    key = str(env_block.get("ANTHROPIC_AUTH_TOKEN") or env_block.get("ANTHROPIC_API_KEY") or "").strip()
    return (base, key) if base and key else None


class ThirdpartyForwardHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ccscience-forwarder"

    def log_message(self, *a: Any) -> None:
        pass

    def _reply(self, code: int, body: bytes, ct: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        with contextlib.suppress(OSError):
            self.wfile.write(body)

    def do_GET(self) -> None:
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
        self._reply(404, b'{"type":"error","error":{"message":"not found"}}')

    def do_POST(self) -> None:
        prov = thirdparty_provider()
        if not prov:
            self._reply(503, b'{"type":"error","error":{"message":"no third-party provider configured"}}')
            return
        base, key = prov
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b"{}"
        stream = "text/event-stream" in (self.headers.get("Accept") or "")
        try:
            body = json.loads(raw)
            normalize_thirdparty_request(body, _url_host(base))
            stream = bool(body.get("stream"))
            raw = json.dumps(body).encode()
        except (ValueError, TypeError):
            pass  # forward non-JSON verbatim
        url = base.rstrip("/") + (self.path if self.path.startswith("/") else "/" + self.path)
        headers = {"content-type": "application/json", "anthropic-version": "2023-06-01",
                   "x-api-key": key, "authorization": f"Bearer {key}"}
        beta = self.headers.get("anthropic-beta")
        if beta:
            headers["anthropic-beta"] = beta
        req = urllib.request.Request(url, data=raw, method="POST", headers=headers)
        try:
            up = urllib.request.urlopen(req, timeout=300)
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
            self._reply(up.getcode() or 200, data, ct)
            return
        # Streaming: relay the upstream SSE with chunked transfer, like CSSwitch.
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            with up:
                while True:
                    chunk = up.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(hex(len(chunk))[2:].encode() + b"\r\n" + chunk + b"\r\n")
                    self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        except OSError:
            pass  # client hung up mid-stream


def serve_thirdparty_forwarder(port: int = THIRDPARTY_FWD_PORT) -> None:
    with contextlib.suppress(OSError):
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), ThirdpartyForwardHandler)
        httpd.serve_forever()


def thirdparty_forwarder_healthy(port: int = THIRDPARTY_FWD_PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


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
    with contextlib.suppress(Exception):
        subprocess.Popen(forwarder_command(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        if thirdparty_forwarder_healthy():
            return
        time.sleep(0.1)


def thirdparty_target() -> dict[str, Any] | None:
    """Decide how the no-login sandbox reaches a third-party model.

    Priority 1 — DIRECT (self-contained, no CSSwitch needed): a provider entry
    that ccswitch / Claude Code wrote into ~/.claude/settings.json.env
    (ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY). The key gets
    embedded in the forged login and inference goes straight to the provider.
    Priority 2 — CSSWITCH-PROXY: a running CSSwitch local proxy holds the key.
    Returns None when neither source is available."""
    prov = thirdparty_provider()
    if prov:
        base, key = prov
        settings = load_json(claude_settings_path(), {})
        model = strip_context_suffix(str(settings.get("model") or "")) if isinstance(settings, dict) else ""
        digest = hashlib.sha256((base + "\n" + key).encode("utf-8")).hexdigest()[:16]
        # Route through OUR local forwarder (it normalizes the request + injects
        # the key), not straight at the provider.
        return {"mode": "direct", "base_url": f"http://127.0.0.1:{THIRDPARTY_FWD_PORT}",
                "provider_base": base, "access_token": key, "model": model,
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
    # When present, ccswitch is asking us to route inference directly to that
    # provider — bypass the CSSwitch proxy and let Science talk to it natively.
    env_block = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    direct_base = str(env_block.get("ANTHROPIC_BASE_URL") or "").strip()
    direct_key_env = "ANTHROPIC_AUTH_TOKEN" if env_block.get("ANTHROPIC_AUTH_TOKEN") else (
        "ANTHROPIC_API_KEY" if env_block.get("ANTHROPIC_API_KEY") else None
    )
    # ccswitch / Claude Code is the model source of truth: the injected value must
    # be a valid Claude Science model id (claude-*). When ccswitch sets a
    # per-tier override (ANTHROPIC_DEFAULT_<TIER>_MODEL), surface it so the UI
    # label is honest; otherwise inject the mapped Claude Science tier id.
    direct_tier_model = ""
    if direct_base:
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
        "upstream_mode": "direct" if direct_base else "csswitch-proxy",
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
    return f"""{MARKER_START}
    <script>
      (function () {{
        var endpoint = {json.dumps(endpoint)};
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
        print(f"csswitch profile: {bridge.get('profile') or bridge.get('template_id') or 'unknown'}")
        print(f"csswitch model: {bridge.get('model') or '(uses Claude Code model)'}")
        print(f"csswitch proxy: {'running' if bridge.get('proxy_running') else 'not-running'} ({bridge.get('proxy_url') or bridge.get('config_path')})")
    else:
        print(f"csswitch proxy: disabled ({bridge.get('mode')})")
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
