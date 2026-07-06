# ccscience Quick Guide

This guide covers the common path only. Open Claude Science once first, then choose your model in CC.Switch.

## 1. Open The App

Open `ccscience.app` on macOS or `ccscience.exe` on Windows. From source:

```sh
python3 ccscience_sync.py
```

Main window:

![ccscience main window](images/user-guide-01-main.png)

Useful buttons:

- `Install / Update`: click once for first setup; click again after Claude Science updates.
- `Open Claude Science`: use this when you have a Claude account.
- `Third-Party (No Login)`: use this when you have no Claude account but have a third-party API key.
- `Check Status`: verify the helper, patch, and third-party services.

## 2. Install Once

Click `Install / Update`, then click `Check Status`. These lines mean it is ready:

```text
helper: running
runtime patch: installed
```

After that, switching models in CC.Switch does not require reinstalling. Start a new Claude Science session instead.

## 3. With A Claude Account

1. Pick the model in CC.Switch.
2. Click `Open Claude Science`.
3. Start a new session in Claude Science.

If Claude Science asks you to sign in, sign in normally. Local links expire; click `Open Claude Science` again for a fresh one.

## 4. Without A Claude Account

1. Pick a third-party model in CC.Switch.
2. Click `Third-Party (No Login)`.
3. Your browser opens a local Claude Science page.

![Third-party no-login page](images/user-guide-03-web-dashboard.png)

This runs in an isolated local sandbox and does not touch your real Claude login. Requests go through the local forwarder to the third-party API you selected; secrets are not written into these docs.

## 5. Start Chatting

Open or create a project, then click `New` in the sidebar. The model picker at the bottom shows the active model:

![Composer and model picker](images/user-guide-04-composer.png)

Type your prompt and send it. If a tool permission prompt appears, allow only tools you trust.

## 6. Troubleshooting

**Model did not change**: old sessions keep their original model. Start a new session.

**Page does not open**: click `Check Status`; the helper, forwarder, and sandbox should be running. If the link expired, click the entry button again.

**Runtime not found**: open Claude Science once manually, then click `Install / Update`.

**`Agent Failed` / `invalid params`**: make sure you are on the latest build, reopen `Third-Party (No Login)`, and test in a new session.

**Third-party model does not work**: check the selected CC.Switch profile and API key. Store keys in environment variables or CC.Switch, not in code or docs.
