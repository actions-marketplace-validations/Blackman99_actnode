# actnode

**Find every GitHub Actions step whose action still runs on Node 20 (or older), and the release that moves it to Node 24.**

Since 2026-06-02 GitHub-hosted runners run JavaScript actions on Node 24 by default, and every job that uses an action declaring `using: node20` ends with:

> Node.js 20 actions are deprecated. The following actions are running on Node.js 20 and may not work as expected: actions/checkout@v4 …

The warning names the action but not *which file and line* uses it, not whether the action is pulled in by a composite action, and not *which version fixes it*. `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` only hides it until Node 20 is removed from runners.

Quick start as a GitHub Action:

```yaml
- uses: actions/checkout@v7
- uses: Blackman99/actnode@v0
  with:
    fail: true
```

actnode answers all three:

```console
$ actnode
[OLD] .github/workflows/ci.yml:7   node20  actions/checkout@v4   -> actions/checkout@v5
[OLD] .github/workflows/ci.yml:9   node20  actions/cache@v4      -> actions/cache@v5
3 step(s) run an action older than node24; 2 have a newer release ready.
$ actnode --fix
```

- reads each action's real `action.yml` at the exact ref you pin (tag, branch or SHA)
- follows composite actions (and their local `./` sub-actions) to find hidden Node 20 actions
- suggests the **smallest** major bump that runs on Node 24, in the same ref style (SHA pins get a SHA + `# vX.Y.Z` comment)
- `--fix` rewrites only those lines; `--fail` and the GitHub Action keep it from coming back

Next: [Install](install.md) · [Usage](usage.md) · [GitHub Action](action.md)
