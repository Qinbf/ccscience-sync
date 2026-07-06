# Installation

## Recommended: Desktop App

Download the latest release:

- macOS: <https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-macos.zip>
- Windows: <https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-windows.zip>

Unzip the file, open the app, then click `Install / Update`.

### First open (security warning)

The apps are free and not signed with a paid Developer ID / code-signing
certificate, so the operating system shows a one-time warning:

- **macOS**: right-click the app, choose `Open`, then confirm (older macOS); or
  `System Settings > Privacy & Security` → `Open Anyway` (macOS 15 Sequoia and
  newer). If it says the app is "damaged", the download was quarantined — run
  `xattr -dr com.apple.quarantine /path/to/ccscience-sync.app`, then open again.
- **Windows**: on the SmartScreen prompt, choose `More info` → `Run anyway`.

These are one-time steps, not a virus warning.

Use `Open Claude Science` in the app to generate a fresh local Claude Science
URL. This helps avoid expired one-time nonce links, but it does not bypass
Claude account login.

For third-party profiles, ccscience-sync treats the active CC.Switch profile as
the source of truth. It accepts the normal `active_id` + `profiles` array shape
as well as common variants such as `activeId`, an inline `activeProfile` object,
or a `profiles` object keyed by profile id. It can use provider details written
by CC.Switch into Claude Code's `ANTHROPIC_*` / `OPENAI_*` settings, including
provider model fields such as `ANTHROPIC_DEFAULT_OPUS_MODEL`,
`ANTHROPIC_MODEL`, or `OPENAI_MODEL`.
When an older `~/.csswitch/config.json` disagrees with a newer Claude settings
provider entry written by the live CC Switch app, ccscience-sync follows the
newer Claude settings entry and marks the local CC Switch config as stale in
`ccscience-sync status`.
It also reads provider-specific profile env entries such as `MOONSHOT_API_KEY` /
`MINIMAX_API_KEY`, or common shell environment variables such as
`DEEPSEEK_API_KEY` / `MOONSHOT_API_KEY` / `MINIMAX_API_KEY` when the active
profile identifies the provider. Profile env values may also reference a shell
variable, for example `${MOONSHOT_API_KEY}` or `${MOONSHOT_BASE_URL}`. For direct third-party
providers, both `Open Claude Science` and `Third-Party (No Login)` route
requests through ccscience-sync's hidden localhost forwarder, which normalizes
provider quirks and injects the key without copying it into Claude Science or
sandbox login files. The forwarder preserves Kimi/Moonshot `reasoning_content`
across turns, avoids sending Kimi-incompatible `adaptive` thinking controls,
disables Kimi thinking when Claude Science forces a tool choice, downgrades
forced tool choice to `auto` for always-thinking Kimi models, preserves tool
names on Kimi tool-result messages, and omits Kimi K2.x sampling parameters that
the Kimi API requires to stay at model defaults.
For DeepSeek OpenAI-compatible profiles, the forwarder also preserves
`reasoning_content` across turns and maps Claude Science thinking controls to
DeepSeek's `enabled` / `disabled` thinking modes.
For Anthropic-compatible providers such as DeepSeek and MiniMax, profile base
URLs may point at the provider root, a `/v1` base, or a full `/v1/messages`
endpoint; ccscience-sync normalizes the upstream URL so the path is not doubled.
For MiniMax, explicit profile `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` wins; if
the profile only identifies MiniMax and provides a key, ccscience-sync defaults
to the international Anthropic endpoint `https://api.minimax.io/anthropic`, and
uses the China endpoint `https://api.minimaxi.com/anthropic` when the profile or
env name clearly indicates `minimaxi` / China. When a MiniMax profile explicitly
uses the OpenAI-compatible `/v1` base, the forwarder enables `reasoning_split`
and preserves MiniMax thinking content through `reasoning_content` /
`reasoning_details`.
Custom CC.Switch profiles are also supported when they include an explicit base
URL and real API key. If a custom profile's explicit base URL is a known
provider host such as Moonshot, DeepSeek, or MiniMax, provider-specific key names
such as `MOONSHOT_API_KEY` are accepted too. Placeholder keys such as `hidden`
are ignored; if there is no usable direct provider entry but a CSSwitch local
proxy is already running, the app can still fall back to that proxy. Use
`ccscience-sync status` to see the resolved provider source, base URL, provider
model, key source variable, and forwarder health without printing the secret.

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

For CC.Switch third-party profiles, switch to the desired profile first, then
open Claude Science from `ccscience-sync`.

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
