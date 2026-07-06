<div align="center">

<img src="assets/icon.png" alt="ccscience" width="112" height="112">

# ccscience

**Use the model you picked in CC.Switch — right inside Claude Science.**

[English](README.md) · [中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
&nbsp;![Platform](https://img.shields.io/badge/macOS%20·%20Windows-informational)
&nbsp;[![Download](https://img.shields.io/badge/Download-Releases-brightgreen)](https://github.com/Qinbf/ccscience/releases/latest)

</div>

Switch models in CC.Switch, start a new Claude Science session — that's it.
Install once; you never reinstall just to change models.

<div align="center">
<img src="docs/images/user-guide-01-main.png" alt="ccscience main window" width="760">
</div>

## What it does

- ✅ **Official Claude models** — Opus, Sonnet, Haiku, and more
- 🔌 **Third-party models** — DeepSeek, Kimi, GLM, MiniMax, and more
- 🔓 **No Claude account? No problem** — open a local, login-free Claude Science with your own third-party API key

## Before you start

You'll use ccscience alongside two other apps — get both ready first:

- **[CC.Switch](https://github.com/SuperJJ007/CSSwitch)** — where you choose your model (official Claude, or a third-party API like DeepSeek, Kimi, GLM, MiniMax). Install it and pick a model.
- **Claude Science** — the app ccscience patches. Just open it once so its files land on your machine.

## Get started in 3 steps

**1 · Download & open the app**

Grab the latest macOS or Windows build from **[Releases](https://github.com/Qinbf/ccscience/releases/latest)**, unzip, and open it.

**2 · Click `① Install / Update`, then `Check Status`**

You're ready when you see:

```text
helper: running
runtime patch: installed
```

You only need this again after *Claude Science itself* updates — never when just switching models.

**3 · Launch Claude Science** — pick your path below ⤵

## Path A · You have a Claude account

1. Pick your model in CC.Switch
2. Click **`Open Claude Science`**
3. Start a **new** session

If Claude Science asks you to sign in, sign in normally. Local links expire — click `Open Claude Science` again for a fresh one.

<div align="center">
<img src="docs/images/user-guide-03-web-dashboard.png" alt="Claude Science projects" width="760">
</div>

## Path B · You don't have a Claude account

Have a third-party API key but no Claude account? Use login-free mode:

1. Pick a third-party model in CC.Switch
2. Click **`Third-Party (No Login)`**
3. Your browser opens a local Claude Science page

It runs in an **isolated local sandbox** and never touches your real Claude login. Requests go through a local forwarder to the third-party API you chose. Keys are read from your local config or environment variables — never written into code or docs.

## Start chatting

Open or create a project, click **`New`** in the sidebar, and type your prompt. The active model shows at the bottom of the composer:

<div align="center">
<img src="docs/images/user-guide-04-composer.png" alt="composer and model picker" width="560">
</div>

> **Model didn't change?** Old sessions keep their original model. Always start a **new** session after switching.

## Troubleshooting

<details>
<summary><b>Common fixes</b></summary>

- **Model didn't change** — old sessions keep their model; start a new session.
- **Page won't open** — click `Check Status`; the helper, forwarder, and sandbox should all be running. If a link expired, click the entry button again.
- **Runtime not found** — open Claude Science once manually, then click `Install / Update`.
- **`Agent Failed` / `invalid params`** — update to the latest build, reopen `Third-Party (No Login)`, and test in a new session.

</details>

## Uninstall

Open the app and click **`Uninstall`**.

## Run from source

```sh
git clone https://github.com/Qinbf/ccscience.git
cd ccscience
python3 ccscience.py
```

On Windows, use `py -3` instead of `python3`.

## License

[MIT](LICENSE)
