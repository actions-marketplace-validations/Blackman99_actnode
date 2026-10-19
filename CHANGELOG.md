# Changelog

## v0.3.0 — 2026-10-19
- `--latest` (Action input `latest`): suggest the newest node24-capable release instead of the smallest major jump; default behavior unchanged
- Release-notes links on every suggested bump (`release_notes` in JSON; text `notes:` URL; Markdown column)
- Action optional PR mode: `create-pr` (+ `pr-branch` / `pr-title`) applies `--fix` and opens or updates a PR when there is a diff on every run, including later runs that update the existing PR branch (needs `contents:write` + `pull-requests:write`); pair it with `fail: false`, otherwise the job still fails after opening the PR

## v0.2.0 — 2026-10-12
- Reusable workflows (`uses: org/repo/.github/workflows/x.yml@ref`) scanned recursively (status `workflow` / `wfl`); nested findings show `(inside …)` and are not rewritten by `--fix`
- Remote scan without cloning: `actnode --repo owner/name` and `actnode --org owner` (public non-fork repos by default; `--fix` refused)
- Tag lookups cached under `~/.cache/actnode` (or `$XDG_CACHE_HOME/actnode`), 24h TTL; `--no-cache` to skip

## v0.1.0 — 2026-10-11
First release: scan, composite following, smallest-major suggestions, `--fix`, `--fail`, JSON/Markdown output, GitHub Action.
