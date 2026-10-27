"""Find GitHub Actions steps whose action runs on an old Node.js runtime, and the release that fixes it."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

CURRENT = 24  # the Node.js runtime GitHub-hosted runners default to since 2026-06-02
USES_RE = re.compile(r"""^(?P<pre>\s*(?:-\s+)?uses:\s*)(?P<q>['"]?)(?P<ref>[^'"\s#]+)(?P=q)(?P<post>.*)$""")
USING_RE = re.compile(r"""^\s+using:\s*['"]?([A-Za-z0-9_-]+)""", re.M)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VER_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")
WORKFLOW_SUB_RE = re.compile(r"^\.github/workflows/[^/]+\.(yml|yaml)$")
DEFAULT_CACHE_TTL = 24 * 3600  # 24 hours

Fetcher = Callable[[str], Optional[str]]


def _token() -> Optional[str]:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def http_get(url: str) -> Optional[str]:
    """GET a URL, return text or None on 404. Uses GITHUB_TOKEN/GH_TOKEN for api.github.com."""
    req = urllib.request.Request(url, headers={"User-Agent": "actnode"})
    tok = _token()
    if tok and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", f"Bearer {tok}")
        req.add_header("Accept", "application/vnd.github+json")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429):
                raise RuntimeError(
                    f"GitHub rate limit hit on {url}. Set GITHUB_TOKEN (or GH_TOKEN) and retry."
                ) from e
            if e.code >= 500 and attempt < 2:
                time.sleep(1 + 2 * attempt)  # transient GitHub 5xx: retry
                continue
            raise
    return None


def cache_dir() -> Path:
    """`$XDG_CACHE_HOME/actnode` if set, else `~/.cache/actnode`."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "actnode"
    return Path.home() / ".cache" / "actnode"


def node_major(using: Optional[str]) -> Optional[int]:
    if not using:
        return None
    m = re.fullmatch(r"node(\d+)", using.strip().lower())
    return int(m.group(1)) if m else None


def parse_using(action_yml: str) -> Optional[str]:
    m = USING_RE.search(action_yml)
    return m.group(1) if m else None


def find_uses(text: str):
    """Yield (line_no, ref, comment) for every `uses:` in a workflow or composite action."""
    for i, line in enumerate(text.splitlines(), 1):
        m = USES_RE.match(line)
        if m:
            yield i, m.group("ref"), m.group("post").strip()


def split_ref(ref: str):
    """'owner/repo/sub/path@ref' -> (owner, repo, subpath, ref). None for local/docker refs."""
    if ref.startswith("./") or ref.startswith("docker://") or "@" not in ref:
        return None
    spec, _, at = ref.rpartition("@")
    parts = spec.split("/")
    if len(parts) < 2:
        return None
    return parts[0], parts[1], "/".join(parts[2:]), at


def is_reusable_workflow_path(subpath: str) -> bool:
    """True if subpath looks like `.github/workflows/name.yml` (a reusable workflow)."""
    return bool(subpath and WORKFLOW_SUB_RE.match(subpath))


def _ver(tag: str):
    m = VER_RE.match(tag)
    if not m:
        return None
    return tuple(int(x) if x else -1 for x in m.groups())


def release_notes_url(suggest: str) -> Optional[str]:
    """GitHub releases page for the tag in a suggest ref (e.g. owner/repo@v5 → …/releases/tag/v5)."""
    if not suggest:
        return None
    ref_part, _, comment = suggest.partition(" # ")
    tag = comment.strip() if comment.strip() else None
    if "@" not in ref_part:
        return None
    spec, _, at = ref_part.rpartition("@")
    parts = spec.split("/")
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if tag is None:
        tag = at
    if not tag or SHA_RE.match(tag):
        return None
    return f"https://github.com/{owner}/{repo}/releases/tag/{tag}"


def _pick_issue(items, target=CURRENT) -> Optional[dict]:
    """Choose the best search hit: title must mention node{target}; open first, then most comments."""
    pat = re.compile(rf"node(?:\.?js)?[\s-]*{target}\b", re.I)
    cands = [i for i in items if isinstance(i, dict) and pat.search(i.get("title") or "")]
    if not cands:
        return None
    cands.sort(key=lambda i: (i.get("state") == "open", i.get("comments") or 0), reverse=True)
    i = cands[0]
    return {
        "url": i.get("html_url"),
        "title": i.get("title"),
        "state": i.get("state"),
        "number": i.get("number"),
        "kind": "pr" if "pull_request" in i else "issue",
    }


@dataclass
class Finding:
    file: str
    line: int
    uses: str
    runtime: Optional[str]
    status: str  # ok | old | unknown | no-fix | local | docker | composite | workflow
    suggest: Optional[str] = None
    via: Optional[str] = None  # composite/reusable workflow that pulled this in
    note: str = ""
    release_notes: Optional[str] = None  # GitHub releases URL for the suggested tag
    upstream_issue: Optional[dict] = None  # {url, title, state, number} tracking the node bump upstream

    def to_dict(self):
        return asdict(self)


@dataclass
class Resolver:
    fetch: Fetcher = http_get
    use_cache: bool = True
    cache_path: Optional[Path] = None  # override for tests; default cache_dir()
    cache_ttl: int = DEFAULT_CACHE_TTL
    latest: bool = False  # True → newest node{target} release; False → smallest major jump
    upstream: bool = True  # look up an upstream issue/PR for actions with no node{target} release
    _yml: dict = field(default_factory=dict)
    _tags: dict = field(default_factory=dict)
    _wf: dict = field(default_factory=dict)
    _issues: dict = field(default_factory=dict)
    _archived: dict = field(default_factory=dict)

    def _cache_root(self) -> Path:
        return self.cache_path if self.cache_path is not None else cache_dir()

    def action_yml(self, owner, repo, sub, ref) -> Optional[str]:
        key = (owner, repo, sub, ref)
        if key not in self._yml:
            base = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/" + (sub + "/" if sub else "")
            txt = None
            for name in ("action.yml", "action.yaml"):
                txt = self.fetch(base + name)
                if txt is not None:
                    break
            self._yml[key] = txt
        return self._yml[key]

    def workflow_yml(self, owner, repo, sub, ref) -> Optional[str]:
        """Fetch a reusable workflow YAML from raw.githubusercontent.com."""
        key = (owner, repo, sub, ref)
        if key not in self._wf:
            url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{sub}"
            self._wf[key] = self.fetch(url)
        return self._wf[key]

    def tags(self, owner, repo):
        """Return list of (name, sha) for version-like tags, newest first.

        Uses an in-memory cache for the run, and optionally a disk cache under
        ~/.cache/actnode (or $XDG_CACHE_HOME/actnode) with a 24h TTL.
        """
        key = (owner, repo)
        if key not in self._tags:
            cached = self._load_tag_cache(owner, repo) if self.use_cache else None
            if cached is not None:
                self._tags[key] = cached
            else:
                out = []
                for page in (1, 2, 3):
                    body = self.fetch(
                        f"https://api.github.com/repos/{owner}/{repo}/tags?per_page=100&page={page}"
                    )
                    if not body:
                        break
                    data = json.loads(body)
                    out += [(t["name"], t["commit"]["sha"]) for t in data if _ver(t["name"])]
                    if len(data) < 100:
                        break
                out.sort(key=lambda t: (_ver(t[0]), len(t[0])), reverse=True)
                self._tags[key] = out
                if self.use_cache:
                    self._save_tag_cache(owner, repo, out)
        return self._tags[key]

    def _tag_cache_file(self, owner, repo) -> Path:
        safe = f"{owner}__{repo}.json".replace("/", "_")
        return self._cache_root() / "tags" / safe

    def _load_tag_cache(self, owner, repo):
        path = self._tag_cache_file(owner, repo)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(data.get("fetched_at", 0)) > self.cache_ttl:
                return None
            tags = data.get("tags")
            if not isinstance(tags, list):
                return None
            out = []
            for item in tags:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    out.append((item[0], item[1]))
                elif isinstance(item, dict) and "name" in item and "sha" in item:
                    out.append((item["name"], item["sha"]))
                else:
                    return None
            return out
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError):
            return None

    def _save_tag_cache(self, owner, repo, tags):
        path = self._tag_cache_file(owner, repo)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"fetched_at": time.time(), "tags": [[n, s] for n, s in tags]}
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass

    def archived(self, owner, repo) -> bool:
        """True if the action's repo is archived (read-only: no node bump will ever ship)."""
        key = (owner, repo)
        if key not in self._archived:
            try:
                body = self.fetch(f"https://api.github.com/repos/{owner}/{repo}")
                self._archived[key] = bool(body and json.loads(body).get("archived"))
            except (RuntimeError, OSError, ValueError, urllib.error.URLError, AttributeError):
                self._archived[key] = False
        return self._archived[key]

    def upstream_issue(self, owner, repo, target=CURRENT) -> Optional[dict]:
        """Find the upstream issue or PR tracking the move to node{target}.

        One GitHub search per repo per run (disk-cached like tags). Prefers open items,
        then the most-commented. Never raises: a failed lookup just returns None.
        """
        key = (owner, repo, target)
        if key in self._issues:
            return self._issues[key]
        cache = self._cache_root() / "issues" / f"{owner}__{repo}__node{target}.json".replace("/", "_")
        hit = None
        found = False
        if self.use_cache:
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                if time.time() - float(data.get("fetched_at", 0)) <= self.cache_ttl:
                    hit, found = data.get("issue"), True
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        if not found:
            q = f'repo:{owner}/{repo} node{target} OR "node {target}" OR "node.js {target}" in:title'
            url = ("https://api.github.com/search/issues?per_page=20&q="
                   + urllib.parse.quote(q))
            try:
                body = self.fetch(url)
                items = (json.loads(body).get("items") or []) if body else []
            except (RuntimeError, OSError, ValueError, urllib.error.URLError):
                self._issues[key] = None
                return None  # rate-limited or offline: don't cache the miss
            hit = _pick_issue(items, target)
            if self.use_cache:
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps({"fetched_at": time.time(), "issue": hit}), encoding="utf-8")
                except OSError:
                    pass
        self._issues[key] = hit
        return hit

    def suggest(self, owner, repo, sub, ref, target=CURRENT) -> Optional[str]:
        """Replacement ref whose action runs on node>=target, in the same ref style.

        Default (latest=False): smallest major jump that is already on target Node.
        With self.latest=True: newest release that already runs on target Node.
        """
        tags = self.tags(owner, repo)
        if not tags:
            return None
        majors = []
        for name, sha in tags:
            mj = _ver(name)[0]
            if mj not in majors:
                majors.append(mj)
        cur = _ver(ref)[0] if _ver(ref) else None
        best = None
        for mj in majors[:6]:  # newest majors first
            if cur is not None and mj < cur:
                break
            in_major = [(n, s) for n, s in tags if _ver(n)[0] == mj]
            full = [t for t in in_major if _ver(t[0])[2] >= 0] or in_major
            newest_name, newest_sha = full[0]
            y = self.action_yml(owner, repo, sub, newest_name)
            ul = (parse_using(y) or "") if y else ""
            nm = node_major(ul)
            if y is None or (nm is not None and nm < target):
                if best:
                    break
                continue
            best = (mj, in_major, newest_name, newest_sha)
            if self.latest:
                break  # first match is the newest target-Node major
        if not best:
            return None
        mj, in_major, newest_name, newest_sha = best
        spec = f"{owner}/{repo}" + (f"/{sub}" if sub else "")
        if SHA_RE.match(ref):
            return f"{spec}@{newest_sha} # {newest_name}"
        v = _ver(ref)
        if v and v[1] == -1:
            short = [n for n, _ in in_major if _ver(n)[1] == -1]
            return f"{spec}@{short[0] if short else newest_name}"
        return f"{spec}@{newest_name}"


def workflow_files(root: Path):
    files = []
    for d in (root / ".github" / "workflows",):
        if d.is_dir():
            files += sorted(p for p in d.iterdir() if p.suffix in (".yml", ".yaml"))
    for name in ("action.yml", "action.yaml"):
        if (root / name).is_file():
            files.append(root / name)
    return files


def list_remote_workflows(owner: str, repo: str, fetch: Fetcher = http_get):
    """List workflow file paths via the GitHub Contents API. Returns [(path, download_url|None)]."""
    body = fetch(f"https://api.github.com/repos/{owner}/{repo}/contents/.github/workflows")
    if not body:
        return []
    data = json.loads(body)
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        name = item.get("name") or ""
        if not name.endswith((".yml", ".yaml")):
            continue
        path = item.get("path") or f".github/workflows/{name}"
        out.append((path, item.get("download_url"), item.get("sha")))
    return out


def fetch_remote_file(owner: str, repo: str, path: str, ref: str, fetch: Fetcher,
                      download_url: Optional[str] = None) -> Optional[str]:
    if download_url:
        txt = fetch(download_url)
        if txt is not None:
            return txt
    return fetch(f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}")


def list_org_repos(owner: str, fetch: Fetcher = http_get, include_forks: bool = False):
    """List public non-fork repos for an org (falls back to user repos). Yields 'owner/name'."""
    # Try org endpoint first; on 404 fall back to user repos.
    for kind in ("orgs", "users"):
        page = 1
        found_any = False
        while page <= 10:
            body = fetch(
                f"https://api.github.com/{kind}/{owner}/repos?per_page=100&page={page}"
                f"&type=public&sort=full_name"
            )
            if body is None:
                break
            data = json.loads(body)
            if not isinstance(data, list):
                break
            if not data and page == 1 and kind == "orgs":
                break  # try users
            found_any = True
            for repo in data:
                if repo.get("archived"):
                    continue
                if not include_forks and repo.get("fork"):
                    continue
                full = repo.get("full_name")
                if full:
                    yield full
            if len(data) < 100:
                return
            page += 1
        if found_any:
            return


def scan(root: Path, resolver: Optional[Resolver] = None, target: int = CURRENT, depth: int = 3):
    resolver = resolver or Resolver()
    findings: list[Finding] = []
    for f in workflow_files(root):
        rel = str(f.relative_to(root))
        for line, ref, _c in find_uses(f.read_text(encoding="utf-8")):
            findings += _check(root, rel, line, ref, resolver, target, depth, via=None)
    return findings


def scan_repo(owner: str, repo: str, resolver: Optional[Resolver] = None,
              target: int = CURRENT, depth: int = 3, ref: str = "HEAD"):
    """Scan a remote repo's workflows via the GitHub API (no clone)."""
    resolver = resolver or Resolver()
    findings: list[Finding] = []
    file_label = f"{owner}/{repo}"
    for path, download_url, _sha in list_remote_workflows(owner, repo, resolver.fetch):
        text = fetch_remote_file(owner, repo, path, ref, resolver.fetch, download_url)
        if text is None:
            findings.append(Finding(
                f"{file_label}:{path}", 0, path, None, "unknown",
                note="could not fetch workflow file",
            ))
            continue
        rel = f"{file_label}:{path}"
        for line, uref, _c in find_uses(text):
            findings += _check(None, rel, line, uref, resolver, target, depth, via=None)
    return findings


def scan_org(owner: str, resolver: Optional[Resolver] = None, target: int = CURRENT,
             depth: int = 3, include_forks: bool = False):
    """Scan all public non-fork repos for an org/user. Aggregates findings with owner/repo:path."""
    resolver = resolver or Resolver()
    findings: list[Finding] = []
    for full in list_org_repos(owner, resolver.fetch, include_forks=include_forks):
        o, _, name = full.partition("/")
        findings += scan_repo(o, name, resolver, target, depth)
    return findings


def _local_workflow_text(root: Optional[Path], ref: str) -> Optional[str]:
    """If ref is a local reusable workflow path, return its text."""
    if root is None or not ref.startswith("./"):
        return None
    p = (root / ref[2:]).resolve()
    try:
        # stay inside root
        p.relative_to(root.resolve())
    except ValueError:
        return None
    if p.is_file() and p.suffix in (".yml", ".yaml"):
        # Prefer .github/workflows/, but also accept any local .yml that is used as a workflow
        return p.read_text(encoding="utf-8")
    return None


def _check(root, rel, line, ref, r: Resolver, target, depth, via):
    if ref.startswith("docker://"):
        return [Finding(rel, line, ref, "docker", "docker", via=via)]

    # Local reusable workflow: ./.github/workflows/x.yml
    if ref.startswith("./") and (
        is_reusable_workflow_path(ref[2:])
        or (ref.endswith((".yml", ".yaml")) and "/.github/workflows/" in ("/" + ref[2:]))
        or (root is not None and _looks_like_local_workflow(root, ref))
    ):
        text = _local_workflow_text(root, ref)
        if text is None:
            return [Finding(rel, line, ref, None, "unknown", via=via, note="local workflow not found")]
        out = [Finding(rel, line, ref, "workflow", "workflow", via=via)]
        if depth > 0:
            for _l, sub_ref, _c in find_uses(text):
                for f in _check(root, rel, line, sub_ref, r, target, depth - 1, via=ref):
                    out.append(f)
        return out

    if ref.startswith("./"):
        if root is None:
            return [Finding(rel, line, ref, None, "unknown", via=via, note="local ref in remote scan")]
        p = root / ref[2:]
        y = None
        for name in ("action.yml", "action.yaml"):
            if (p / name).is_file():
                y = (p / name).read_text(encoding="utf-8")
                break
        if y is None:
            # Maybe it's a workflow file used without the standard path layout
            if p.is_file() and p.suffix in (".yml", ".yaml"):
                text = p.read_text(encoding="utf-8")
                out = [Finding(rel, line, ref, "workflow", "workflow", via=via)]
                if depth > 0:
                    for _l, sub_ref, _c in find_uses(text):
                        for f in _check(root, rel, line, sub_ref, r, target, depth - 1, via=ref):
                            out.append(f)
                return out
            return [Finding(rel, line, ref, None, "unknown", via=via, note="local action.yml not found")]
        return _classify(root, rel, line, ref, y, None, r, target, depth, via)

    parts = split_ref(ref)
    if not parts:
        return [Finding(rel, line, ref, None, "unknown", via=via, note="unpinned or unparseable ref")]
    owner, repo, sub, at = parts

    # Remote reusable workflow
    if is_reusable_workflow_path(sub):
        text = r.workflow_yml(owner, repo, sub, at)
        if text is None:
            return [Finding(rel, line, ref, None, "unknown", via=via, note="reusable workflow not found")]
        out = [Finding(rel, line, ref, "workflow", "workflow", via=via)]
        if depth > 0:
            for _l, sub_ref, _c in find_uses(text):
                # Resolve local ./ refs against the reusable workflow's repo (same as composites)
                if sub_ref.startswith("./"):
                    local_path = sub_ref[2:].rstrip("/")
                    if is_reusable_workflow_path(local_path) or local_path.endswith((".yml", ".yaml")):
                        sub_ref = f"{owner}/{repo}/{local_path}@{at}"
                    else:
                        sub_ref = f"{owner}/{repo}/{local_path}@{at}"
                for f in _check(root, rel, line, sub_ref, r, target, depth - 1, via=ref):
                    out.append(f)
        return out

    y = r.action_yml(owner, repo, sub, at)
    if y is None:
        # Fallback: maybe someone pointed at a workflow-like path we didn't catch, or a missing action
        return [Finding(rel, line, ref, None, "unknown", via=via, note="action.yml not found at that ref")]
    return _classify(root, rel, line, ref, y, parts, r, target, depth, via)


def _looks_like_local_workflow(root: Path, ref: str) -> bool:
    if not ref.startswith("./"):
        return False
    p = root / ref[2:]
    return p.is_file() and p.suffix in (".yml", ".yaml") and "action.yml" not in p.name and "action.yaml" not in p.name


def _classify(root, rel, line, ref, y, parts, r, target, depth, via):
    using = parse_using(y)
    nm = node_major(using)
    out = []
    if nm is not None:
        if nm >= target:
            out.append(Finding(rel, line, ref, using, "ok", via=via))
        else:
            sug = r.suggest(*parts, target=target) if parts else None
            st = "old" if sug else "no-fix"
            note = "" if sug else ("local action: bump runs.using" if not parts
                                   else f"no release on node{target} yet; ask upstream or fork")
            rn = release_notes_url(sug) if sug else None
            up = None
            if not sug and parts and r.upstream:
                if r.archived(parts[0], parts[1]):
                    note = f"no release on node{target}; upstream repo is archived, replace the action"
                else:
                    up = r.upstream_issue(parts[0], parts[1], target)
                if up:
                    note = f"no release on node{target} yet; upstream {up['kind']} #{up['number']} ({up['state']})"
            out.append(Finding(
                rel, line, ref, using, st, suggest=sug, via=via, note=note, release_notes=rn,
                upstream_issue=up,
            ))
    elif using == "composite":
        out.append(Finding(rel, line, ref, using, "composite", via=via))
        if depth > 0:
            for _l, sub_ref, _c in find_uses(y):
                if sub_ref.startswith("./") and parts:
                    o, rp, _s, at = parts
                    sub_ref = f"{o}/{rp}/{sub_ref[2:].rstrip('/')}@{at}"
                for f in _check(root, rel, line, sub_ref, r, target, depth - 1, via=ref):
                    out.append(f)
    else:
        out.append(Finding(rel, line, ref, using, "docker" if using == "docker" else "unknown", via=via))
    return out


def apply_fixes(root: Path, findings) -> int:
    """Rewrite direct `uses:` lines that have a suggestion. Returns number of lines changed.

    Only rewrites findings with via=None (not nested inside composites or reusable workflows).
    Skips remote file labels (owner/repo:path).
    """
    by_file: dict = {}
    for f in findings:
        if f.status == "old" and f.suggest and f.via is None:
            if ":" in f.file and not Path(f.file).exists():
                # remote scan label like owner/repo:.github/workflows/ci.yml
                continue
            by_file.setdefault(f.file, {})[f.line] = f
    changed = 0
    for rel, lines in by_file.items():
        p = root / rel
        if not p.is_file():
            continue
        src = p.read_text(encoding="utf-8").splitlines(keepends=True)
        for ln, f in lines.items():
            raw = src[ln - 1]
            nl = raw[len(raw.rstrip("\r\n")):]
            m = USES_RE.match(raw.rstrip("\r\n"))
            if not m or m.group("ref") != f.uses:
                continue
            new_ref, _, comment = f.suggest.partition(" # ")
            post = m.group("post")
            if comment:
                post = f" # {comment}"
            src[ln - 1] = f"{m.group('pre')}{m.group('q')}{new_ref}{m.group('q')}{post}{nl}"
            changed += 1
        p.write_text("".join(src), encoding="utf-8")
    return changed
