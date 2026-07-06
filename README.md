# ccscience

[English](README.md) | [中文](README.zh-CN.md)

**Use the model you selected in CC.Switch inside Claude Science.**

Install once. After that, switch models in CC.Switch and start a new Claude Science session. No reinstalling.

## What It Supports

- Official Claude models: Opus, Sonnet, Haiku, and more
- Third-party models: DeepSeek, Kimi, GLM, MiniMax, and more
- A local no-login Claude Science mode for users with third-party API keys but no Claude account

## Install

Before installing:

1. Open Claude Science at least once
2. Pick your model in CC.Switch

Then download and open this app:

- macOS: download the latest macOS build from [GitHub Releases](https://github.com/Qinbf/ccscience-sync/releases/latest)
- Windows: download the latest Windows build from [GitHub Releases](https://github.com/Qinbf/ccscience-sync/releases/latest)

Click **`Install / Update`**.

<img src="docs/images/user-guide-01-main.png" alt="ccscience main window" width="720">

After installation, click **`Check Status`**. These lines mean it is ready:

```text
helper: running
runtime patch: installed
```

Only click **`Install / Update`** again after Claude Science itself updates. Switching models does not require reinstalling.

## With A Claude Account

1. Pick the model in CC.Switch
2. Click **`Open Claude Science`**
3. Start a new session in Claude Science

If Claude Science asks you to sign in, sign in normally. Local links expire; click **`Open Claude Science`** again for a fresh one.

## Without A Claude Account

If you have no Claude account but do have a third-party API key:

1. Pick a third-party model in CC.Switch
2. Click **`Third-Party (No Login)`**
3. Your browser opens a local Claude Science page

<img src="docs/images/user-guide-03-web-dashboard.png" alt="third-party no-login page" width="720">

This runs in an isolated local sandbox and does not touch your real Claude login. Requests go through the local forwarder to the selected third-party API. Secrets are read from your local config or environment variables; do not write them into code or docs.

## Start Chatting

Open or create a project, then click **New** in the sidebar. The bottom of the composer shows the active model:

<img src="docs/images/user-guide-04-composer.png" alt="composer and model picker" width="520">

Type your prompt and send it. If a tool permission prompt appears, allow only tools you trust.

## Troubleshooting

**Model did not change?** Old sessions keep their original model. Start a new session after switching models.

**Page does not open?** Click **`Check Status`** and make sure the helper, forwarder, and sandbox are running. If the link expired, click the entry button again.

**Runtime not found?** Open Claude Science once manually, then click **`Install / Update`**.

**`Agent Failed` / `invalid params`?** Make sure you are on the latest build, reopen **`Third-Party (No Login)`**, and test in a new session.

## Uninstall

Open the app and click **`Uninstall`**.

## Run From Source

```sh
git clone https://github.com/Qinbf/ccscience-sync.git ccscience
cd ccscience
python3 ccscience_sync.py
```

On Windows, replace `python3` with `py -3`.

## License

MIT
