# Contributing

Thanks for helping improve ccscience.

## Local Checks

```sh
python3 -m unittest discover -s tests
python3 -m py_compile ccscience.py
```

## Pull Requests

- Keep the tool dependency-free unless there is a strong reason.
- Do not add API keys, tokens, passwords, or machine-specific paths.
- Include tests for model mapping, runtime patching, or platform behavior when
  you change those areas.
- Keep runtime patches reversible and clearly marked.

## Reporting Bugs

Please include:

- Operating system and version.
- Python version.
- `ccscience --version`.
- `ccscience status` output, with any private paths redacted if desired.
