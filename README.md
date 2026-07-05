# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

Use the same model in Claude Science that you selected in ccswitch or Claude
Code.

If you are not a developer, start here. You only need to install it once.

## Simple Setup

Before installing:

1. Install Python 3.9 or newer.
2. Open Claude Science once, then close it.
3. Make sure ccswitch or Claude Code already has the model you want selected.

### Step 1: Download

Download this project and unzip it:

[Download ZIP](https://github.com/Qinbf/ccscience-sync/archive/refs/heads/main.zip)

### Step 2: Install

macOS:

Double-click `install-macos.command`.

Windows:

Double-click `install-windows.bat`.

### If Double-Click Does Not Work

macOS Terminal:

```sh
cd ~/Downloads/ccscience-sync-main
python3 ccscience_sync.py install
python3 ccscience_sync.py status
```

Windows PowerShell:

```powershell
cd "$env:USERPROFILE\Downloads\ccscience-sync-main"
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
```

## How To Know It Worked

`status` should show something like:

```text
helper: running (...)
runtime patch: installed (...)
```

After that, use ccswitch or Claude Code as usual. When you start a new Claude
Science session, it should use the same model.

## Everyday Use

After installation, there is nothing else to open.

1. Change model in ccswitch or Claude Code.
2. Start a new Claude Science session.
3. Claude Science uses the synced model automatically.

If Claude Science updates, run `install` again.

## Uninstall

macOS:

Double-click `uninstall-macos.command`.

Windows:

Double-click `uninstall-windows.bat`.

## Common Problems

### Python command not found

Install Python from [python.org](https://www.python.org/downloads/), then open
a new Terminal or PowerShell window and try again.

### Claude Science runtime not found

Open Claude Science once, close it, then run `install` again.

### Model did not change

Start a new Claude Science session. Existing sessions may keep the model they
were created with.

## What This Tool Does

`ccscience-sync` is a local helper. It reads the current model from
`~/.claude/settings.json`, maps it to a Claude Science model ID, and updates
Claude Science's new-session model locally.

It does not read, store, print, upload, or document API keys, passwords, or
tokens.

## Advanced Usage

Install with `pipx`:

```sh
pipx install git+https://github.com/Qinbf/ccscience-sync.git
ccscience-sync install
ccscience-sync status
```

Useful commands:

```sh
ccscience-sync model
ccscience-sync install
ccscience-sync status
ccscience-sync uninstall
```

Direct source commands:

- macOS: `python3 ccscience_sync.py <command>`
- Windows: `py -3 .\ccscience_sync.py <command>`

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
