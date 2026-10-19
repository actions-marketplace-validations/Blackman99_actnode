import json
import time

from actnode.core import (
    Resolver,
    apply_fixes,
    find_uses,
    is_reusable_workflow_path,
    list_org_repos,
    list_remote_workflows,
    node_major,
    parse_using,
    release_notes_url,
    scan,
    scan_org,
    scan_repo,
    split_ref,
)
from actnode.cli import main

RAW = "https://raw.githubusercontent.com/"
API = "https://api.github.com/repos/"


def node(v):
    return f"name: x\nruns:\n  using: 'node{v}'\n  main: index.js\n"


COMPOSITE = "runs:\n  using: composite\n  steps:\n    - uses: acme/old@v1\n    - uses: ./inner\n"
SHA5 = "b" * 40

REUSABLE = """\
jobs:
  call:
    steps:
      - uses: acme/old@v1
      - uses: acme/js@v4
"""

NESTED_REUSABLE = """\
jobs:
  call:
    uses: acme/inner-wf/.github/workflows/inner.yml@v1
"""

INNER_WF = """\
jobs:
  t:
    steps:
      - uses: acme/old@v1
"""

FILES = {
    RAW + "acme/js/v4/action.yml": node(20),
    RAW + "acme/js/v5.2.0/action.yml": node(24),
    RAW + "acme/js/v6.0.0/action.yml": node(24),
    RAW + "acme/js/" + "a" * 40 + "/action.yml": node(20),
    RAW + "acme/new/v2/action.yml": node(24),
    RAW + "acme/stuck/v1/action.yaml": node(16),
    RAW + "acme/stuck/v1.0.0/action.yaml": node(16),
    RAW + "acme/comp/v1/action.yml": COMPOSITE,
    RAW + "acme/comp/v1/inner/action.yml": node(24),
    RAW + "acme/old/v1/action.yml": node(20),
    RAW + "acme/old/v1.0.0/action.yml": node(20),
    RAW + "acme/shared/.github/workflows/build.yml/v1": None,  # wrong path form — real one below
    RAW + "acme/shared/v1/.github/workflows/build.yml": REUSABLE,
    RAW + "acme/outer-wf/v1/.github/workflows/outer.yml": NESTED_REUSABLE,
    RAW + "acme/inner-wf/v1/.github/workflows/inner.yml": INNER_WF,
    API + "acme/js/tags?per_page=100&page=1": json.dumps([
        {"name": n, "commit": {"sha": s}} for n, s in
        [("v6", "c" * 40), ("v6.0.0", "c" * 40), ("v5", SHA5), ("v5.2.0", SHA5), ("v4", "a" * 40), ("latest", "d" * 40)]
    ]),
    API + "acme/stuck/tags?per_page=100&page=1": json.dumps([{"name": "v1.0.0", "commit": {"sha": "e" * 40}}]),
    API + "acme/old/tags?per_page=100&page=1": json.dumps([{"name": "v1.0.0", "commit": {"sha": "f" * 40}}]),
    # remote repo listing
    API + "org/demo/contents/.github/workflows": json.dumps([
        {"name": "ci.yml", "path": ".github/workflows/ci.yml",
         "download_url": RAW + "org/demo/main/.github/workflows/ci.yml", "sha": "abc"},
        {"name": "README.md", "path": ".github/workflows/README.md", "download_url": None, "sha": "x"},
    ]),
    RAW + "org/demo/main/.github/workflows/ci.yml": (
        "jobs:\n  t:\n    steps:\n      - uses: acme/js@v4\n      - uses: acme/new@v2\n"
    ),
    API + "org/other/contents/.github/workflows": json.dumps([
        {"name": "lint.yml", "path": ".github/workflows/lint.yml",
         "download_url": RAW + "org/other/HEAD/.github/workflows/lint.yml", "sha": "def"},
    ]),
    RAW + "org/other/HEAD/.github/workflows/lint.yml": "jobs:\n  t:\n    steps:\n      - uses: acme/stuck@v1\n",
}


def fake(url):
    return FILES.get(url)


WF = """jobs:
  t:
    steps:
      - uses: acme/js@v4
      - name: pinned
        uses: acme/js@{a} # v4.0.0
      - uses: 'acme/new@v2'
      - uses: acme/stuck@v1
      - uses: acme/comp@v1
      - uses: docker://alpine:3
      - run: echo uses: nothing
""".format(a="a" * 40)


def repo(tmp_path):
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True)
    (d / "ci.yml").write_text(WF)
    return tmp_path


def test_helpers():
    assert node_major("node20") == 20 and node_major("composite") is None
    assert parse_using(node(16)) == "node16"
    assert split_ref("a/b/c/d@v1") == ("a", "b", "c/d", "v1")
    assert split_ref("./x") is None and split_ref("docker://x") is None
    assert [r for _, r, _ in find_uses(WF)][:3] == ["acme/js@v4", "acme/js@" + "a" * 40, "acme/new@v2"]
    assert is_reusable_workflow_path(".github/workflows/ci.yml")
    assert is_reusable_workflow_path(".github/workflows/ci.yaml")
    assert not is_reusable_workflow_path("subdir/action")
    assert not is_reusable_workflow_path(".github/actions/foo/action.yml")


def test_scan_classifies(tmp_path):
    fs = scan(repo(tmp_path), Resolver(fetch=fake, use_cache=False))
    by = {(f.uses, f.via): f for f in fs}
    assert by[("acme/js@v4", None)].suggest == "acme/js@v5"  # smallest jump that is on node24
    assert by[("acme/js@v4", None)].release_notes == "https://github.com/acme/js/releases/tag/v5"
    assert by[("acme/js@" + "a" * 40, None)].suggest == f"acme/js@{SHA5} # v5.2.0"
    assert by[("acme/js@" + "a" * 40, None)].release_notes == "https://github.com/acme/js/releases/tag/v5.2.0"
    assert by[("acme/new@v2", None)].status == "ok"
    assert by[("acme/stuck@v1", None)].status == "no-fix"
    assert by[("acme/comp@v1", None)].status == "composite"
    assert by[("acme/old@v1", "acme/comp@v1")].status == "no-fix"
    assert by[("acme/comp/inner@v1", "acme/comp@v1")].status == "ok"
    assert by[("docker://alpine:3", None)].status == "docker"


def test_fix_rewrites_only_direct(tmp_path):
    r = repo(tmp_path)
    fs = scan(r, Resolver(fetch=fake, use_cache=False))
    assert apply_fixes(r, fs) == 2
    txt = (r / ".github/workflows/ci.yml").read_text()
    assert "- uses: acme/js@v5\n" in txt
    assert f"uses: acme/js@{SHA5} # v5.2.0\n" in txt
    assert "acme/stuck@v1" in txt


def test_local_action(tmp_path):
    (tmp_path / "action.yml").write_text("runs:\n  using: composite\n  steps:\n    - uses: ./sub\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "action.yml").write_text(node(20))
    fs = scan(tmp_path, Resolver(fetch=fake, use_cache=False))
    assert any(f.status == "no-fix" and f.uses == "./sub" for f in fs)


def test_reusable_workflow(tmp_path):
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True)
    (d / "ci.yml").write_text(
        "jobs:\n  call:\n    uses: acme/shared/.github/workflows/build.yml@v1\n"
        "  local:\n    steps:\n      - uses: acme/new@v2\n"
    )
    fs = scan(tmp_path, Resolver(fetch=fake, use_cache=False))
    by = {(f.uses, f.via): f for f in fs}
    assert by[("acme/shared/.github/workflows/build.yml@v1", None)].status == "workflow"
    nested_old = by[("acme/old@v1", "acme/shared/.github/workflows/build.yml@v1")]
    assert nested_old.status == "no-fix"
    nested_js = by[("acme/js@v4", "acme/shared/.github/workflows/build.yml@v1")]
    assert nested_js.status == "old" and nested_js.suggest == "acme/js@v5"
    # --fix must not rewrite nested findings (via set)
    assert apply_fixes(tmp_path, fs) == 0


def test_nested_reusable_workflow_depth(tmp_path):
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True)
    (d / "ci.yml").write_text(
        "jobs:\n  call:\n    uses: acme/outer-wf/.github/workflows/outer.yml@v1\n"
    )
    fs = scan(tmp_path, Resolver(fetch=fake, use_cache=False), depth=3)
    vias = {f.uses: f.via for f in fs}
    assert vias.get("acme/outer-wf/.github/workflows/outer.yml@v1") is None
    assert vias.get("acme/inner-wf/.github/workflows/inner.yml@v1") == (
        "acme/outer-wf/.github/workflows/outer.yml@v1"
    )
    assert vias.get("acme/old@v1") == "acme/inner-wf/.github/workflows/inner.yml@v1"
    # depth=1: outer only, no nested inner expansion of old
    fs1 = scan(tmp_path, Resolver(fetch=fake, use_cache=False), depth=1)
    uses1 = {f.uses for f in fs1}
    assert "acme/outer-wf/.github/workflows/outer.yml@v1" in uses1
    assert "acme/inner-wf/.github/workflows/inner.yml@v1" in uses1
    assert "acme/old@v1" not in uses1  # depth exhausted before expanding inner


def test_local_reusable_workflow(tmp_path):
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True)
    (d / "reusable.yml").write_text("jobs:\n  t:\n    steps:\n      - uses: acme/old@v1\n")
    (d / "ci.yml").write_text("jobs:\n  call:\n    uses: ./.github/workflows/reusable.yml\n")
    fs = scan(tmp_path, Resolver(fetch=fake, use_cache=False))
    by = {(f.uses, f.via): f for f in fs}
    assert by[("./.github/workflows/reusable.yml", None)].status == "workflow"
    assert by[("acme/old@v1", "./.github/workflows/reusable.yml")].status == "no-fix"


def test_tag_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    fetches = []

    def counting(url):
        fetches.append(url)
        return FILES.get(url)

    r1 = Resolver(fetch=counting, use_cache=True, cache_path=cache / "actnode")
    tags1 = r1.tags("acme", "js")
    assert tags1
    tag_fetches = [u for u in fetches if "/tags?" in u]
    assert len(tag_fetches) == 1

    # Second resolver: should hit disk cache, no new tag API calls
    fetches.clear()
    r2 = Resolver(fetch=counting, use_cache=True, cache_path=cache / "actnode")
    tags2 = r2.tags("acme", "js")
    assert tags2 == tags1
    assert not any("/tags?" in u for u in fetches)

    # --no-cache / use_cache=False always hits network
    fetches.clear()
    r3 = Resolver(fetch=counting, use_cache=False, cache_path=cache / "actnode")
    r3.tags("acme", "js")
    assert any("/tags?" in u for u in fetches)

    # Corrupt / expired cache is ignored
    tag_file = cache / "actnode" / "tags" / "acme__js.json"
    tag_file.write_text("{not json", encoding="utf-8")
    fetches.clear()
    r4 = Resolver(fetch=counting, use_cache=True, cache_path=cache / "actnode")
    r4.tags("acme", "js")
    assert any("/tags?" in u for u in fetches)

    # Expired TTL
    tag_file.write_text(json.dumps({
        "fetched_at": time.time() - 999999,
        "tags": [["v1", "a" * 40]],
    }), encoding="utf-8")
    fetches.clear()
    r5 = Resolver(fetch=counting, use_cache=True, cache_path=cache / "actnode", cache_ttl=60)
    r5.tags("acme", "js")
    assert any("/tags?" in u for u in fetches)


def test_list_remote_workflows():
    items = list_remote_workflows("org", "demo", fake)
    assert len(items) == 1
    assert items[0][0] == ".github/workflows/ci.yml"


def test_scan_repo():
    fs = scan_repo("org", "demo", Resolver(fetch=fake, use_cache=False))
    by = {f.uses: f for f in fs if f.via is None}
    assert by["acme/js@v4"].status == "old"
    assert by["acme/js@v4"].file == "org/demo:.github/workflows/ci.yml"
    assert by["acme/new@v2"].status == "ok"


def test_scan_org(monkeypatch):
    org_repos = json.dumps([
        {"full_name": "org/demo", "fork": False, "archived": False},
        {"full_name": "org/forked", "fork": True, "archived": False},
        {"full_name": "org/other", "fork": False, "archived": False},
        {"full_name": "org/old", "fork": False, "archived": True},
    ])

    def fetch(url):
        if url.startswith("https://api.github.com/orgs/org/repos"):
            return org_repos
        return FILES.get(url)

    names = list(list_org_repos("org", fetch, include_forks=False))
    assert names == ["org/demo", "org/other"]

    fs = scan_org("org", Resolver(fetch=fetch, use_cache=False))
    files = {f.file for f in fs}
    assert "org/demo:.github/workflows/ci.yml" in files
    assert "org/other:.github/workflows/lint.yml" in files
    assert not any("forked" in f.file for f in fs)


def test_cli_json_and_fail(tmp_path, monkeypatch, capsys):
    import actnode.core as core

    monkeypatch.setattr(core, "http_get", fake)

    def fake_init(self, fetch=None, use_cache=True, cache_path=None, cache_ttl=86400, latest=False):
        self.fetch = fake
        self.use_cache = False
        self.cache_path = cache_path
        self.cache_ttl = cache_ttl
        self.latest = latest
        self._yml = {}
        self._tags = {}
        self._wf = {}

    monkeypatch.setattr(core.Resolver, "__init__", fake_init)
    r = repo(tmp_path)
    assert main([str(r), "--fail"]) == 1
    capsys.readouterr()
    assert main(["scan", str(r), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["target"] == 24 and len(data["findings"]) >= 6
    out = tmp_path / "s.md"
    main([str(r), "--format", "md", "-o", str(out)])
    assert "| Where |" in out.read_text()


def test_cli_repo_and_fix_refused(tmp_path, monkeypatch, capsys):
    import actnode.core as core

    monkeypatch.setattr(core, "http_get", fake)

    def fake_init(self, fetch=None, use_cache=True, cache_path=None, cache_ttl=86400, latest=False):
        self.fetch = fake
        self.use_cache = False
        self.cache_path = cache_path
        self.cache_ttl = cache_ttl
        self.latest = latest
        self._yml = {}
        self._tags = {}
        self._wf = {}

    monkeypatch.setattr(core.Resolver, "__init__", fake_init)
    assert main(["--repo", "org/demo", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert any(f["uses"] == "acme/js@v4" for f in data["findings"])
    assert main(["--repo", "org/demo", "--fix"]) == 2
    err = capsys.readouterr().err
    assert "local checkout" in err
    assert main(["--repo", "org/demo", "--org", "org"]) == 2
    assert main([".", "--repo", "org/demo"]) == 2


def test_release_notes_url():
    assert release_notes_url("acme/js@v5") == "https://github.com/acme/js/releases/tag/v5"
    assert release_notes_url("acme/js/sub@v5.2.0") == "https://github.com/acme/js/releases/tag/v5.2.0"
    assert release_notes_url(f"acme/js@{'a'*40} # v5.2.0") == "https://github.com/acme/js/releases/tag/v5.2.0"
    assert release_notes_url(f"acme/js@{'a'*40}") is None
    assert release_notes_url("") is None


def test_suggest_latest(tmp_path):
    """Default = smallest jump (v5); --latest / Resolver.latest = newest (v6)."""
    r = repo(tmp_path)
    fs = scan(r, Resolver(fetch=fake, use_cache=False, latest=False))
    by = {(f.uses, f.via): f for f in fs}
    assert by[("acme/js@v4", None)].suggest == "acme/js@v5"
    fs_latest = scan(r, Resolver(fetch=fake, use_cache=False, latest=True))
    by_l = {(f.uses, f.via): f for f in fs_latest}
    assert by_l[("acme/js@v4", None)].suggest == "acme/js@v6"
    assert by_l[("acme/js@v4", None)].release_notes == "https://github.com/acme/js/releases/tag/v6"
    assert by_l[("acme/js@" + "a" * 40, None)].suggest == f"acme/js@{'c'*40} # v6.0.0"


def test_cli_latest(tmp_path, monkeypatch, capsys):
    import actnode.core as core

    monkeypatch.setattr(core, "http_get", fake)

    def fake_init(self, fetch=None, use_cache=True, cache_path=None, cache_ttl=86400, latest=False):
        self.fetch = fake
        self.use_cache = False
        self.cache_path = cache_path
        self.cache_ttl = cache_ttl
        self.latest = latest
        self._yml = {}
        self._tags = {}
        self._wf = {}

    monkeypatch.setattr(core.Resolver, "__init__", fake_init)
    r = repo(tmp_path)
    assert main(["scan", str(r), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    js = next(f for f in data["findings"] if f["uses"] == "acme/js@v4" and not f.get("via"))
    assert js["suggest"] == "acme/js@v5"
    assert js["release_notes"] == "https://github.com/acme/js/releases/tag/v5"

    assert main(["scan", str(r), "--latest", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    js = next(f for f in data["findings"] if f["uses"] == "acme/js@v4" and not f.get("via"))
    assert js["suggest"] == "acme/js@v6"
    assert js["release_notes"] == "https://github.com/acme/js/releases/tag/v6"

    out = tmp_path / "notes.md"
    main([str(r), "--format", "md", "-o", str(out)])
    md = out.read_text()
    assert "Release notes" in md
    assert "https://github.com/acme/js/releases/tag/v5" in md


def test_pr_body_helper(tmp_path):
    import subprocess
    import sys
    from pathlib import Path as P

    report = tmp_path / "r.json"
    report.write_text(json.dumps({
        "target": 24,
        "findings": [{
            "file": ".github/workflows/ci.yml", "line": 7, "uses": "acme/js@v4",
            "runtime": "node20", "status": "old", "suggest": "acme/js@v5",
            "via": None, "note": "",
            "release_notes": "https://github.com/acme/js/releases/tag/v5",
        }],
    }), encoding="utf-8")
    root = P(__file__).resolve().parents[1]
    body = subprocess.check_output(
        [sys.executable, str(root / "pr_body.py"), str(report), "24"],
        text=True,
    )
    assert "Release notes" in body
    assert "acme/js@v5" in body
    assert "https://github.com/acme/js/releases/tag/v5" in body
