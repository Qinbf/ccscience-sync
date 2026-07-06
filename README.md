# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

Use the same model in Claude Science that you selected in ccswitch, Claude
Code, or CSSwitch — and, if you have no Claude subscription, run Claude Science
entirely on your own third-party model API with no Claude sign-in.

Most users do not need Python, Terminal, PowerShell, or source code. Download
the app, open it, and click install.

Two ways to open Claude Science:

- **`Open Claude Science`** — the real instance, using your Claude account. It
  syncs the model you picked and opens a fresh one-time link. It does not bypass
  sign-in.
- **`Third-Party (No Login)`** — an isolated local instance with a locally
  generated virtual login, running entirely on your own third-party model API
  through the CSSwitch proxy. It never touches your real Claude account or
  `~/.claude-science`.

The desktop app automatically uses Chinese on Chinese systems and English on
other systems.

## One-Click Install

Before installing:

1. Open Claude Science once, then close it.
2. Make sure ccswitch, Claude Code, or CSSwitch already has the model you want selected.

### macOS

1. Download:
   [ccscience-sync-macos.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-macos.zip)
2. Unzip it.
3. Open `ccscience-sync.app`.
4. Click `Install / Update`.
5. Click `Open Claude Science` when you want a fresh Claude Science link.

If macOS blocks the app: right-click it and choose `Open`, then confirm (older
macOS); or open `System Settings > Privacy & Security`, scroll down, and click
`Open Anyway` (macOS 15 Sequoia and newer, where right-click no longer works for
unsigned apps). If it still says the app is "damaged" or cannot be opened, the
download was quarantined:
open Terminal and run
`xattr -dr com.apple.quarantine /path/to/ccscience-sync.app` (type the command
and a space, then drag the app onto the Terminal window to fill in the path),
then open it again. This app is free and unsigned, so these are one-time
first-open steps, not a virus warning.

### Windows

1. Download:
   [ccscience-sync-windows.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-windows.zip)
2. Unzip it.
3. Open `ccscience-sync.exe`.
4. Click `Install / Update`.
5. Click `Open Claude Science` when you want a fresh Claude Science link.

If Windows SmartScreen appears, choose `More info`, then `Run anyway`.

## How To Know It Worked

In the app, click `Check Status`.

You should see:

```text
helper: running (...)
runtime patch: installed (...)
```

If you use a CSSwitch third-party model, you should also see:

```text
csswitch proxy: running (http://127.0.0.1:18991/****)
csswitch model: ...
```

After that, use ccswitch or Claude Code as usual. When you start a new Claude
Science session, it should use the same model.

## Everyday Use

After installation, there is nothing else to keep open.

1. Change model in ccswitch or Claude Code.
2. Start a new Claude Science session.
3. Claude Science uses the synced model automatically.

If you use a CSSwitch third-party model:

1. Select the third-party profile in CSSwitch and keep its local proxy running.
2. Click `Open Claude Science` in `ccscience-sync`.
3. If Claude Science asks you to sign in, sign in normally. After that, model
   inference goes through the CSSwitch local proxy.

You do not need to reinstall after changing models in ccswitch or Claude Code.
The helper reads the latest model automatically when a new Claude Science
session starts.

Only run `Install / Update` again if Claude Science itself updates or status
does not show `runtime patch: installed`.

## Third-Party No-Login Mode

Use this if you do not have a Claude subscription but do have a third-party
model API key (via CSSwitch).

1. In CSSwitch, select a third-party profile and keep its local proxy running.
2. In `ccscience-sync`, click `Third-Party (No Login)`.
3. Claude Science opens ready to use — no Claude account, no sign-in screen.

What it does, precisely:

- It starts a **separate, isolated** Claude Science instance (its own HOME, data
  directory, and port — never the real port 8765) and generates a **local
  virtual login** (`virtual@localhost.invalid`) so Claude Science starts without
  a Claude account.
- All inference is routed through your CSSwitch local proxy, which removes the
  virtual credential and sends your own third-party API key to your chosen
  model.
- It **never reads, copies, modifies, or deletes** your real `~/.claude-science`
  or your real Claude login. Hard guardrails refuse to run on the real port or
  the real credential directory.

This does not bypass Anthropic account authentication on Anthropic's servers:
inference never reaches Anthropic. The virtual login only lets the local Claude
Science program start so it can talk to your third-party model.

Requirements: CSSwitch must be running with a third-party profile selected and
its local proxy healthy. If it is not, `ccscience-sync` tells you and does
nothing.

To stop the isolated instance, run `stop-thirdparty` (or `Uninstall`).

## Uninstall

Open `ccscience-sync` and click `Uninstall`.

## Common Problems

### Claude Science asks me to log in

Claude Science's local browser link is a one-time link and can expire. Open
`ccscience-sync` and click `Open Claude Science` to generate and open a fresh
link.

If Claude Science asks for your Claude account, sign in normally. `Open Claude
Science` uses your real Claude account and does not bypass that sign-in.

If you have no Claude account, use `Third-Party (No Login)` instead: it runs a
separate isolated instance on your own third-party model API. See
[Third-Party No-Login Mode](#third-party-no-login-mode).

### Claude Science runtime not found

Open Claude Science once, close it, then click `Install / Update` again.

### Model did not change

Start a new Claude Science session. Existing sessions may keep the model they
were created with.

You do not need to reinstall `ccscience-sync` after changing models.

### The app is blocked by the operating system

The current release is unsigned. macOS and Windows may show a security warning.
This is expected for a small open-source app without paid code-signing
certificates.

## What This Tool Does

`ccscience-sync` is a local helper. It reads the current model from
`~/.claude/settings.json`, maps it to a Claude Science model ID, and updates
Claude Science's new-session model locally.

If it detects an active CSSwitch third-party profile in `~/.csswitch/config.json`
and the CSSwitch local proxy is running, `Open Claude Science` starts
`claude-science` with `ANTHROPIC_BASE_URL` pointing to that local proxy. The
proxy secret is masked in status output.

It does not rely on a fixed 5-second polling loop. Claude Science refreshes
the model when the page becomes active, when you interact with it, and right
before a new-session request is sent.

It does not store, print, upload, or document API keys, passwords, or tokens.
When bridging CSSwitch, it uses only the profile name, model, port, and local
proxy secret; it does not use the API key field from the CSSwitch config.

For `Third-Party (No Login)`, it generates a local virtual Claude Science login
inside an isolated sandbox directory and launches a separate `claude-science`
instance whose inference is routed to the CSSwitch proxy. The virtual token's
credential is a throwaway value the proxy discards; your real third-party API
key stays inside CSSwitch. The sandbox never touches your real
`~/.claude-science`, and guardrails refuse the real port and real credential
directory.

## Advanced Usage From Source

Install Python 3.9 or newer, then run:

```sh
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
python3 ccscience_sync.py
```

Useful commands:

```sh
python3 ccscience_sync.py install
python3 ccscience_sync.py status
python3 ccscience_sync.py open-thirdparty   # isolated no-login third-party instance
python3 ccscience_sync.py stop-thirdparty
python3 ccscience_sync.py uninstall
```

Windows:

```powershell
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
py -3 .\ccscience_sync.py open-thirdparty
py -3 .\ccscience_sync.py uninstall
```

## Custom Model Map

Create `~/.ccscience-sync.json`:

```json
{
  "model_map": {
    "opus[1m]": "claude-opus-4-8",
    "sonnet[1m]": "claude-sonnet-5"
  }
}
```

Default mapping:

| Source model contains | Claude Science model |
| --- | --- |
| `opus` | `claude-opus-4-8` |
| `sonnet` | `claude-sonnet-5` |
| `sonnet-4`, `4.6` | `claude-sonnet-4-6` |
| `haiku` | `claude-haiku-4-5` |
| `fable` | `claude-fable-5` |

## Development

```sh
python3 -m unittest discover -s tests
python3 -m py_compile ccscience_sync.py
```

## License

MIT
