# Contributing

Thanks! Please read [GOAL.md](GOAL.md) first: changes should serve that one goal.

```bash
git clone https://github.com/Blackman99/actnode && cd actnode
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

- Tests use a fake fetcher (no network); add a case to `tests/test_core.py` for any new behaviour.
- Keep zero runtime dependencies.
- Site lives in `site/` (plain HTML/CSS/JS), docs in `docs/` (MkDocs Material). Design notes: `site/DESIGN.md`.
- One logical change per PR; describe how you tested it.

## Releasing

Push a `vX.Y.Z` tag. The Release workflow builds, publishes the release, and moves the major tag (`v0`) to it, so `uses: Blackman99/actnode@v0` always gets the latest release. To move it by hand: `git tag -f v0 vX.Y.Z^{} && git push -f origin refs/tags/v0`.
