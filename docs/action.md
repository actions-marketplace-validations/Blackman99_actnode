# GitHub Action

```yaml
name: node-runtime
on: [pull_request, workflow_dispatch]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: Blackman99/actnode@v0
        with:
          fail: true
```

`@v0` is a moving major tag that always points at the latest v0.x release (pin `@v0.3.0` or a SHA for a fixed version).

The step writes a Markdown table to the job summary and fails if any step uses an action older than Node 24.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `path` | `.` | repository root to scan |
| `target` | `24` | minimum Node major |
| `fail` | `true` | fail the step when something old is found |
| `latest` | `false` | suggest the newest release already on the target Node instead of the smallest major jump |
| `create-pr` | `false` | apply `--fix` and open (or update, on later runs) a PR when there is a diff; pair with `fail: false`, otherwise the job still fails after opening the PR |
| `pr-branch` | `actnode/node-runtime` | branch name for `create-pr` |
| `pr-title` | `chore: bump actions to Node 24 runtime` | PR title for `create-pr` |
| `token` | `github.token` | used to list tags; also to push/open a PR when `create-pr` is true |

## Outputs

| Output | Meaning |
|---|---|
| `report` | path to the JSON report |
| `pr-number` | number of the opened/updated PR when `create-pr` ran (empty otherwise) |
| `pr-url` | URL of that PR (empty otherwise) |

## Optional PR mode

For a scheduled (or `workflow_dispatch`) workflow on the default branch, actnode can rewrite `uses:` lines and open a PR:

```yaml
name: node-runtime-pr
on:
  schedule:
    - cron: "0 9 * * 1"
  workflow_dispatch:
permissions:
  contents: write
  pull-requests: write
jobs:
  bump:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: Blackman99/actnode@v0
        with:
          create-pr: true
          fail: false          # PR opened; don't fail the job after proposing fixes
          # latest: true     # optional: jump to the newest node24 release
```

- No PR is opened when `--fix` produces an empty diff.
- An existing open PR on `pr-branch` is updated (force-with-lease push + title/body edit).
- The calling workflow needs `contents: write` and `pull-requests: write` (and a token that can push — default `github.token` is enough for same-repo PRs).
