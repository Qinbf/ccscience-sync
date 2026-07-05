# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

Sync the model selected by ccswitch or Claude Code into Claude Science.

`ccscience-sync` is a small local bridge for users who switch Claude Code
models with ccswitch and want new Claude Science sessions to use the same
model automatically.

It does not read, store, print, upload, or document API keys, passwords, or
tokens.

## What It Does

- Reads the active Claude Code model from `~/.claude/settings.json`.
- Maps that model to the model IDs used by Claude Science.
- Starts a localhost helper at `127.0.0.1:19783`.
- Applies a reversible patch to Claude Science's web runtime.
- Keeps Claude Science's default model and new-session request model in sync.
- Supports macOS and Windows without administrator permissions.

## Requirements

- Python 3.9 or newer.
- Claude Code or ccswitch writing `~/.claude/settings.json`.
- Claude Science installed and launched at least once.

## Quick Install

With `pipx`:

```sh
pipx install git+https://github.com/Qinbf/ccscience-sync.git
ccscience-sync install
ccscience-sync status
```

From source:

```sh
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
python3 ccscience_sync.py install
python3 ccscience_sync.py status
```

On Windows, use PowerShell:

```powershell
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
```

## Commands

```sh
ccscience-sync model
ccscience-sync serve --port 19783
ccscience-sync install
ccscience-sync install --all
ccscience-sync install --no-autostart
ccscience-sync status
ccscience-sync uninstall
```

If you run directly from source, replace `ccscience-sync` with
`python3 ccscience_sync.py`. On Windows, use `py -3 .\ccscience_sync.py`.

## Platform Behavior

| Platform | Autostart method | Admin required |
| --- | --- | --- |
| macOS | User LaunchAgent | No |
| Windows | Current user's Startup folder | No |

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

## Claude Science Data Directory

If Claude Science stores runtime files somewhere unusual, set
`CLAUDE_SCIENCE_DATA_DIR` before installing:

```sh
export CLAUDE_SCIENCE_DATA_DIR="/path/to/.claude-science"
ccscience-sync install
```

PowerShell:

```powershell
$env:CLAUDE_SCIENCE_DATA_DIR = "C:\path\to\.claude-science"
ccscience-sync install
```

## Updating Claude Science

Claude Science updates may create a new runtime directory. Re-run:

```sh
ccscience-sync install
```

## Uninstall

```sh
ccscience-sync uninstall
```

This removes the runtime patch and the helper autostart entry. It does not
modify Claude Code settings, ccswitch settings, or API credentials.

## How It Works

Claude Code stores its current model in `~/.claude/settings.json`. Claude
Science stores a default model in browser local storage and sends a `model`
field when starting a new session. `ccscience-sync` bridges those two local
places with:

- a tiny localhost JSON endpoint that exposes the mapped model; and
- a marked script patch in Claude Science's `web-dist/index.html`.

The patch is wrapped with `ccscience-sync:start` and `ccscience-sync:end`
markers, so it can be updated or removed safely.

## Development

```sh
python3 -m unittest discover -s tests
python3 -m py_compile ccscience_sync.py
```

## Security

`ccscience-sync` only reads local model metadata. Please do not open issues or
pull requests containing API keys, passwords, tokens, or private credentials.

## License

MIT
