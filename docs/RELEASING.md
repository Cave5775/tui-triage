# Releasing

Releases are built and published by GitHub Actions (`.github/workflows/release.yml`) using PyPI Trusted Publishing, so no API token is stored anywhere.

## One-time setup

1. Push the repository to GitHub as `Cave5775/triage-board` (or update the URLs in `pyproject.toml` and `CHANGELOG.md`).
2. On GitHub, under **Settings → Environments**, create two environments: `pypi` and `testpypi`. Adding yourself as a required reviewer on `pypi` is recommended.
3. On [pypi.org](https://pypi.org/manage/account/publishing/), add a *pending trusted publisher*:
   - PyPI project name: `triage-board`
   - Owner: `Cave5775`, repository: `triage-board`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
4. Do the same on [test.pypi.org](https://test.pypi.org/manage/account/publishing/) with environment `testpypi` (optional, for dry runs).

## Each release

1. Bump `__version__` in `triage/__init__.py` (the package version is read from there).
2. Move the `Unreleased` notes in `CHANGELOG.md` under a new version heading.
3. Commit, then tag and push:

   ```sh
   git tag v0.1.1
   git push origin main v0.1.1
   ```

The workflow runs the full test suite, checks that the tag matches `__version__`, builds the sdist and wheel, publishes them to PyPI, and creates a GitHub release with the files attached.

To try a build without publishing to the real index, run the **Release** workflow by hand (Actions → Release → Run workflow). That publishes to TestPyPI.

## Building locally

```sh
pip install -e .[dev]
python -m build
python -m twine check --strict dist/*
```
