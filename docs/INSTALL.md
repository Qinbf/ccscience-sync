# Installation

## From Source

```sh
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
```

### macOS

```sh
python3 ccscience_sync.py install
python3 ccscience_sync.py status
```

### Windows

```powershell
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
```

## From GitHub With pipx

```sh
pipx install git+https://github.com/Qinbf/ccscience-sync.git
ccscience-sync install
```

## What install does

1. Finds the newest Claude Science runtime `web-dist/index.html`.
2. Inserts a small marked script before the main Claude Science module.
3. Starts a local helper on `127.0.0.1:19783`.
4. Installs user-level autostart:
   - macOS: `~/Library/LaunchAgents/io.github.ccscience-sync.helper.plist`
   - Windows: current user's Startup folder

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

If the helper is not running:

```sh
ccscience-sync serve --port 19783
```

Then open Claude Science and start a new session.
