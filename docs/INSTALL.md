# Installation

## Recommended: Desktop App

Download the latest release:

- macOS: <https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-macos.zip>
- Windows: <https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-windows.zip>

Unzip the file, open the app, then click `Install / Update`.

Use `Open Claude Science` in the app to generate a fresh local Claude Science
URL. This helps avoid expired one-time nonce links, but it does not bypass
Claude account login.

## From Source

```sh
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
```

macOS:

```sh
python3 ccscience_sync.py install
python3 ccscience_sync.py status
```

Windows:

```powershell
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
```

## What install does

1. Finds the newest Claude Science runtime `web-dist/index.html`.
2. Inserts a small marked script before the main Claude Science module.
3. Starts a local helper on `127.0.0.1:19783`.
4. Installs user-level autostart:
   - macOS: `~/Library/LaunchAgents/io.github.ccscience-sync.helper.plist`
   - Windows: current user's Startup folder

Packaged App/EXE builds copy themselves to a stable per-user application data
directory before installing autostart, so users can delete the downloaded ZIP
folder after installation.

Users do not need to reinstall after changing models in ccswitch or Claude
Code. The local helper reads the latest model for new Claude Science sessions.

## Troubleshooting

If runtime files are not found, launch Claude Science once and run install
again.

If Claude Science uses a custom data directory:

```sh
export CLAUDE_SCIENCE_DATA_DIR="/path/to/.claude-science"
ccscience-sync install
```

On Windows:

```powershell
$env:CLAUDE_SCIENCE_DATA_DIR = "C:\path\to\.claude-science"
ccscience-sync install
```
