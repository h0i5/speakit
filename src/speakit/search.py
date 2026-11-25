"""App-wide search for the settings window: settings, pages, actions, key help,
word fixes and dictation history in one ranked list.

Ranking = keyword score (field-weighted, IDF, prefix-as-you-type, typo-tolerant)
fused with semantic similarity from bge-small-en-v1.5 (ONNX, CPU, ~34 MB, fetched
on first start) so "mute spotify" finds "Pause music while recording". Without the
model (offline first start) it is keyword-only. History queries also take filters:
an app name ("slack"), a mode ("cleanup", "command") and a day ("today", "yesterday").
"""
from __future__ import annotations

import math
import re
import threading
import time

from . import config as cfg

# Section -> page id in the settings app.
SECTION_PAGE = {"recording": "general", "feedback": "general", "typing": "typing",
                "cleanup": "cleanup", "history": "history", "model": "model"}
PAGES = [
    ("general", "General", "How recording starts, stops and sounds.", "keys hotkeys shortcuts"),
    ("typing", "Typing", "How text reaches the focused window.", "keyboard paste input"),
    ("cleanup", "Cleanup", "The local model behind Insert and End.", "llm ai grammar polish rewrite tone"),
    ("words", "Word fixes", "Names and jargon the speech model gets wrong.", "replacements dictionary vocabulary spelling snippets"),
    ("history", "History", "Your recent dictations, and what talking has saved you.", "past transcripts stats words per minute"),
    ("model", "Speech model", "Changes here take effect after a restart.", "asr parakeet transcription gpu cpu"),
]
ACTIONS = [
    ("restart", "Restart speakit", "Restart the daemon to apply speech model changes.", "model", "reload reboot apply service"),
    ("test-sound", "Play sounds", "Hear the start and stop cues.", "general", "test preview cue beep audio thock"),
]
HELP = [
    ("key-home", "Home: Dictate", "Types what you say, minus the ums. Tap to start and again to stop, or hold while you talk.", "general", "hotkey shortcut record start stop push to talk"),
    ("key-insert", "Insert: Clean up", "Fixes grammar and self-corrections, formats lists.", "general", "hotkey shortcut polish"),
    ("key-end", "End: Command", "Rewrites the selection the way you ask, or writes something new.", "general", "hotkey shortcut rewrite edit selection"),
    ("key-esc", "Esc: Cancel or undo", "Esc cancels a recording, or undoes a cleanup right after.", "general", "escape abort revert undo"),
    ("rebind", "Rebind keys", "Key bindings live in hyprland.conf.", "general", "change hotkey shortcut keybind"),
    ("tones", "Tone by app", "Terminals get backticks, chat apps casual, email polished.", "cleanup", "style formal casual slack gmail terminal"),
]
MODES = {"dictate": "raw", "dictation": "raw", "raw": "raw", "cleanup": "clean", "clean": "clean",
         "command": "command", "commands": "command"}
SWITCH_WORDS = {"on", "off", "enable", "disable", "enabled", "disabled", "toggle", "turn", "stop", "start"}
WEIGHTS = {"title": 1.0, "keywords": 0.8, "body": 0.55, "meta": 0.5}


# --- text -------------------------------------------------------------------------
def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def close(a: str, b: str, limit: int) -> bool:
    """Edit distance (with transpositions) between a and b is at most limit."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return False
        prev2, prev = prev, cur
    return prev[-1] <= limit


def match(q: str, w: str, last: bool) -> float:
    """How well query word q matches document word w (both stemmed)."""
    if q == w:
        return 1.0
    if w.startswith(q) and (len(q) >= 3 or (last and len(q) >= 2)):
        return 0.85 if last else 0.7
    if len(q) >= 4 and close(q, w, 1 if len(q) < 8 else 2):
        return 0.6
    return 0.0


# --- documents --------------------------------------------------------------------
def documents(history: list[dict], wordfixes: str) -> list[dict]:
    docs = []
    for pid, label, blurb, kw in PAGES:
        docs.append({"kind": "page", "id": pid, "page": pid, "title": label, "sub": blurb, "keywords": kw})
    for s in cfg.SETTINGS:
        page = SECTION_PAGE.get(s.section, "general")
        label = next(p[1] for p in PAGES if p[0] == page)
        docs.append({"kind": "setting", "id": s.name, "page": page, "title": s.label, "sub": s.help,
                     "keywords": f"{s.keywords} {s.section}", "meta": f"{label} {s.name.replace('_', ' ')}",
                     "value": getattr(cfg, s.name), "switch": isinstance(s.default, bool)})
    for aid, title, sub, page, kw in ACTIONS:
        docs.append({"kind": "action", "id": aid, "page": page, "title": title, "sub": sub, "keywords": kw})
    for hid, title, sub, page, kw in HELP:
        docs.append({"kind": "help", "id": hid, "page": page, "title": title, "sub": sub, "keywords": kw})
    for line in wordfixes.splitlines():
        if "=>" in line and not line.lstrip().startswith("#"):
            heard, meant = (x.strip() for x in line.split("=>", 1))
            docs.append({"kind": "wordfix", "id": line.strip(), "page": "words", "title": f"{heard} → {meant}",
                         "sub": "Word fix", "keywords": f"{heard} {meant}"})
    for h in history:
        if h.get("text"):
            docs.append({"kind": "history", "id": h.get("time", 0), "page": "history", "title": h["text"],
                         "sub": "", "meta": f"{h.get('app') or ''} {h.get('mode', '')}", "time": h.get("time", 0),
                         "app": h.get("app") or "", "mode": h.get("mode", "")})
    return docs


def semantic_text(d: dict) -> str:
    return f"{d['title']}. {d['sub']} {d.get('keywords', '')}".strip()


# --- query filters ----------------------------------------------------------------
def parse(query: str, docs: list[dict], now: float) -> tuple[list[str], dict]:
    """Query words left after pulling out history filters (app, mode, day)."""
    apps = {d["app"].lower() for d in docs if d.get("app")}
    out, f = [], {}
    ws = words(query)
    t = time.localtime(now)
    midnight = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    i = 0
    while i < len(ws):
        w, nxt = ws[i], ws[i + 1] if i + 1 < len(ws) else ""
        if w == "today":
            f["since"], f["until"] = midnight, math.inf
        elif w == "yesterday":
            f["since"], f["until"] = midnight - 86400, midnight
        elif w in ("this", "last", "past") and nxt in ("week", "month"):
            f["since"], f["until"] = now - (7 if nxt == "week" else 30) * 86400, math.inf
            i += 1
        elif w in apps and len(w) >= 3:
            f["app"] = w
        elif w in MODES and any(d["kind"] == "history" for d in docs):
            f["mode"] = MODES[w]
            out.append(w)  # "cleanup" is also a page/setting word; keep it for them
        else:
            out.append(w)
        i += 1
    return out, f


def passes(d: dict, f: dict) -> bool:
    if d["kind"] != "history":
        return not ({"since", "app"} & f.keys())  # a day/app filter means "search history"
    if "since" in f and not (f["since"] <= d["time"] < f["until"]):
        return False
    if "app" in f and d["app"].lower() != f["app"]:
        return False
    return "mode" not in f or d["mode"] == f["mode"]


# --- keyword score ----------------------------------------------------------------
def keyword_scores(qwords: list[str], docs: list[dict]) -> list[float]:
    fields = [{k: [stem(w) for w in words(str(d.get(k, "")))] for k in WEIGHTS} for d in docs]
    df: dict[str, int] = {}
    for fs in fields:
        for w in {w for ws in fs.values() for w in ws}:
            df[w] = df.get(w, 0) + 1
    n = len(docs)
    idf = lambda w: math.log(1 + n / (df.get(w, 0) + 1))  # noqa: E731
    qs = [stem(w) for w in qwords]
    scores = []
    for d, fs in zip(docs, fields):
        total = norm = 0.0
        for k, q in enumerate(qs):
            last = k == len(qs) - 1
            best = 0.0
            for field, weight in WEIGHTS.items():
                for w in fs[field]:
                    m = match(q, w, last)
                    if m:
                        best = max(best, weight * m * idf(w))
            total += best
            norm += max(idf(q), 1.0)
        s = total / norm if norm else 0.0
        title = d["title"].lower()
        phrase = " ".join(qwords)
        if phrase and title.startswith(phrase):
            s += 0.35
        elif phrase and len(qwords) > 1 and phrase in title:
            s += 0.2
        if d.get("switch") and SWITCH_WORDS & set(qwords):
            s += 0.1
        scores.append(s)
    return scores


# --- embeddings -------------------------------------------------------------------
REPO = "Xenova/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder:
    """bge-small on CPU, loaded in the background; vectors cached by text."""

    def __init__(self) -> None:
        self.session = self.tokenizer = None
        self.cache: dict[str, object] = {}
        self.lock = threading.Lock()

    def load(self) -> None:
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
            from tokenizers import Tokenizer
            def fetch(name: str) -> str:  # cached copy first: no network on every start
                try:
                    return hf_hub_download(REPO, name, local_files_only=True)
                except Exception:
                    return hf_hub_download(REPO, name)
            model = fetch("onnx/model_quantized.onnx")
            tok = Tokenizer.from_file(fetch("tokenizer.json"))
            tok.enable_truncation(256)
            tok.enable_padding()
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            self.session = ort.InferenceSession(model, opts, providers=["CPUExecutionProvider"])
            self.tokenizer = tok
        except Exception as e:  # offline first start, missing package: keyword-only
            print(f"speakit: semantic search off ({e})", flush=True)

    @property
    def ready(self) -> bool:
        return self.session is not None

    def encode(self, texts: list[str]):
        import numpy as np
        with self.lock:
            todo = [t for t in dict.fromkeys(texts) if t not in self.cache]
            for i in range(0, len(todo), 64):
                batch = todo[i:i + 64]
                enc = self.tokenizer.encode_batch(batch)
                ids = np.array([e.ids for e in enc], dtype=np.int64)
                mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
                out = self.session.run(None, {"input_ids": ids, "attention_mask": mask,
                                              "token_type_ids": np.zeros_like(ids)})[0][:, 0]  # CLS pooling
                out /= np.linalg.norm(out, axis=1, keepdims=True)
                self.cache.update(zip(batch, out))
            return np.stack([self.cache[t] for t in texts]) if texts else np.zeros((0, 384))


embedder = Embedder()


# --- search -----------------------------------------------------------------------
KIND_PRIOR = {"setting": 1.0, "action": 0.95, "page": 0.9, "help": 0.9, "wordfix": 0.85, "history": 0.8}


def search(query: str, history: list[dict], wordfixes: str, limit: int = 12, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    docs = documents(history, wordfixes)
    qwords, f = parse(query, docs, now)
    docs = [d for d in docs if passes(d, f)]
    if not docs:
        return []
    if not qwords:  # only filters ("yesterday", "slack"): newest matching history
        return sorted(docs, key=lambda d: -d.get("time", 0))[:limit] if f else []
    lex = keyword_scores(qwords, docs)
    sem = [0.0] * len(docs)
    if embedder.ready and len(" ".join(qwords)) >= 3:
        vecs = embedder.encode([semantic_text(d) for d in docs])
        q = embedder.encode([QUERY_PREFIX + " ".join(qwords)])[0]
        sims = vecs @ q
        # bge-small's absolute similarities drift per query (nonsense still scores ~0.5), so score
        # each doc by how far it stands above this query's median: junk tops out ~+0.06, hits +0.1..0.2.
        mid = float(sorted(sims)[len(sims) // 2])
        sem = [max(0.0, min(1.0, (float(s) - mid - 0.07) / 0.12)) for s in sims]
    out = []
    for d, l, s in zip(docs, lex, sem):
        score = max(l, 0.0) + 0.6 * s + 0.25 * min(l, 1.0) * s  # agreement bonus
        if score < 0.3:
            continue
        score *= KIND_PRIOR[d["kind"]]
        if d["kind"] == "history":
            age_days = max(0.0, (now - d["time"]) / 86400)
            score *= 1 / (1 + age_days / 60) ** 0.25  # gentle recency
        out.append((score, d))
    out.sort(key=lambda x: -x[0])
    top = out[0][0] if out else 0
    return [{**d, "score": round(sc, 3)} for sc, d in out[:limit] if sc >= top * 0.35]


if __name__ == "__main__":
    assert close("pasue", "pause", 1) and close("microphon", "microphone", 1) and not close("sound", "model", 1)
    assert match("mic", "microphone", True) and not match("zz", "pause", False)
    now = time.time()
    hist = [{"time": now - 60, "mode": "clean", "app": "slack", "text": "Running late, be there in ten"},
            {"time": now - 2 * 86400, "mode": "raw", "app": "kitty", "text": "git rebase the feature branch"}]
    fixes = "cloud code => Claude Code\n# comment"
    def top(q: str) -> str:
        r = search(q, hist, fixes)
        return r[0]["id"] if r else ""
    assert top("pause music") == "PAUSE_MEDIA", search("pause music", hist, fixes)[:2]
    assert top("pasue") == "PAUSE_MEDIA"          # typo
    assert top("micro") == "MIC_TARGET"           # prefix while typing
    assert top("restart") == "restart"
    assert top("claude") == "cloud code => Claude Code"
    assert top("slack") == now - 60               # app filter -> that app's history
    assert [r["id"] for r in search("yesterday", hist, fixes)] == []
    assert top("rebase") == now - 2 * 86400
    assert search("qqqzzz", hist, fixes) == []
    print("keyword ok")
    embedder.load()
    if embedder.ready:
        for q, want in [("mute spotify", "PAUSE_MEDIA"), ("how do i cancel", "key-esc"),
                        ("use the graphics card", "DEVICE"), ("typing too fast characters missing", "KEY_HOLD")]:
            print(f"{q!r:40} -> {[r['id'] for r in search(q, hist, fixes)[:3]]}  (want {want})")
