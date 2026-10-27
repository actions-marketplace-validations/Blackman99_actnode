from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import CURRENT, Resolver, apply_fixes, scan, scan_org, scan_repo

MARK = {
    "ok": "ok ",
    "old": "OLD",
    "no-fix": "OLD",
    "unknown": " ? ",
    "composite": "cmp",
    "workflow": "wfl",
    "docker": "dkr",
    "local": "loc",
}


def render_text(findings, target):
    rows = []
    for f in findings:
        where = f"{f.file}:{f.line}"
        rt = f.runtime or "-"
        extra = f"-> {f.suggest}" if f.suggest else f.note
        if f.upstream_issue and f.upstream_issue.get("url"):
            extra = f"{extra}  {f.upstream_issue['url']}"
        if f.release_notes:
            extra = f"{extra}  notes: {f.release_notes}" if extra else f"notes: {f.release_notes}"
        via = f"   (inside {f.via})" if f.via else ""
        rows.append(f"[{MARK.get(f.status, f.status)}] {where:<34} {rt:<10} {f.uses}  {extra}{via}")
    old = [f for f in findings if f.status in ("old", "no-fix")]
    fix = [f for f in old if f.status == "old"]
    rows.append("")
    if old:
        rows.append(f"{len(old)} step(s) run an action older than node{target}; {len(fix)} have a newer release ready.")
    else:
        rows.append(f"All actions run on node{target} or newer (or are composite/workflow/docker).")
    return "\n".join(rows)


def render_md(findings, target):
    old = [f for f in findings if f.status in ("old", "no-fix")]
    out = [f"### actnode: Node.js runtime audit (target node{target})", ""]
    if not old:
        out.append(f"All JavaScript actions run on node{target} or newer.")
        return "\n".join(out) + "\n"
    out += [
        "| Where | Action | Runtime | Upgrade to | Release notes |",
        "|---|---|---|---|---|",
    ]
    for f in old:
        up = f"`{f.suggest}`" if f.suggest else f.note
        ui = f.upstream_issue
        if not f.suggest and ui and ui.get("url"):
            up = f"no node{target} release yet; upstream [#{ui['number']}]({ui['url']}) ({ui['state']})"
        via = f" (via `{f.via}`)" if f.via else ""
        notes = f"[notes]({f.release_notes})" if f.release_notes else ""
        out.append(f"| `{f.file}:{f.line}` | `{f.uses}`{via} | {f.runtime} | {up} | {notes} |")
    return "\n".join(out) + "\n"


DEMO = """\
name: ci
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - uses: actions/cache@v4
      - uses: actions/upload-artifact@v4
"""


def _add_scan_flags(s):
    s.add_argument("path", nargs="?", default=None, help="local repository root (default .)")
    s.add_argument("--repo", metavar="OWNER/NAME", help="scan a remote repo via GitHub API (no clone)")
    s.add_argument("--org", metavar="OWNER", help="scan all public non-fork repos for an org/user via API")
    s.add_argument("--target", type=int, default=CURRENT, help="minimum Node major (default 24)")
    s.add_argument("--format", choices=["text", "json", "md"], default="text")
    s.add_argument("-o", "--output", help="write report to this file (appends for md)")
    s.add_argument("--fix", action="store_true", help="rewrite uses: lines to the suggested refs")
    s.add_argument(
        "--latest",
        action="store_true",
        help="suggest the newest release already on the target Node instead of the smallest major jump",
    )
    s.add_argument("--fail", action="store_true", help="exit 1 if any step runs an old Node action")
    s.add_argument("--all", action="store_true", help="show every step, not only problems")
    s.add_argument(
        "--no-upstream",
        action="store_true",
        help="don't search upstream for an issue/PR when an action has no target-Node release",
    )
    s.add_argument("--no-cache", action="store_true", help="skip disk tag cache (~/.cache/actnode)")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="actnode",
        description="Find GitHub Actions that still run on Node 20 (or older) and the release that moves them to Node 24.",
    )
    p.add_argument("--version", action="version", version=f"actnode {__version__}")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("scan", help="scan a repository's workflows (default command)")
    _add_scan_flags(s)
    # Also accept top-level flags when no subcommand (actnode --repo ... / actnode .)
    # The default-insert of "scan" below handles that.
    sub.add_parser("demo", help="scan a built-in sample workflow (needs network)")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("scan", "demo", "-h", "--help", "--version"):
        argv.insert(0, "scan")
    a = p.parse_args(argv)
    if a.cmd == "demo":
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / ".github" / "workflows").mkdir(parents=True)
        (d / ".github" / "workflows" / "ci.yml").write_text(DEMO)
        a = p.parse_args(["scan", str(d), "--all"])

    if a.repo and a.org:
        print("actnode: use only one of --repo or --org", file=sys.stderr)
        return 2
    if (a.repo or a.org) and a.path is not None:
        print("actnode: PATH cannot be combined with --repo or --org", file=sys.stderr)
        return 2
    if a.fix and (a.repo or a.org):
        print("actnode: --fix requires a local checkout; cannot rewrite remote scans", file=sys.stderr)
        return 2

    resolver = Resolver(use_cache=not a.no_cache, latest=a.latest, upstream=not a.no_upstream)
    try:
        if a.repo:
            if "/" not in a.repo or a.repo.count("/") != 1:
                print("actnode: --repo expects OWNER/NAME", file=sys.stderr)
                return 2
            owner, name = a.repo.split("/", 1)
            findings = scan_repo(owner, name, resolver, a.target)
        elif a.org:
            findings = scan_org(a.org, resolver, a.target)
        else:
            root = Path(a.path if a.path is not None else ".")
            findings = scan(root, resolver, a.target)
    except RuntimeError as e:
        print(f"actnode: {e}", file=sys.stderr)
        return 2

    shown = findings if (a.all or a.format == "json") else [
        f for f in findings if f.status in ("old", "no-fix", "unknown")
    ]
    if a.format == "json":
        text = json.dumps({"target": a.target, "findings": [f.to_dict() for f in findings]}, indent=2) + "\n"
    elif a.format == "md":
        text = render_md(findings, a.target)
    else:
        text = render_text(shown, a.target) + "\n"
    if a.output:
        with open(a.output, "a" if a.format == "md" else "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    if a.fix:
        root = Path(a.path if a.path is not None else ".")
        n = apply_fixes(root, findings)
        print(f"actnode: rewrote {n} line(s)", file=sys.stderr)
    if a.fail and any(f.status in ("old", "no-fix") for f in findings):
        return 1
    return 0
