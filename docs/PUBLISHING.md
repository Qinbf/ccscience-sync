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
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions will run tests on macOS and Windows for pushes and pull
requests.

## Before Publishing

- Run local tests.
- Verify `ccscience-sync uninstall` and `ccscience-sync install` on a clean
  machine or VM when possible.
