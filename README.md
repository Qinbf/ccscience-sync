# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

**Use any model you picked in CC.Switch inside Claude Science.** Install once, then
switch models freely — no reinstalling.

A tiny desktop app. **No Python, no terminal.** Download it, open it, click one button.

For screenshot-based steps, see the [English quick guide](docs/USER_GUIDE.md) or
[中文图文说明](docs/USER_GUIDE.zh-CN.md).

## What it does

Claude Science normally runs only the official Claude models. This app makes it follow
**whatever you chose in CC.Switch** instead:

- **Official Claude** — Opus, Sonnet, Haiku.
- **Third-party models** — DeepSeek, Kimi (Moonshot), GLM (Zhipu), MiniMax, and more.
  The app quietly translates each provider's format for you, so they just work.

Pick a model in CC.Switch → open a new Claude Science session → it uses that model.
**Install once; after that, switching models never needs a reinstall.**

## Install (3 steps)

First: open Claude Science once (then you can close it), and pick your model in CC.Switch.

**macOS**
1. Download [ccscience-sync-macos.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-macos.zip) and unzip it
2. Open `ccscience-sync.app`
3. Click **`①  Install / Update`** — done ✅

> Blocked on first open? That's normal — this app is free and unsigned. On newer macOS:
> `System Settings → Privacy & Security → Open Anyway`. On older macOS: right-click the
> app → `Open`. More cases in [docs/INSTALL.md](docs/INSTALL.md).

**Windows**
1. Download [ccscience-sync-windows.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-windows.zip) and unzip it
2. Open `ccscience-sync.exe`
3. Click **`①  Install / Update`** — done ✅

> If Windows SmartScreen appears → `More info` → `Run anyway`.

## Everyday use

1. Switch models in **CC.Switch**
2. Click **`Open Claude Science`** in this app
3. The new session uses the model you just picked — no reinstall, nothing to change

To confirm it's installed, click **`Check Status`** and look for:

```text
helper: running (...)
runtime patch: installed (...)
```

You only click `Install / Update` **again** when Claude Science itself updates to a new
version (Check Status then shows `runtime patch: not-installed`). Switching models never
needs it.

## No Claude account? Use "Third-Party (No Login)"

Only for people with **no Claude account** but who do have a third-party API key (e.g.
DeepSeek, MiniMax). **With a Claude account, skip this.**

1. Pick a third-party model in CC.Switch
2. Click **`Third-Party (No Login)`** in this app
3. Claude Science opens ready to use — no account, no sign-in screen

It runs a **separate, isolated** copy of Claude Science (its own folder and port — it never
touches your real login) and routes requests through this app's own built-in local
forwarder straight to your third-party API. Your key stays on your machine. Click
`Uninstall` to stop it.

## Common questions

**Claude Science asks me to log in.** The local link is one-time and can expire. Click
**`Open Claude Science`** for a fresh one. It uses your real Claude account and does not
bypass sign-in. No account? Use "Third-Party (No Login)" above.

**"Claude Science runtime not found."** Open Claude Science once, close it, then click
`Install / Update` again.

**The model didn't change.** Start a **new** session — sessions already open keep the model
they started with. Switching never needs a reinstall.

**The OS warns the app is unverified.** This release is unsigned, so macOS/Windows show a
one-time warning — normal for a small open-source app. Allow it as shown above. It does not
read or upload your keys.

## Uninstall

Open the app and click **`Uninstall`**.

## Names (don't mix them up)

- **CC.Switch (cc-switch)** — the app **you** use to switch models / set up a third-party
  API. It decides which model Claude Code and Claude Science use. This is the only thing
  ccscience-sync works with.
- **Claude Science** — the app whose model this tool redirects.

## Run from source (developers)

```sh
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
python3 ccscience_sync.py            # open the GUI
python3 ccscience_sync.py install    # or via CLI
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
