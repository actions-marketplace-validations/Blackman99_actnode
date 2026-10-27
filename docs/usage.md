# Usage

Run from a repository root (or pass a path):

```bash
actnode                 # problems only
actnode path/to/repo --all   # every step, including the ones already on node24
```

What it scans: every file in `.github/workflows/*.yml|yaml`, plus a root `action.yml` if the repo is itself an action. Every `uses:` is resolved:

| Status | Meaning |
|---|---|
| `ok` | the action runs on node24 (or the `--target`) or newer |
| `OLD` + `->` | runs on an older Node; a newer release on node24 exists, shown after `->` |
| `OLD` + note | runs on an older Node and **no** release runs on node24 yet: the note links the upstream issue or PR tracking it (or says the repo is archived), so you can follow it, fork, or replace the action |
| `cmp` | composite action; the steps inside are checked and shown with `(inside …)` |
| `wfl` | reusable workflow; jobs/steps inside are checked recursively (same depth as composites) |
| `dkr` | Docker action, not affected |
| `?` | could not read `action.yml` / workflow YAML (private repo, deleted ref, unpinned ref) |

Reusable workflows (`uses: org/repo/.github/workflows/ci.yml@v1` or local `./.github/workflows/…`) are fetched and scanned the same way composites are followed.

## Remote scan (no clone)

```bash
actnode --repo owner/name          # one public (or token-visible) repo via the API
actnode --org owner                # all public non-fork repos for an org or user
```

Findings are labeled `owner/repo:.github/workflows/ci.yml`. Forks and archived repos are skipped in `--org` mode. `--fix` is refused with `--repo`/`--org` (needs a local checkout). Set `GITHUB_TOKEN` for rate limits and private repos.

`PATH`, `--repo`, and `--org` are mutually exclusive.

## Latest vs smallest jump

By default actnode suggests the **smallest major** that already runs on Node 24 (fewer breaking changes). Pass `--latest` to jump straight to the newest release that is already on the target Node:

```bash
actnode                 # -> actions/checkout@v5   (smallest jump)
actnode --latest        # -> actions/checkout@v7   (newest on node24)
actnode --latest --fix
```

## Release notes

Every finding with a suggested bump includes a `release_notes` URL (GitHub releases page for that tag). Text mode prints `notes: https://…`; Markdown adds a **Release notes** column; JSON adds a `release_notes` field.

## Fix

```bash
actnode --fix
git diff
```

Only direct `uses:` lines with a suggestion are rewritten. Quotes, indentation and trailing comments are kept; for SHA pins the trailing comment becomes the new version. Actions found *inside* composite actions or reusable workflows can't be fixed in your repo: bump the composite/reusable workflow or ask its maintainer.

Major bumps can carry breaking changes (for example `upload-artifact` v4 → v6). Read the release notes before merging.

## Formats

```bash
actnode --format json -o actnode.json
actnode --format md -o "$GITHUB_STEP_SUMMARY"
```

## Gate

```bash
actnode --fail   # exit 1 if any old-runtime action is found
```

## Cache

Tag lookups are cached under `~/.cache/actnode` (or `$XDG_CACHE_HOME/actnode`) for 24 hours so repeated scans of the same actions stay fast. Pass `--no-cache` to always hit the GitHub API.
