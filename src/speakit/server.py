"""Settings UI server: static files from ui/dist + a small JSON API.

Loopback only. Every /api call must carry the per-start random token
(X-Speakit-Token), which only the launcher can read from the 0600 token file:
other local web pages can't forge it, and a custom header forces a CORS
preflight we never answer. The Host check stops DNS-rebinding.
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

from . import config as cfg
from . import desktop as dk
from . import history as hist
from . import search as srch

if TYPE_CHECKING:
    from .daemon import Daemon


def _llm_up() -> bool:
    base = cfg.LLM_URL.split("/v1/")[0]
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=0.5) as r:
            return r.status == 200
    except OSError:
        return False


def _search_inputs(daemon: "Daemon") -> tuple[list[dict], str]:
    try:
        fixes = cfg.REPLACEMENTS_PATH.read_text()
    except OSError:
        fixes = ""
    return (hist.load() if cfg.SAVE_HISTORY else list(daemon.history)), fixes


def serve(daemon: "Daemon") -> None:
    def warm() -> None:  # load the embedding model, then embed everything once
        srch.embedder.load()
        if srch.embedder.ready:
            srch.search("warm up", *_search_inputs(daemon))
    threading.Thread(target=warm, daemon=True).start()
    token = secrets.token_urlsafe(24)
    fd = os.open(cfg.UI_TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    port = cfg.UI_PORT
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):  # keep the journal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: object, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode())

        def _authed(self) -> bool:
            if self.headers.get("Host") not in hosts:
                self._json({"error": "bad host"}, 403)
                return False
            if not self.path.startswith("/api/"):
                return True
            if not secrets.compare_digest(self.headers.get("X-Speakit-Token", ""), token):
                self._json({"error": "bad token"}, 401)
                return False
            return True

        def _body(self) -> object:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(min(n, 1_000_000)) or b"null")

        def do_GET(self) -> None:
            if not self._authed():
                return
            p = self.path.split("?")[0]
            if p == "/api/settings":
                values = {s.name: getattr(cfg, s.name) for s in cfg.SETTINGS}
                schema = [{**s.__dict__, "choices": list(s.choices)} for s in cfg.SETTINGS]
                return self._json({"schema": schema, "values": values,
                                   "env": sorted(cfg.env_overrides()), "path": str(cfg.CONFIG_PATH)})
            if p == "/api/status":
                return self._json({"state": daemon.state, "model": cfg.MODEL, "device": cfg.DEVICE,
                                   "model_ready": daemon.model is not None, "llm": _llm_up()})
            if p == "/api/replacements":
                try:
                    text = cfg.REPLACEMENTS_PATH.read_text()
                except OSError:
                    text = ""
                return self._json({"text": text, "path": str(cfg.REPLACEMENTS_PATH)})
            if p == "/api/history":
                return self._json(list(reversed(daemon.history)))
            if p == "/api/search":
                from urllib.parse import parse_qs, urlsplit
                q = parse_qs(urlsplit(self.path).query).get("q", [""])[0][:200]
                return self._json({"results": srch.search(q, *_search_inputs(daemon)), "semantic": srch.embedder.ready})
            if p == "/api/stats":
                return self._json(hist.stats(hist.load() if cfg.SAVE_HISTORY else list(daemon.history)))
            if p.startswith("/api/"):
                return self._json({"error": "not found"}, 404)
            # Static UI (SPA: unknown paths serve index.html).
            f = (cfg.UI_DIST / p.lstrip("/")).resolve()
            if not f.is_relative_to(cfg.UI_DIST.resolve()) or not f.is_file():
                f = cfg.UI_DIST / "index.html"
            if not f.is_file():
                return self._send(503, b"settings UI not built: cd ui && pnpm install && pnpm build", "text/plain")
            self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")

        def do_PUT(self) -> None:
            if not self._authed():
                return
            p = self.path.split("?")[0]
            try:
                body = self._body()
                if p == "/api/settings":
                    cfg.save(dict(body))
                    return self._json({"ok": True, "values": {s.name: getattr(cfg, s.name) for s in cfg.SETTINGS}})
                if p == "/api/replacements":
                    cfg.REPLACEMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
                    cfg.REPLACEMENTS_PATH.write_text(str(body["text"]))
                    return self._json({"ok": True})
            except (ValueError, KeyError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
            self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            if not self._authed():
                return
            p = self.path.split("?")[0]
            if p == "/api/test-sound":
                dk.play(daemon.cues[0])
                threading.Timer(0.6, dk.play, (daemon.cues[1],)).start()
                return self._json({"ok": True})
            if p == "/api/restart":
                # Non-zero exit: systemd's Restart=on-failure brings us back.
                threading.Timer(0.3, os._exit, (75,)).start()
                return self._json({"ok": True})
            self._json({"error": "not found"}, 404)

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
