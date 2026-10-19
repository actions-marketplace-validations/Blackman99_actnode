"""Build a markdown PR body from an actnode JSON report. Usage: pr_body.py REPORT.json TARGET > body.md

Action-only helper: action.yml runs it via ${{ github.action_path }}; it is not part of the wheel.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    report = Path(argv[0])
    target = argv[1] if len(argv) > 1 else "24"
    lines = [
        "## actnode Node runtime bump",
        "",
        "Opened by [actnode](https://github.com/Blackman99/actnode) (`create-pr: true`).",
        f"Direct `uses:` lines were rewritten to releases that already run on Node {target}.",
        "Major bumps can carry breaking changes — read the release-notes links before merging.",
        "",
    ]
    if report.is_file():
        data = json.loads(report.read_text(encoding="utf-8"))
        old = [f for f in data.get("findings", []) if f.get("status") in ("old", "no-fix")]
        if not old:
            lines.append(
                f"All JavaScript actions already run on node{data.get('target', target)} or newer."
            )
        else:
            lines += [
                "| Where | Action | Runtime | Upgrade to | Release notes |",
                "|---|---|---|---|---|",
            ]
            for f in old:
                up = f"`{f['suggest']}`" if f.get("suggest") else (f.get("note") or "")
                via = f" (via `{f['via']}`)" if f.get("via") else ""
                notes = f"[notes]({f['release_notes']})" if f.get("release_notes") else ""
                lines.append(
                    f"| `{f['file']}:{f['line']}` | `{f['uses']}`{via} | "
                    f"{f.get('runtime') or ''} | {up} | {notes} |"
                )
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
