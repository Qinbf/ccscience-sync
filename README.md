# ccscience-sync

Sync the model selected by ccswitch or Claude Code into Claude Science.

Claude Code stores the active model in `~/.claude/settings.json`. Claude
Science stores its default model in browser local storage and sends the model
as a JSON request field when a new session starts. `ccscience-sync` bridges
those two places with a small localhost helper and a reversible patch to Claude
Science's web entrypoint.

No API keys, passwords, or tokens are read, stored, printed, or uploaded.

## Features

- Works on macOS and Windows.
- Installs without administrator permissions.
- Uses only the Python standard library.
- Starts a local helper at `127.0.0.1:19783`.
- Patches Claude Science runtime files with clear start/end markers.
- Supports custom model mapping through `~/.ccscience-sync.json`.
- Provides one-command install, status, and uninstall.

## Requirements

- Python 3.9 or newer.
- Claude Code or ccswitch writing `~/.claude/settings.json`.
- Claude Science installed and launched at least once.

## Quick Start

Clone the repository, then run:

### macOS

```sh
python3 ccscience_sync.py install
python3 ccscience_sync.py status
```

The installer creates a user LaunchAgent and patches the newest Claude Science
runtime.

### Windows

```powershell
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
```

The installer creates a hidden startup entry in the current user's Startup
folder and patches the newest Claude Science runtime.

## Install With pipx

After this project is published on GitHub:

```sh
pipx install git+https://github.com/Qinbf/ccscience-sync.git
ccscience-sync install
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

If you run directly from source, replace `ccscience-sync` with:

```sh
python3 ccscience_sync.py
```

On Windows, use `py -3 .\ccscience_sync.py`.

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

The default mapping is intentionally conservative:

| Source model contains | Claude Science model |
| --- | --- |
| `opus` | `claude-opus-4-8` |
| `sonnet` | `claude-sonnet-5` |
| `sonnet-4`, `4.6` | `claude-sonnet-4-6` |
| `haiku` | `claude-haiku-4-5` |
| `fable` | `claude-fable-5` |

## Claude Science Data Directory

If Claude Science stores runtime files somewhere unusual, set:

```sh
export CLAUDE_SCIENCE_DATA_DIR="/path/to/.claude-science"
ccscience-sync install
```

On Windows PowerShell:

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

## Development

```sh
python3 -m unittest discover -s tests
python3 -m py_compile ccscience_sync.py
```

## Security

`ccscience-sync` only reads model metadata from local settings files. Do not
open issues or pull requests containing API keys or credentials.

## License

MIT
