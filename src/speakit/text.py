"""Transcript cleanup before typing."""
from __future__ import annotations

import re
from pathlib import Path

# Parakeet transcribes hesitations verbatim ("message uh aligns"). Drop them,
# eating an adjacent comma so "I think, uh, we" -> "I think we".
_FILLER = re.compile(r",?\s*\b(?:uh+|um+|uhm|erm|hmm+|mm+)\b,?", re.IGNORECASE)


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


if __name__ == "__main__":
    assert clean("Make sure that our message uh aligns with docs.") == "Make sure that our message aligns with docs."
    assert clean("I think, uh, we should") == "I think we should"
    assert clean("Um, so we go.") == "So we go."
    assert clean("It was, um.") == "It was."
    assert clean("Uh.") == ""
    assert clean("Mm.") == ""
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
