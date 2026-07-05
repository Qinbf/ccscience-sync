# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

Use the same model in Claude Science or the built-in third-party model
workbench that you selected in ccswitch or Claude Code.

Most users do not need Python, Terminal, PowerShell, or source code. Download
the app, open it, and click install.

The desktop app automatically uses Chinese on Chinese systems and English on
other systems.

## Two Modes

- `Claude Science mode`: requires normal Claude Science sign-in. This mode only
  syncs models and opens fresh one-time links. It does not bypass sign-in.
- `Third-Party Workbench`: does not use Claude Science sign-in. It uses your own
  third-party API key and defaults to an OpenAI-compatible DeepSeek endpoint.

## One-Click Install

Before installing:

1. Open Claude Science once, then close it.
2. Make sure ccswitch or Claude Code already has the model you want selected.

### macOS

1. Download:
   [ccscience-sync-macos.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-macos.zip)
2. Unzip it.
3. Open `ccscience-sync.app`.
4. Click `Install / Update`.
5. If you have a Claude account, click `Open Claude Science`.
6. If you do not have a Claude account, click `Third-Party Workbench`.

If macOS blocks the app, right-click it, choose `Open`, then confirm.

### Windows

1. Download:
   [ccscience-sync-windows.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-windows.zip)
2. Unzip it.
3. Open `ccscience-sync.exe`.
4. Click `Install / Update`.
5. If you have a Claude account, click `Open Claude Science`.
6. If you do not have a Claude account, click `Third-Party Workbench`.

If Windows SmartScreen appears, choose `More info`, then `Run anyway`.

## How To Know It Worked

In the app, click `Check Status`.

You should see:

```text
helper: running (...)
runtime patch: installed (...)
```

After that, use ccswitch or Claude Code as usual. When you start a new Claude
Science session, it should use the same model.

The third-party workbench status also shows:

```text
workbench provider: DeepSeek
workbench model: deepseek-v4-flash
workbench key: configured
```

## Everyday Use

After installation, there is nothing else to keep open.

1. Change model in ccswitch or Claude Code.
2. If you have a Claude account, start a new Claude Science session.
3. If you do not have a Claude account, open `Third-Party Workbench` and chat there.

You do not need to reinstall after changing models in ccswitch or Claude Code.
The helper reads the latest model automatically when a new Claude Science
session starts.

Only run `Install / Update` again if Claude Science itself updates or status
does not show `runtime patch: installed`.

## Uninstall

Open `ccscience-sync` and click `Uninstall`.

## Common Problems

### Can I use it without a Claude account?

Yes, use `Third-Party Workbench`. It does not start Claude Science and does not
need Claude Science sign-in. It reads the current ccswitch model and calls the
third-party provider you configured.

Default configuration:

- API key environment variable: `DEEPSEEK_API_KEY`
- Base URL: `https://api.deepseek.com`
- Endpoint: `/chat/completions`
- Default fast model: `deepseek-v4-flash`
- Opus-like model: `deepseek-v4-pro`

Store your API key in your own environment variable or `~/.zshrc`, for example:

```zsh
export DEEPSEEK_API_KEY="<your_key>"
```

Then reopen `ccscience-sync`.

### Claude Science asks me to log in

Claude Science's local browser link is a one-time link and can expire. Open
`ccscience-sync` and click `Open Claude Science` to generate and open a fresh
link.

If Claude Science asks for your Claude account, sign in normally. This tool
does not and cannot bypass Claude account login.

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

In third-party workbench mode, it maps the current ccswitch model to a provider
model, reads the API key from an environment variable, and calls an
OpenAI-compatible chat endpoint.

It does not rely on a fixed 5-second polling loop. Claude Science refreshes
the model when the page becomes active, when you interact with it, and right
before a new-session request is sent.

It does not store, print, or document API key values. In third-party workbench
mode it reads only the configured environment variable and sends that value as
the authorization header to the provider you configured.

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
python3 ccscience_sync.py open-workbench
python3 ccscience_sync.py uninstall
```

Windows:

```powershell
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
py -3 .\ccscience_sync.py open-workbench
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

The third-party workbench can use any OpenAI-compatible provider:

```json
{
  "workbench": {
    "provider": "My Provider",
    "base_url": "https://api.example.com",
    "endpoint": "/chat/completions",
    "api_key_env": "MY_PROVIDER_API_KEY",
    "default_model": "provider-default-model",
    "model_map": {
      "opus": "provider-strong-model",
      "sonnet": "provider-fast-model"
    }
  }
}
```

The config stores only the variable name, not the API key value.

## Development

```sh
python3 -m unittest discover -s tests
python3 -m py_compile ccscience_sync.py
```

## License

MIT
