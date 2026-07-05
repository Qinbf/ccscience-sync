#!/usr/bin/env python3
"""Sync Claude Code/ccswitch model settings into Claude Science.

The tool is intentionally small and stdlib-only. It reads
~/.claude/settings.json, exposes the mapped model on a localhost endpoint,
and injects a tiny bootstrap script into Claude Science's web entrypoint so
new Claude Science requests carry the same model.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import glob
import http.server
import io
import json
import os
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from typing import Any


APP_NAME = "ccscience-sync"
VERSION = "0.2.2"
DEFAULT_PORT = 19783
MACOS_LABEL = "io.github.ccscience-sync.helper"
MARKER_START = "<!-- ccscience-sync:start -->"
MARKER_END = "<!-- ccscience-sync:end -->"


def home() -> pathlib.Path:
    return pathlib.Path.home()


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return os.name == "nt"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


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
    source_model = settings.get("model")
    source_effort = settings.get("effortLevel") or settings.get("effort")
    target_model = map_model(str(source_model) if source_model else None, config)
    target_effort = map_effort(str(source_effort) if source_effort else None)
    return {
        "ok": bool(target_model),
        "source": "claude-settings",
        "source_model": source_model,
        "model": target_model,
        "source_effort": source_effort,
        "effort": target_effort,
        "settings_path": str(claude_settings_path()),
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
    address = ("127.0.0.1", port)
    httpd = http.server.ThreadingHTTPServer(address, ModelHandler)
    print(f"ccscience-sync serving on http://127.0.0.1:{port}/model", flush=True)
    httpd.serve_forever()


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


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
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    payload = current_model_payload()
    print(f"source model: {payload.get('source_model')}")
    print(f"science model: {payload.get('model')}")
    print(f"effort: {payload.get('effort')}")
    print(f"helper: {helper_status(args.port)}")
    print(f"autostart: {autostart_status()}")
    indexes = runtime_indexes()
    if not indexes:
        searched = ", ".join(str(path) for path in science_data_dirs())
        print(f"runtime: not found under {searched}")
    for path in indexes[:5]:
        print(f"runtime patch: {patch_status(path)} ({path})")
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


def gui_install() -> tuple[int, str]:
    return capture_output(lambda: cmd_install(argparse.Namespace(port=DEFAULT_PORT, all=False, no_agent=False)))


def gui_status() -> tuple[int, str]:
    return capture_output(lambda: cmd_status(argparse.Namespace(port=DEFAULT_PORT)))


def gui_uninstall() -> tuple[int, str]:
    return capture_output(lambda: cmd_uninstall(argparse.Namespace(keep_agent=False)))


def launch_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except Exception as exc:
        print(f"Could not start GUI: {exc}", file=sys.stderr)
        print("Run 'ccscience-sync install' from a terminal instead.", file=sys.stderr)
        return 2

    root = tk.Tk()
    root.title(f"ccscience-sync {VERSION}")
    root.geometry("720x520")
    root.minsize(640, 440)

    title = ttk.Label(root, text="ccscience-sync", font=("TkDefaultFont", 18, "bold"))
    title.pack(anchor="w", padx=18, pady=(16, 4))

    subtitle = ttk.Label(
        root,
        text="Install once. New Claude Science sessions will use the latest model selected in ccswitch / Claude Code.",
        wraplength=660,
    )
    subtitle.pack(anchor="w", padx=18, pady=(0, 14))

    button_frame = ttk.Frame(root)
    button_frame.pack(fill="x", padx=18, pady=(0, 10))

    output = tk.Text(root, height=16, wrap="word")
    output.pack(fill="both", expand=True, padx=18, pady=(0, 12))

    status_var = tk.StringVar(value="Ready")
    status = ttk.Label(root, textvariable=status_var)
    status.pack(anchor="w", padx=18, pady=(0, 12))

    buttons: list[ttk.Button] = []

    def set_output(text: str) -> None:
        output.configure(state="normal")
        output.delete("1.0", "end")
        output.insert("1.0", text or "(no output)")
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
                    status_var.set(f"{label} finished")
                    if label == "Install":
                        messagebox.showinfo(
                            "ccscience-sync",
                            "Installed. You do not need to reinstall when switching models.",
                        )
                else:
                    status_var.set(f"{label} failed")
                    messagebox.showerror("ccscience-sync", text or f"{label} failed")

            root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    install_button = ttk.Button(button_frame, text="Install / Update", command=lambda: run_action("Install", gui_install))
    status_button = ttk.Button(button_frame, text="Check Status", command=lambda: run_action("Status", gui_status))
    uninstall_button = ttk.Button(button_frame, text="Uninstall", command=lambda: run_action("Uninstall", gui_uninstall))
    quit_button = ttk.Button(button_frame, text="Quit", command=root.destroy)

    for button in (install_button, status_button, uninstall_button, quit_button):
        button.pack(side="left", padx=(0, 8))
        buttons.append(button)

    set_output(
        "Click Install / Update once to set up ccscience-sync.\n\n"
        "After installing, change models in ccswitch or Claude Code, then start a new Claude Science session. "
        "You do not need to reinstall after model changes."
    )
    root.after(200, lambda: run_action("Status", gui_status))
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
