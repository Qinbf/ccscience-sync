# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

**Make Claude Science use whatever model you picked in CC.Switch. Install once — switch models freely afterward, no reinstalling.**

A tiny desktop app: **no Python, no terminal.** Download it, open it, click one button.

## What it does

- ✅ **Supports every model CC.Switch can use** — the official Claude, plus any third-party relay you configure in CC.Switch (DeepSeek, Kimi, GLM, MiniMax, and more). Whatever you pick in CC.Switch, Claude Science uses it.
- ✅ **Install once, use forever** — after that, switch models in CC.Switch and just start a new Claude Science session; it follows along automatically. **No reinstall, no reconfiguring.**
- ✅ **Zero setup** — no Python, no terminal. Double-click the app and click once. (It shows Chinese on Chinese systems, English elsewhere.)

## Get started in 3 steps

Before you start: open Claude Science once (then you can close it); pick the model you want in CC.Switch.

### macOS

1. Download [ccscience-sync-macos.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-macos.zip) and unzip it
2. Open `ccscience-sync.app`
3. Click **`①  Install / Update`** — done ✅

> Blocked on first open? That's normal (this app is free and unsigned): on newer
> macOS, open `System Settings > Privacy & Security` and click `Open Anyway`; on
> older macOS, right-click the app → `Open`. More cases in [docs/INSTALL.md](docs/INSTALL.md).

### Windows

1. Download [ccscience-sync-windows.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-windows.zip) and unzip it
2. Open `ccscience-sync.exe`
3. Click **`①  Install / Update`** — done ✅

> If Windows SmartScreen appears → `More info` → `Run anyway`.

## Everyday use

1. Switch models in **CC.Switch**
2. Click **`Open Claude Science`** in this app to open a new session
3. The new session uses the model you just picked — **no reinstall, no settings to change**

To confirm it's installed, click **`Check Status`** and look for:

```text
helper: running (...)
runtime patch: installed (...)
```

**The only time you click `Install / Update` again** is when Claude Science itself
updates to a new version (Check Status then shows `runtime patch: not-installed`).
Switching models never needs it.

## Names (don't mix them up)

- **CC.Switch (cc-switch)** — the app **you use to switch models / configure a third-party
  API**; it decides which model or provider Claude Code and Claude Science use. **This is
  the only thing this tool works with.**

## Optional: "Third-Party (No Login)" when you have no Claude account

Only needed if you have **no Claude account** but do have a third-party model API (e.g.
DeepSeek, MiniMax). **With a Claude account, skip this section.**

1. Pick a third-party model in CC.Switch (it writes that provider's endpoint + your API key)
2. Click **`Third-Party (No Login)`** in this app
3. Claude Science opens ready to use — no account, no sign-in screen

It launches a **separate, isolated** Claude Science (its own directory and port, and it
**never touches** your real `~/.claude-science` or real login), starts it with a locally
generated virtual login, and routes inference through **this tool's own hidden local
forwarder** (which normalizes the request for your third-party endpoint and adds your key)
straight to your own third-party API. **No extra software needed.** This does **not** bypass
Anthropic account auth — inference never reaches Anthropic; the virtual login only lets the
local program start. Click `Uninstall` to stop it.

## Uninstall

Open this app and click **`Uninstall`**.

## Common problems

**Claude Science asks me to log in.**
The local link is one-time and can expire. Click **`Open Claude Science`** for a fresh
link. It uses your real Claude account and does not bypass sign-in. With no account, use
"Third-Party (No Login)" above.

**Claude Science runtime not found.**
Open Claude Science once, close it, then click **`Install / Update`** again.

**Model didn't change.**
Start a **new** Claude Science session; sessions already open keep the model they were
created with. Switching models needs no reinstall.

**The OS warns the app is risky / unverified.**
This release is unsigned, so macOS/Windows show a security warning — normal for a small
open-source app. Allow it as shown under "Get started". It does not read or upload your keys.

## Run from source (developers)

```sh
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
python3 ccscience_sync.py            # open the GUI
python3 ccscience_sync.py install    # or via CLI: install
python3 ccscience_sync.py status     # check status
python3 ccscience_sync.py uninstall  # uninstall
```

On Windows, replace `python3` with `py -3`.

## Custom model map (optional)

This tool maps the model name from CC.Switch to a Claude Science model ID. Defaults:

| Source model contains | Claude Science model |
| --- | --- |
| `opus` | `claude-opus-4-8` |
| `sonnet` | `claude-sonnet-5` |
| `sonnet-4`, `4.6` | `claude-sonnet-4-6` |
| `haiku` | `claude-haiku-4-5` |
| `fable` | `claude-fable-5` |

To customize, create `~/.ccscience-sync.json`:

```json
{
  "model_map": {
    "opus[1m]": "claude-opus-4-8",
    "sonnet[1m]": "claude-sonnet-5"
  }
}
```

## License

MIT
