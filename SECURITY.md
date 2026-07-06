# Security Policy

`ccscience` is a local helper. It reads model metadata from Claude Code or
ccswitch settings and exposes the mapped model on `127.0.0.1`.

It must not collect, print, store, upload, or document API keys, tokens,
passwords, or access keys.

## Reporting a Vulnerability

Open a private security advisory on GitHub if available. If not, open an issue
that describes the impact without including secrets or exploit payloads.

## Localhost Helper

The helper binds to `127.0.0.1` by default. Do not change it to bind to public
interfaces unless there is a reviewed security design.
