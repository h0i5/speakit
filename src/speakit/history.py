"""Dictation history on disk (one JSON object per line) and the stats it feeds."""
from __future__ import annotations

import json
import os
import time

from . import config as cfg


def load() -> list[dict]:
    # ponytail: reads the whole file per call; fine for years of dictation
    # (~200 B each), keep running totals if it ever gets slow.
    try:
        lines = cfg.HISTORY_PATH.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def append(entry: dict) -> None:
    cfg.HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 0600: transcripts are private.
    fd = os.open(cfg.HISTORY_PATH, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(entry) + "\n")


TYPING_WPM = 40  # what "time saved" compares against


def stats(items: list[dict], now: float | None = None) -> dict:
    now = time.time() if now is None else now
    t = time.localtime(now)
    midnight = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))

    def words(i: dict) -> int:
        return len(i.get("text", "").split())

    timed = [i for i in items if i.get("secs")]
    spoken = sum(words(i) for i in timed)
    secs = sum(i["secs"] for i in timed)
    return {
        "dictations": len(items),
        "words": sum(words(i) for i in items),
        "today": sum(words(i) for i in items if i.get("time", 0) >= midnight),
        "wpm": round(spoken / secs * 60) if secs else 0,
        "minutes_saved": max(0, round(spoken / TYPING_WPM - secs / 60)),
    }


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    cfg.HISTORY_PATH = Path(tempfile.mkdtemp()) / "h.jsonl"
    assert load() == []
    now = time.time()
    append({"time": now, "text": "one two three four", "secs": 2.0})
    append({"time": now - 3 * 86400, "text": "five six", "secs": 1.0})
    cfg.HISTORY_PATH.open("a").write("not json\n")
    append({"time": now, "text": "seven"})  # no secs: counts words, not speed
    items = load()
    assert len(items) == 3
    s = stats(items, now)
    assert s["dictations"] == 3 and s["words"] == 7 and s["today"] == 5, s
    assert s["wpm"] == 120, s  # 6 words in 3 s
    assert stats([]) == {"dictations": 0, "words": 0, "today": 0, "wpm": 0, "minutes_saved": 0}
    print("ok")
