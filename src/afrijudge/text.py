"""Conservative answer parsing; Unicode transformations are explicit interventions."""

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def strip_marks(text: str) -> str:
    return nfc(
        "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    )


def json_object(text: str) -> dict | None:
    """Accept one JSON object, optionally wrapped in a single Markdown fence."""
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    elif text.startswith("```\n") and text.endswith("```"):
        text = text[4:-3].strip()
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def answer(text: str, task: str) -> str | None:
    tags = re.findall(r"<answer>\s*([^<>]+?)\s*</answer>", text)
    if len(tags) != 1:
        return None
    value = tags[0].strip()
    if task == "mmlu":
        return value if value in "ABCD" and len(value) == 1 else None
    # Do not guess the final number from arbitrary reasoning or silently delete separators.
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", value):
        return None
    try:
        return str(Decimal(value.replace(",", "")).normalize())
    except InvalidOperation:
        return None


def verdict(text: str) -> str:
    obj = json_object(text)
    if obj and obj.get("verdict") in ("A", "B", "TIE"):
        return obj["verdict"]
    return "INVALID"


def reconcile(ab: str, ba: str) -> str:
    """Keep order instability separate from an explicit quality tie."""
    if "INVALID" in (ab, ba):
        return "INVALID"
    mapped = {"A": "B", "B": "A", "TIE": "TIE"}[ba]
    return ab if ab == mapped else "ORDER_UNSTABLE"


def features(text: str) -> dict:
    return {"characters": len(text), "utf8_bytes": len(text.encode()), "words": len(text.split())}
