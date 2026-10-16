<p align="center"><img src="site/logo-512.png" width="120" alt="actnode logo: a green route shield reading ACT 24"></p>
<h1 align="center">actnode</h1>
<p align="center"><b>Node 20 lane ends.</b> Find every GitHub Actions step still on a Node 20 (or older) action, get the release that runs on Node 24, and rewrite it.</p>
<p align="center"><a href="https://blackman99.github.io/actnode/">Home</a> · <a href="https://blackman99.github.io/actnode/docs/">Docs</a> · <a href="https://github.com/Blackman99/actnode/actions/workflows/ci.yml"><img src="https://github.com/Blackman99/actnode/actions/workflows/ci.yml/badge.svg" alt="CI"></a></p>

## The problem

Since 2026-06-02 GitHub runners run JavaScript actions on Node 24, and jobs that use node20 actions end with *"Node.js 20 actions are deprecated. The following actions are running on Node.js 20…"*. The warning doesn't say **which file and line**, misses actions **hidden inside composite actions**, and doesn't say **which version fixes it**. `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` only hides it ([actions/runner#4295](https://github.com/actions/runner/issues/4295)) until Node 20 is removed from runners.

## Quick start: GitHub Action

Add this workflow (e.g. `.github/workflows/node-runtime.yml`). It writes a job-summary table of every step whose action still runs on Node 20 or older, with the release that runs on Node 24, and fails the job if any is found:

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
          fail: true      # inputs: path (.), target (24), fail (true), token (github.token)
```

`@v0` is a moving major tag that always points at the latest v0.x release; pin `@v0.2.0` or a SHA if you prefer.

## Install (CLI, to fix locally)

```bash
pipx install git+https://github.com/Blackman99/actnode
```

Python 3.9+, zero dependencies. Set `GITHUB_TOKEN` (e.g. `export GITHUB_TOKEN=$(gh auth token)`) for repos with many actions.

## Use

```console
$ actnode
[OLD] .github/workflows/ci.yml:7    node20  actions/checkout@v4         -> actions/checkout@v5
[OLD] .github/workflows/ci.yml:10   node20  actions/upload-artifact@v4  -> actions/upload-artifact@v6
$ actnode --fix      # rewrite those uses: lines (SHA pins get a SHA + version comment)
$ actnode --fail     # exit 1 if anything is still old
$ actnode --repo owner/name   # API scan, no clone
```

![demo](site/demo.gif)

It reads each action's real `action.yml` at the exact ref you pin, follows composite actions and reusable workflows, and suggests the **smallest** major bump that runs on Node 24. Scan a remote repo without cloning: `actnode --repo owner/name` (or `--org owner`).

Full docs: [install](https://blackman99.github.io/actnode/docs/install/) · [usage](https://blackman99.github.io/actnode/docs/usage/) · [Action](https://blackman99.github.io/actnode/docs/action/) · [reference](https://blackman99.github.io/actnode/docs/reference/) · [FAQ](https://blackman99.github.io/actnode/docs/faq/)

[Goal](GOAL.md) · [Roadmap](ROADMAP.md) · [Contributing](CONTRIBUTING.md) · MIT
