# Roadmap

## v0.1 (2026-10-11) — shipped
- Scan workflows + root action.yml, resolve every `uses:` to its `runs.using`
- Follow composite actions (3 levels, incl. local `./` sub-actions)
- Smallest-major suggestion in the same ref style (tag / full version / SHA + comment)
- `--fix`, `--fail`, text / JSON / Markdown, GitHub Action with job summary

## v0.2 (2026-10-12) — shipped
- Reusable workflows (`uses: org/repo/.github/workflows/x.yml@ref`) scanned recursively
- Org/repo mode: `actnode --repo owner/name` and `--org owner` without cloning (API only)
- Cache tag lookups across runs (`~/.cache/actnode`)

## v0.3 (2026-10-19) — shipped
- `--latest` to suggest the newest node24 release instead of the smallest jump
- Show release-notes links for each major bump
- Optional PR mode for the Action (open a PR with the `--fix` diff)

## Later
- Track upstream "no node24 release yet" actions and link the upstream issue
- Publish to PyPI
