# Publishing to GitHub

## First Push

Choose an owner and repository name, then run:

```sh
git init
git add .
git commit -m "Initial release"
gh repo create ccscience-sync --public --source=. --remote=origin --push
```

If the repository already exists:

```sh
git remote add origin https://github.com/Qinbf/ccscience-sync.git
git branch -M main
git push -u origin main
```

## Release

```sh
git tag v0.2.1
git push origin v0.2.1
```

GitHub Actions will run tests, build the macOS and Windows desktop apps, create
the GitHub Release if needed, and upload:

- `ccscience-sync-macos.zip`
- `ccscience-sync-windows.zip`

## Before Publishing

- Run local tests.
- Verify `ccscience-sync uninstall` and `ccscience-sync install` on a clean
  machine or VM when possible.
