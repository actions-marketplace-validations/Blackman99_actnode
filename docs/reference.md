# Command reference

```
actnode [scan] [PATH] [--repo OWNER/NAME] [--org OWNER]
        [--target N] [--format text|json|md] [-o FILE]
        [--fix] [--latest] [--fail] [--all] [--no-cache] [--no-upstream]
actnode demo
actnode --version
```

| Flag | Meaning |
|---|---|
| `PATH` | local repository root (default `.`; mutually exclusive with `--repo`/`--org`) |
| `--repo OWNER/NAME` | scan a remote repo via the GitHub Contents API (no clone) |
| `--org OWNER` | scan all public non-fork repos for an org or user via the API |
| `--target N` | minimum Node major an action must run on (default 24) |
| `--format` | `text` (default), `json` (every finding), `md` (problem table, for job summaries) |
| `-o FILE` | write to a file; `md` appends (so it works with `$GITHUB_STEP_SUMMARY`) |
| `--fix` | rewrite direct `uses:` lines to the suggested ref (local PATH only) |
| `--latest` | suggest the newest release already on the target Node (default: smallest major jump) |
| `--fail` | exit code 1 if any step uses an older runtime |
| `--all` | in text mode, also show `ok`, composite, workflow and docker steps |
| `--no-upstream` | don't look up an upstream issue/PR or archived status for actions with no target-Node release |
| `--no-cache` | skip the on-disk tag cache (`~/.cache/actnode` / `$XDG_CACHE_HOME/actnode`) |

Exit codes: `0` ok, `1` old runtime found with `--fail`, `2` usage error or GitHub API rate limit (set a token).

## Status values

| `status` | Text mark | Meaning |
|---|---|---|
| `ok` | `ok` | runs on target Node or newer |
| `old` | `OLD` | older Node; a suggested bump exists |
| `no-fix` | `OLD` | older Node; no node24 release yet (note links the upstream issue/PR tracking it, or says the repo is archived) |
| `composite` | `cmp` | composite action (nested steps followed) |
| `workflow` | `wfl` | reusable workflow (nested uses followed) |
| `docker` | `dkr` | Docker action |
| `unknown` | `?` | could not resolve |

## JSON shape

```json
{"target": 24, "findings": [
  {"file": ".github/workflows/ci.yml", "line": 7, "uses": "actions/checkout@v4",
   "runtime": "node20", "status": "old", "suggest": "actions/checkout@v5", "via": null, "note": "",
   "release_notes": "https://github.com/actions/checkout/releases/tag/v5", "upstream_issue": null}
]}
```

For `no-fix` findings, `upstream_issue` is the best upstream match for "node24" in an issue or PR title (open first, then most discussed): `{"url", "title", "state", "number", "kind": "issue"|"pr"}`, or `null` if none was found. If the action's repository is archived, the note says so instead, since no bump will ever ship. Lookups use one GitHub search per repository, cached with the tags; a rate-limited search is skipped silently.

Remote scans use `file` values like `owner/repo:.github/workflows/ci.yml`. Nested findings set `via` to the composite or reusable workflow ref that pulled them in.
