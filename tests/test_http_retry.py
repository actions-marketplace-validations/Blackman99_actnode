import io
import urllib.error

from actnode import core


def test_http_get_retries_5xx(monkeypatch):
    calls = []

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=20):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 500, "x", {}, None)
        return R(b"ok")

    monkeypatch.setattr(core.urllib.request, "urlopen", fake)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    assert core.http_get("https://api.github.com/x") == "ok"
    assert len(calls) == 3
