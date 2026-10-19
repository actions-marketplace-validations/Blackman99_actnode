"""create-pr must be able to update its PR branch on runs after the first.

actions/checkout only fetches the triggering ref, so the runner has no
refs/remotes/origin/<pr-branch>. scripts/push_pr_branch.sh fetches it before
``git push --force-with-lease``; this test simulates two scheduled runs.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "push_pr_branch.sh"
BRANCH = "actnode/node-runtime"

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win") or not shutil.which("bash") or not shutil.which("git"),
    reason="needs bash + git (the Action runs the script with bash on Linux/macOS runners)",
)

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
}


def git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=check,
                          capture_output=True, text=True)


@pytest.fixture
def origin(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    (seed / "ci.yml").write_text("uses: actions/checkout@v4\n")
    git(seed, "add", ".")
    git(seed, "commit", "-qm", "init")
    bare = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
    return bare


def checkout_like_actions(origin, dest, style="checkout"):
    """Leave the repo the way actions/checkout does: only main, shallow.

    style="checkout": init + remote add (wildcard refspec) + fetch main only,
    which is what actions/checkout runs. style="single-branch": a
    --single-branch clone, whose refspec only maps main.
    """
    if style == "checkout":
        dest.mkdir()
        git(dest, "init", "-q")
        git(dest, "remote", "add", "origin", origin.as_uri())
        git(dest, "fetch", "-q", "--no-tags", "--depth=1", "origin",
            "+refs/heads/main:refs/remotes/origin/main")
        git(dest, "checkout", "-q", "-B", "main", "refs/remotes/origin/main")
    else:
        git(dest.parent, "clone", "-q", "--depth=1", "--single-branch", "--branch", "main",
            origin.as_uri(), str(dest))
    refs = git(dest, "for-each-ref", "--format=%(refname)", "refs/remotes/").stdout.split()
    assert f"refs/remotes/origin/{BRANCH}" not in refs


def run_fix(work, content, msg):
    (work / "ci.yml").write_text(content)
    git(work, "checkout", "-q", "-B", BRANCH)
    git(work, "commit", "-qam", msg)


def push(work):
    return subprocess.run(["bash", str(SCRIPT), BRANCH], cwd=work, env=ENV,
                          capture_output=True, text=True)


def remote_head(origin):
    return git(origin, "rev-parse", f"refs/heads/{BRANCH}").stdout.strip()


@pytest.mark.parametrize("style", ["checkout", "single-branch"])
def test_first_and_second_run_both_push(origin, tmp_path, style):
    run1 = tmp_path / "run1"
    checkout_like_actions(origin, run1, style)
    run_fix(run1, "uses: actions/checkout@v5\n", "run 1")
    r = push(run1)
    assert r.returncode == 0, r.stderr
    assert remote_head(origin) == git(run1, "rev-parse", "HEAD").stdout.strip()

    # Next scheduled run: fresh runner, new diff, PR branch already on origin.
    run2 = tmp_path / "run2"
    checkout_like_actions(origin, run2, style)
    run_fix(run2, "uses: actions/checkout@v6\n", "run 2")
    r = push(run2)
    assert r.returncode == 0, r.stderr
    assert remote_head(origin) == git(run2, "rev-parse", "HEAD").stdout.strip()


def test_lease_still_protects_a_branch_that_moved(origin, tmp_path):
    """If someone pushes to the PR branch after our lookup, we must not clobber it."""
    run1 = tmp_path / "run1"
    checkout_like_actions(origin, run1)
    run_fix(run1, "uses: actions/checkout@v5\n", "run 1")
    assert push(run1).returncode == 0
    stale = remote_head(origin)

    other = tmp_path / "other"
    checkout_like_actions(origin, other)
    run_fix(other, "uses: actions/checkout@v6\n", "human edit")
    git(other, "push", "-q", "-f", "origin", f"HEAD:refs/heads/{BRANCH}")
    moved = remote_head(origin)

    r = git(run1, "push", "origin", f"HEAD:refs/heads/{BRANCH}",
            f"--force-with-lease=refs/heads/{BRANCH}:{stale}", check=False)
    assert r.returncode != 0 and "stale info" in r.stderr
    assert remote_head(origin) == moved


def test_bare_force_with_lease_is_rejected_without_fetch(origin, tmp_path):
    """Regression guard: documents the bug the fetch in the script works around."""
    run1 = tmp_path / "run1"
    checkout_like_actions(origin, run1)
    run_fix(run1, "uses: actions/checkout@v5\n", "run 1")
    assert push(run1).returncode == 0

    run2 = tmp_path / "run2"
    checkout_like_actions(origin, run2)
    run_fix(run2, "uses: actions/checkout@v6\n", "run 2")
    r = git(run2, "push", "-u", "origin", f"HEAD:refs/heads/{BRANCH}", "--force-with-lease",
            check=False)
    assert r.returncode != 0
    assert "stale info" in r.stderr
