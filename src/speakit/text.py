"""Transcript cleanup before typing."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# Typographic punctuation NFKD can't fold (LLM output); map before folding.
_PUNCT = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                        "\u2013": "-", "\u2014": " - ", "\u2026": "..."})
# Parakeet transcribes hesitations verbatim ("message uh aligns"). Drop them,
# eating an adjacent comma so "I think, uh, we" -> "I think we".
_FILLER = re.compile(r",?\s*\b(?:uh+|um+|uhm|erm|hmm+|mm+)\b,?", re.IGNORECASE)


def ascii_fold(text: str) -> str:
    """For ydotool, which types US-layout ASCII only and silently drops anything
    else: fold accents ("café" -> "cafe") rather than lose the letters."""
    return unicodedata.normalize("NFKD", text.translate(_PUNCT)).encode("ascii", "ignore").decode()


def clean(text: str) -> str:
    out = _FILLER.sub("", text).strip()
    if not any(c.isalnum() for c in out):
        return ""
    if out != text.strip() and text.lstrip()[:1].isupper():
        out = out[0].upper() + out[1:]
    return out


def load_replacements(path: Path) -> list[tuple[re.Pattern[str], str]]:
    """Parse `wrong => right` lines (# comments). Missing file = no rules."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    rules = []
    for line in lines:
        wrong, sep, right = line.split("#", 1)[0].partition("=>")
        if sep and wrong.strip():
            # Whole-word, case-insensitive. Lookarounds instead of \b so
            # phrases starting/ending in punctuation still match.
            rules.append((re.compile(rf"(?<!\w){re.escape(wrong.strip())}(?!\w)", re.IGNORECASE), right.strip()))
    return rules


def replace(text: str, rules: list[tuple[re.Pattern[str], str]]) -> str:
    for pat, right in rules:
        text = pat.sub(lambda _m: right, text)
    return text


# "daemon dot py", "read me dot md", "Daemon.py": up to 4 words, then the
# extension. Not right after a path char, so existing paths stay as they are.
_SPOKEN_FILE = re.compile(r"(?<![\w/.-])((?:[\w-]+ ){0,3}[\w-]+)(?: dot |\.)(\w+)\b", re.IGNORECASE)


def _norm(name: str) -> str:
    return re.sub(r"[\s_-]", "", name.replace(" dot ", ".")).lower()


def file_paths(text: str, files: list[str]) -> str:
    """Spoken file names -> paths from `files` (the focused terminal's repo).
    A name shared by several files becomes just the file name."""
    index: dict[str, str] = {}
    for f in files:
        base = f.rsplit("/", 1)[-1]
        key = _norm(base)
        index[key] = f if key not in index else base

    def sub(m: re.Match[str]) -> str:
        words = m[1].split()
        for i in range(len(words)):  # longest name first: "the read me" -> "read me"
            path = index.get(_norm(" ".join(words[i:])) + "." + m[2].lower())
            if path:
                return " ".join(words[:i] + [path])
        return m[0]

    return _SPOKEN_FILE.sub(sub, text) if index else text


if __name__ == "__main__":
    files = ["README.md", "src/speakit/daemon.py", "ui/vite.config.ts", "app/src/main.rs",
             "client/src/main.rs", "install.sh", "src/speakit/__init__.py"]
    assert file_paths("Look at daemon dot py and install dot sh.", files) == "Look at src/speakit/daemon.py and install.sh."
    assert file_paths("Update the read me dot md", files) == "Update the README.md"
    assert file_paths("Check vite dot config dot ts", files) == "Check ui/vite.config.ts"
    assert file_paths("Fix main dot rs and Daemon.py", files) == "Fix main.rs and src/speakit/daemon.py"
    assert file_paths("Edit init dot py", files) == "Edit src/speakit/__init__.py"  # underscores aren't spoken
    assert file_paths("Edit foo dot py", files) == "Edit foo dot py"  # unknown: left alone
    assert file_paths("In src/speakit/daemon.py, e.g. here. Then go.", files) == "In src/speakit/daemon.py, e.g. here. Then go."
    assert file_paths("daemon dot py", []) == "daemon dot py"

    assert clean("Make sure that our message uh aligns with docs.") == "Make sure that our message aligns with docs."
    assert clean("I think, uh, we should") == "I think we should"
    assert clean("Um, so we go.") == "So we go."
    assert clean("It was, um.") == "It was."
    assert clean("Uh.") == ""
    assert clean("Mm.") == ""
    assert ascii_fold("It\u2019s \u201cdone\u201d\u2014mostly\u2026") == 'It\'s "done" - mostly...'
    assert ascii_fold("A café in São Paulo, naïve.") == "A cafe in Sao Paulo, naive."
    assert clean("A café in São Paulo.") == "A café in São Paulo."
    assert clean("  Bring an umbrella, Uhura. ") == "Bring an umbrella, Uhura."
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("# comment\nfake zo => fake Zoho\nZo => Zoho\nS D F S => SDFs  # trailing comment\nbad line\n")
    rules = load_replacements(Path(f.name))
    assert len(rules) == 3
    assert replace("Go from fake Zo to Real Zo, check S D F S.", rules) == "Go from fake Zoho to Real Zoho, check SDFs."
    assert replace("Zone and zoo stay.", rules) == "Zone and zoo stay."
    assert load_replacements(Path("/nonexistent")) == []
    print("ok")
