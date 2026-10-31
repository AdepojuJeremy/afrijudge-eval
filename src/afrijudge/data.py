"""Pinned source downloads, schema checks, and parallel sampling. No synthetic fallback."""

import ast
import csv
import hashlib
import io
import json
import random
import tarfile
from pathlib import Path

import httpx

from afrijudge.io import digest, read_jsonl, write_json, write_jsonl
from afrijudge.text import answer, nfc

CODES = {"en": "eng", "ha": "hau", "yo": "yor", "ig": "ibo", "sw": "swa"}
FLORES = {"en": "eng_Latn", "ha": "hau_Latn", "yo": "yor_Latn", "ig": "ibo_Latn", "sw": "swh_Latn"}


def download(source: dict, filename: str, root: Path) -> str:
    url = (
        f"https://huggingface.co/datasets/{source['repo']}/resolve/{source['revision']}/{filename}"
    )
    cache = root / "raw" / digest(url)
    if not cache.exists():
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            response = client.get(url)
            response.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(response.content)
    return cache.read_text(encoding="utf-8")


def parse_verifiable(raw: str, task: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(raw), delimiter="\t"))
    result = []
    for index, row in enumerate(rows):
        question = nfc(row["question"].strip())
        if not question:
            raise ValueError("Empty source question")
        if task == "mmlu":
            choices = ast.literal_eval(row["choices"])
            if not isinstance(choices, list) or len(choices) != 4:
                raise ValueError("Expected four MMLU choices")
            question += "\n" + "\n".join(
                f"{k}) {nfc(str(v))}" for k, v in zip("ABCD", choices, strict=True)
            )
            gold = row["answer"].strip()
        else:
            gold = str(row.get("answer_number") or row.get("answer", "")).strip()
        gold = answer(f"<answer>{gold}</answer>", task)
        if gold is None:
            raise ValueError(f"Invalid source gold at {task}:{index}")
        result.append(
            {"item_id": f"{task}:{index}", "task": task, "prompt": question, "gold": gold}
        )
    return result


def parse_flores(raw: str) -> dict[str, str]:
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    out = {}
    for row in rows:
        key = str(row["id"])
        if key in out or not row["text"].strip():
            raise ValueError("Duplicate FLORES IDs or empty text")
        out[key] = nfc(row["text"].strip())
    return out


def flores_archive(source: dict, root: Path) -> tarfile.TarFile:
    """Verify bytes before reading named members; never extract archive paths."""
    cache = root / "raw" / source["sha256"]
    if not cache.exists():
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            response = client.get(source["url"])
            response.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(response.content)
    if hashlib.sha256(cache.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("FLORES archive checksum mismatch; no automatic fallback")
    return tarfile.open(cache, "r:gz")


def prepare(config: dict, root: Path) -> dict:
    """Use identical sampled row IDs across languages and verify answer-key alignment.

    IrokoBench TSVs are distributed in parallel row order, without stable source IDs.
    Record row IDs and validate lengths/keys; this is not a semantic translation audit.
    FLORES human translations are not native-original prose; retain that provenance.
    """
    fingerprint = digest({k: config[k] for k in ("datasets", "languages", "samples", "seed")})
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["fingerprint"] != fingerprint:
            raise ValueError("Prepared data configuration changed; choose a new --data directory")
        for name, expected in manifest["hashes"].items():
            if digest(read_jsonl(root / name)) != expected:
                raise ValueError(f"Prepared data changed: {name}")
        return manifest
    exp1, exp2 = [], []
    sources = []
    for task in ("mmlu", "mgsm"):
        count = config["samples"][task]
        tables = {}
        source = config["datasets"][task]
        for lang in config["languages"]:
            filename = f"data/{CODES[lang]}/test.tsv"
            raw = download(source, filename, root)
            tables[lang] = parse_verifiable(raw, task)
            sources.append({**source, "file": filename, "content_hash": digest(raw)})
        english = tables["en"]
        if any(len(rows) != len(english) for rows in tables.values()):
            raise ValueError(f"Nonparallel row counts in {task}")
        eligible, seen = [], {lang: set() for lang in tables}
        for idx in range(len(english)):
            if any(rows[idx]["prompt"] in seen[lang] for lang, rows in tables.items()):
                continue
            for lang, rows in tables.items():
                seen[lang].add(rows[idx]["prompt"])
            eligible.append(idx)
        if count > len(eligible):
            raise ValueError(f"Requested more {task} items than available")
        indices = sorted(random.Random(f"{config['seed']}:{task}").sample(eligible, count))
        for idx in indices:
            if any(rows[idx]["gold"] != english[idx]["gold"] for rows in tables.values()):
                raise ValueError(f"Parallel answer keys differ: {task}:{idx}")
            for lang, rows in tables.items():
                exp1.append({**rows[idx], "lang": lang, "source": source})
    source = config["datasets"]["translation"]
    tables = {}
    with flores_archive(source, root) as archive:
        for lang in config["languages"]:
            filename = f"./flores200_dataset/devtest/{FLORES[lang]}.devtest"
            member = archive.extractfile(filename)
            if member is None:
                raise ValueError(f"Missing archive member: {filename}")
            raw = member.read().decode("utf-8")
            rows = raw.splitlines()
            if not rows or any(not row.strip() for row in rows):
                raise ValueError("Empty translation reference")
            tables[lang] = {str(i): nfc(row.strip()) for i, row in enumerate(rows)}
            sources.append({**source, "file": filename, "content_hash": digest(raw)})
    if len({len(t) for t in tables.values()}) != 1:
        raise ValueError("FLORES parallel row counts differ")
    common = sorted(set.intersection(*(set(table) for table in tables.values())))
    count = config["samples"]["traps_per_language"]
    if count > len(common):
        raise ValueError("Insufficient aligned translation references")
    ids = random.Random(config["seed"]).sample(common, count)
    for lang in config["languages"]:
        if lang == "en":
            continue
        for idx in ids:
            exp2.append(
                {
                    "item_id": f"flores:{idx}",
                    "lang": lang,
                    "en_source": tables["en"][idx],
                    "reference": tables[lang][idx],
                    "reference_provenance": "human_translation_not_native_original",
                    "source": source,
                }
            )
    paths = {"exp1.jsonl": exp1, "exp2.jsonl": exp2}
    for name, rows in paths.items():
        write_jsonl(root / name, rows)
    manifest = {
        "fingerprint": fingerprint,
        "sources": sources,
        "counts": {k: len(v) for k, v in paths.items()},
        "hashes": {k: digest(v) for k, v in paths.items()},
    }
    write_json(manifest_path, manifest)
    return manifest
