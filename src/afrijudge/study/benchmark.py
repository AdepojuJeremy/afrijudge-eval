"""Deterministic four-way benchmark selection from pinned releases."""

import ast
import csv
import gzip
import hashlib
import io
import json
import random
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote

import httpx

from afrijudge.data import (
    CODES,
    FLORES,
    eligible_parallel_indices,
    flores_archive,
    parse_verifiable,
)
from afrijudge.io import digest, write_json
from afrijudge.study.num2words_afri import number_text, quantities, spoken_question
from afrijudge.text import nfc

LANGUAGES = ("en", "ha", "yo", "ig")
DOMAINS = ("belebele", "mmlu", "mgsm", "flores")
AUTHORS = ("gpt4o", "gemini25pro", "claude_sonnet")
MATCHUPS = (("gemini25pro", "gpt4o"), ("llama33_70b", "gpt4o"), ("llama33_70b", "qwen25_72b"))
TIERS = {
    75: ((4, 15), (4, 15), (4, 15), (3, 15)),
    300: ((15, 60),) * 4,
}
PINNED = {
    "belebele": ("facebook/belebele", "9bb2fee95406d0d23ceb869240c94b2acc9e5b83"),
    "mmlu": ("masakhane/afrimmlu", "96f247619673906ae4c321a3232afc67b98ea57e"),
    "mgsm": ("masakhane/afrimgsm", "8e4268d2b94941f18f63f694cf48e4ae26fbec65"),
    "xnli": ("masakhane/afrixnli", "e3ca06b30f3e7af2a86f6c8609ea76fee326bc56"),
    "sib200": ("Davlan/sib200", "38977a667f6fc264d5c26ec57a01e16db040b358"),
    "afriqa": ("masakhane/afriqa", "8c9e7495b0e14b41d908e08cb1509a985453523f"),
}
FLORES_SOURCE = {
    "url": "https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz",
    "sha256": "b8b0b76783024b85797e5cc75064eb83fc5288b41e9654dabc7be6ae944011f6",
}
GSM_ORIGINAL = (
    "https://raw.githubusercontent.com/openai/grade-school-math/"
    "3101c7d5072418e28b9008a6636bde82a006892c/grade_school_math/data/test.jsonl"
)

AFRIQA_GOLD = (
    "https://raw.githubusercontent.com/masakhane-io/afriqa/"
    "5c29933753692c28773c34ac1f68482007f1d2bb/data/gold_passages"
)

CLAIM = {
    "en": "Which claim is supported by the passage? Explain your choice using details from it.",
    "ha": "Wace magana ce nassin ya goyi baya? Yi bayanin zaɓinka da hujjoji daga nassin.",
    "yo": "Èwo nínú àwọn gbólóhùn yìí ni àyọkà náà fi múlẹ̀? Ṣàlàyé yíyàn rẹ pẹ̀lú ẹ̀rí.",
    "ig": "Kedu n'ime okwu ndị a ka ederede ahụ kwadoro? Jiri ihe dị n'ederede kọwaa nhọrọ gị.",
}


def _fetch_bytes(url: str, cache: Path) -> bytes:
    path = cache / "raw" / digest(url)
    if not path.exists():
        with httpx.Client(timeout=90, follow_redirects=True) as http:
            response = http.get(url)
            response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(response.content)
        tmp.replace(path)
    return path.read_bytes()


def _fetch(url: str, cache: Path) -> str:
    return _fetch_bytes(url, cache).decode("utf-8-sig")


def _verified_bytes(url: str, cache: Path, origin: list) -> bytes:
    raw = _fetch_bytes(url, cache)
    origin.append({"url": url, "sha256": hashlib.sha256(raw).hexdigest()})
    return raw


def _hf_url(domain: str, file: str) -> str:
    repo, revision = PINNED[domain]
    return f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{file}"


def _hf(domain: str, file: str, cache: Path, origin: list) -> str:
    return _verified_bytes(_hf_url(domain, file), cache, origin).decode("utf-8-sig")


def _choices(question: str, choices: list[str]) -> str:
    return (
        question
        + "\n"
        + "\n".join(f"{label}) {text}" for label, text in zip("ABCD", choices, strict=True))
    )


def _mc_candidates(questions, options, gold_idx, foil_idx) -> dict:
    return {
        lang: {
            "prompt": _choices(questions[lang], options[lang]),
            "gold": "ABCD"[gold_idx],
            "foil": "ABCD"[foil_idx],
            "gold_text": options[lang][gold_idx],
            "foil_text": options[lang][foil_idx],
        }
        for lang in LANGUAGES
    }


def belebele(cache: Path, origin: list) -> list[dict]:
    tables = {}
    for lang in LANGUAGES:
        raw = _hf("belebele", f"data/{FLORES[lang]}.jsonl", cache, origin)
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        tables[lang] = {(row["link"], row["question_number"]): row for row in rows}
        if len(tables[lang]) != 900 or len(rows) != 900:
            raise ValueError(f"Expected 900 unique Belebele keys for {lang}")
    if any(table.keys() != tables["en"].keys() for table in tables.values()):
        raise ValueError("Belebele source key mismatch")
    result = []
    for link, idx in sorted(tables["en"]):
        rows = {lang: table[link, idx] for lang, table in tables.items()}
        gold = {int(row["correct_answer_num"]) - 1 for row in rows.values()}
        if len(gold) != 1:
            continue
        gold_idx = gold.pop()
        foil_idx = (gold_idx + 1 + int(digest([link, idx]), 16) % 3) % 4
        options = {
            lang: [nfc(row[f"mc_answer{i}"].strip()) for i in range(1, 5)]
            for lang, row in rows.items()
        }
        if any(len(set(values)) != 4 or not all(values) for values in options.values()):
            continue
        questions = {
            lang: nfc(row["flores_passage"].strip() + "\n\n" + row["question"].strip())
            for lang, row in rows.items()
        }
        result.append(
            {
                "source_id": f"belebele:{digest(link)[:12]}:{idx}",
                "article": link,
                "variants": _mc_candidates(questions, options, gold_idx, foil_idx),
            }
        )
    return result


def _tsvs(domain: str, cache: Path, origin: list) -> tuple[dict, dict]:
    sources, parsed = {}, {}
    for lang in LANGUAGES:
        raw = _hf(domain, f"data/{CODES[lang]}/test.tsv", cache, origin)
        sources[lang] = list(csv.DictReader(io.StringIO(raw), delimiter="\t"))
        parsed[lang] = parse_verifiable(raw, domain)
    expected = 500 if domain == "mmlu" else 250
    if any(len(rows) != expected for rows in sources.values()):
        raise ValueError(f"Unaligned pinned {domain} splits")
    return sources, parsed


def _pilot_exclusions(parsed: dict, domain: str, exclusions: set[str]) -> set[str]:
    """Reproduce the sample IDs from every committed pilot profile."""
    sampled = set(exclusions)
    for count, quarantine in ((30, []), (20, []), (20, sorted(exclusions))):
        eligible = eligible_parallel_indices(parsed, domain, quarantine)
        selected = random.Random(f"42:{domain}").sample(eligible, count)
        sampled.update(parsed["en"][idx]["item_id"] for idx in selected)
    return sampled


def _eligible_tsv(parsed, domain, exclusions) -> list[int]:
    return [
        idx
        for idx in eligible_parallel_indices(parsed, domain, sorted(exclusions))
        if len({parsed[lang][idx]["gold"] for lang in LANGUAGES}) == 1
    ]


def mmlu(cache: Path, origin: list, exclusions: set) -> list[dict]:
    tables, parsed = _tsvs("mmlu", cache, origin)
    exclusions.update(_pilot_exclusions(parsed, "mmlu", exclusions))
    result = []
    for idx in _eligible_tsv(parsed, "mmlu", exclusions):
        rows = {lang: table[idx] for lang, table in tables.items()}
        if len({row["subject"] for row in rows.values()}) != 1:
            continue
        options = {
            lang: [nfc(text.strip()) for text in ast.literal_eval(row["choices"])]
            for lang, row in rows.items()
        }
        if any(
            len(set(values)) != 4 or any(len(value.split()) not in range(1, 21) for value in values)
            for values in options.values()
        ):
            continue
        if re.search(r"\b(except|not|least)\b", rows["en"]["question"], re.I):
            continue
        gold_idx = "ABCD".index(rows["en"]["answer"])
        foil_idx = (gold_idx + 1 + int(digest(["mmlu", idx]), 16) % 3) % 4
        result.append(
            {
                "source_id": f"mmlu:{idx}",
                "subject": rows["en"]["subject"],
                "variants": _mc_candidates(
                    {lang: nfc(row["question"].strip()) for lang, row in rows.items()},
                    options,
                    gold_idx,
                    foil_idx,
                ),
            }
        )
    return result


def _gsm_key(text: str) -> str:
    return "".join(c for c in nfc(text).casefold() if c.isalnum())


def _gsm_solutions(cache: Path, origin: list) -> dict:
    raw = _fetch(GSM_ORIGINAL, cache)
    origin.append({"url": GSM_ORIGINAL, "sha256": hashlib.sha256(raw.encode()).hexdigest()})
    solutions = {}
    for line in raw.splitlines():
        row = json.loads(line)
        solution, _, answer = row["answer"].rpartition("####")
        steps = re.findall(r"<<([^<>]+)>>", solution)
        if steps and re.fullmatch(r"\s*[\d,]+\s*", answer):
            if all(re.fullmatch(r"[\d, ()+*/-]+=[\d,]+", step) for step in steps):
                values = set.union(*(quantities(step) for step in steps))
                solutions[_gsm_key(row["question"])] = (int(answer.replace(",", "")), values)
    return solutions


def mgsm(cache: Path, origin: list, exclusions: set) -> list[dict]:
    tables, parsed = _tsvs("mgsm", cache, origin)
    original = _gsm_solutions(cache, origin)
    exclusions.update(_pilot_exclusions(parsed, "mgsm", exclusions))
    result = []
    for idx in _eligible_tsv(parsed, "mgsm", exclusions):
        rows = {lang: table[idx] for lang, table in tables.items()}
        solution = original.get(_gsm_key(rows["en"]["question"]))
        if not solution:
            continue
        gold, intermediate = solution
        if gold != Decimal(parsed["en"][idx]["gold"]) or not 1 <= gold <= 1000:
            continue
        all_quantities = set.union(*(quantities(row["question"]) for row in rows.values()))
        if any(not 1 <= n <= 1000 for n in intermediate | all_quantities):
            continue
        # Some translations spell quantities already. Flag only numeric values absent
        # from both the English text and its published computation.
        if all_quantities - quantities(rows["en"]["question"]) - intermediate:
            continue
        try:
            prompts = {
                lang: spoken_question(nfc(row["question"].strip()), lang)
                for lang, row in rows.items()
            }
        except ValueError:
            continue
        foil = gold + 1 if gold < 1000 else gold - 1
        result.append(
            {
                "source_id": f"mgsm:{idx}",
                "reference_quantities": sorted(intermediate),
                "variants": {
                    lang: {
                        "prompt": prompt,
                        "gold": str(gold),
                        "foil": str(foil),
                        "gold_text": number_text(gold, lang),
                        "foil_text": number_text(foil, lang),
                    }
                    for lang, prompt in prompts.items()
                },
            }
        )
    return result


def _read_member(archive, name: str) -> str:
    member = archive.extractfile("./flores200_dataset/" + name)
    if member is None:
        raise ValueError(f"Missing FLORES-200 member {name}")
    with member:
        return member.read().decode("utf-8")


def _table(raw: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw), delimiter="\t"))


def xnli(cache: Path, origin: list) -> list:
    tables = {
        lang: _table(_hf("xnli", f"data/{CODES[lang]}/test.tsv", cache, origin))
        for lang in LANGUAGES
    }
    if any(len(rows) != len(tables["en"]) for rows in tables.values()):
        raise ValueError("AfriXNLI test lengths differ")
    result = []
    for idx, en in enumerate(tables["en"]):
        variants = {lang: table[idx] for lang, table in tables.items()}
        if any(v["label"] != en["label"] for v in variants.values()):
            raise ValueError(f"AfriXNLI label mismatch at row {idx}")
        if all(v["premise"].strip() and v["hypothesis"].strip() for v in variants.values()):
            result.append({"source_id": f"xnli:{idx}", "variants": variants})
    return result


def sib200(cache: Path, origin: list) -> list:
    tables = {}
    for lang in LANGUAGES:
        rows = [
            row
            for split in ("dev", "test", "train")
            for row in _table(_hf("sib200", f"data/{FLORES[lang]}/{split}.tsv", cache, origin))
        ]
        tables[lang] = {int(row["index_id"]): row for row in rows}
        if len(tables[lang]) != len(rows):
            raise ValueError("Repeated SIB-200 sentence ID")
    ids = set.intersection(*(set(table) for table in tables.values()))
    result = []
    for idx in sorted(ids):
        variants = {lang: table[idx] for lang, table in tables.items()}
        if len({r["category"] for r in variants.values()}) != 1:
            raise ValueError(f"SIB-200 category mismatch at sentence {idx}")
        result.append({"source_id": f"sib200:{idx}", "variants": variants})
    return result


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+(?=[\w“])", text)


def _passage(record: dict) -> str | None:
    text = nfc(" ".join(record["context"].split()))
    answers = record["answer_pivot"]["text"]
    if not answers or not answers[0]:
        return None
    answer = nfc(answers[0]).casefold()
    sentences = _sentences(text)
    bound = re.compile(r"(?<!\w)" + re.escape(answer) + r"(?!\w)")
    for idx, sent in enumerate(sentences):
        if not bound.search(sent.casefold()):
            continue
        start = max(0, min(idx - 1, len(sentences) - 3))
        passage = " ".join(sentences[start : start + 3])
        if len(sentences) >= 3 and 35 <= len(passage.split()) <= 220:
            return passage
    return None


def afriqa(cache: Path, origin: list) -> list[dict]:
    import pyarrow.parquet as pq

    result = []
    for lang in LANGUAGES[1:]:
        code = CODES[lang]
        qa_url = _hf_url("afriqa", f"{code}/test/0000.parquet")
        gold_url = f"{AFRIQA_GOLD}/{code}/gold_span_passages.afriqa.{code}.en.test.json"
        raw = _verified_bytes(qa_url, cache, origin)
        tables = pq.read_table(io.BytesIO(raw)).to_pylist()
        keys = {
            (nfc(r["question"]).strip(), nfc(r["translated_question"]).strip()): r
            for r in tables
            if r["translation_type"] == "human_translation"
            and r["lang"] == code
            and r["split"] == "test"
        }
        for line in _verified_bytes(gold_url, cache, origin).decode("utf-8-sig").splitlines():
            row = json.loads(line)
            question = nfc(row["question_lang"]).strip()
            english = nfc(row["question_translated"]).strip()
            released = keys.get((question, english))
            if not released or not row["context"] or not 4 <= len(question.split()) <= 35:
                continue
            title = nfc(row["title"] or "").strip()
            # Rely on an explicit article entity in the English pivot for this analysis.
            # This also drops groundings where a passage covers a different named person.
            if not title or _gsm_key(title) not in _gsm_key(english):
                continue
            answer = nfc(row["answer_lang"] or "").strip()
            try:
                translations = {nfc(v).casefold() for v in ast.literal_eval(released["answers"])}
                english_answers = ast.literal_eval(released["translated_answer"])
            except (SyntaxError, ValueError):
                continue
            if not answer or answer.casefold() not in translations:
                continue
            passage = _passage(row)
            if not passage:
                continue
            result.append(
                {
                    "topic_id": f"afriqa:{lang}:{row['id']}",
                    "original_lang": lang,
                    "question": question,
                    "english_question": english,
                    "passage": passage,
                    "answer": answer,
                    "title": title,
                    "english_answers": english_answers,
                    "question_source": qa_url,
                    "passage_source": gold_url,
                }
            )
    return result


def _assign_h2(rows: list, topics: list, seed: int, exclusions: set[str]) -> None:
    by_lang = {}
    for lang in LANGUAGES[1:]:
        by_lang[lang] = sorted(
            (t for t in topics if t["original_lang"] == lang and t["topic_id"] not in exclusions),
            key=lambda t: digest([seed, t["topic_id"]]),
        )
    used_titles, seen_questions = set(), set()
    test = [row for row in rows if row["domain"] == "flores" and row["split"] == "test"]
    for idx, row in enumerate(test):
        origin = LANGUAGES[1 + (idx // 3 + idx % 3) % 3]
        while by_lang[origin]:
            topic = by_lang[origin].pop(0)
            title, question = _gsm_key(topic["title"]), _gsm_key(topic["english_question"])
            if title not in used_titles and question not in seen_questions:
                used_titles.add(title)
                seen_questions.add(question)
                row["h2"] = topic
                break
        else:
            raise ValueError(f"Too few distinct AfriQA questions and passages for {origin}")


def flores(cache: Path, origin: list) -> list[dict]:
    lookup = {_gsm_key(r["variants"]["en"]["text"]): r for r in sib200(cache, origin)}
    origin.append(FLORES_SOURCE)
    with flores_archive(FLORES_SOURCE, cache) as arc:
        metadata = list(
            csv.DictReader(io.StringIO(_read_member(arc, "metadata_devtest.tsv")), delimiter="\t")
        )
        texts = {
            lang: _read_member(arc, f"devtest/{FLORES[lang]}.devtest").splitlines()
            for lang in LANGUAGES
        }
    if any(
        len(rows) != len(metadata) or not all(text.strip() for text in rows)
        for rows in texts.values()
    ):
        raise ValueError("FLORES-200 metadata and translations do not align")
    documents = defaultdict(list)
    for idx, row in enumerate(metadata):
        documents[row["URL"]].append(idx)

    def topics(ids):
        found = []
        for idx in ids:
            match = lookup.get(_gsm_key(texts["en"][idx]))
            if match and all(
                _gsm_key(texts[lang][idx]) == _gsm_key(match["variants"][lang]["text"])
                for lang in LANGUAGES
            ):
                found.append(match)
        return found

    eligible = [
        (url, ids, topics(ids))
        for url, ids in sorted(documents.items())
        if len(ids) >= 3 and topics(ids)
    ]
    # Retain pilot document exclusions at the document level, even if the pilot sentence
    # would not have been used as the lead. Reserve separate source articles for foils.
    prior_rows = random.Random(42).sample(sorted(str(i) for i in range(len(metadata))), 30)
    prior_articles = {metadata[int(idx)]["URL"] for idx in prior_rows}
    foil_pool = [group for group in eligible if int(digest(group[0]), 16) % 5 == 0]
    foil_articles = {article for article, _, _ in foil_pool}
    # Foils are first sentences of another FLORES document from the same source
    # domain. The passage retains only the remaining sentences from its own article.
    result = []
    for url, ids, labels in eligible:
        if url in prior_articles or url in foil_articles:
            continue
        first = ids[0]
        distractors = [
            other_ids[0]
            for other_url, other_ids, _ in foil_pool
            if other_url != url
            and metadata[other_ids[0]]["domain"] == metadata[first]["domain"]
            and metadata[other_ids[0]]["topic"] != metadata[first]["topic"]
        ]
        if not distractors:
            continue
        foil = min(distractors, key=lambda idx: digest([first, idx]))
        correct_first = int(digest(url), 16) % 2 == 0
        variants = {}
        for lang, rows in texts.items():
            evidence = nfc(" ".join(rows[idx] for idx in ids[1:]))
            gold_text, foil_text = nfc(rows[first]), nfc(rows[foil])
            options = [gold_text, foil_text] if correct_first else [foil_text, gold_text]
            variants[lang] = {
                "prompt": f"{evidence}\n\n{CLAIM[lang]}\nA) {options[0]}\nB) {options[1]}",
                "gold": "A" if correct_first else "B",
                "foil": "B" if correct_first else "A",
                "gold_text": gold_text,
                "foil_text": foil_text,
            }
        result.append(
            {
                "source_id": f"flores:{first}",
                "article": url,
                "sentence_rows": ids,
                "foil_article": metadata[foil]["URL"],
                "foil_sentence_row": foil,
                "reference_provenance": "published_FLORES200_translations",
                "sib200_sentences": [
                    {
                        "source_id": topic["source_id"],
                        "category": topic["variants"]["en"]["category"],
                    }
                    for topic in labels
                ],
                "variants": variants,
            }
        )
    return result


def _article_key(url: str) -> str:
    return unquote(url).rstrip("/").casefold()


def _select(rows, domain, seed, counts, exclusions, used_articles) -> list:
    anchor_n, test_n = counts
    ranked = sorted(rows, key=lambda row: digest([seed, domain, row["source_id"]]))
    seen, chosen = set(used_articles), []
    for row in ranked:
        key = _article_key(row.get("article", row["source_id"]))
        if row["source_id"] in exclusions or key in seen:
            continue
        seen.add(key)
        if "article" in row:
            used_articles.add(key)
        chosen.append(row)
        if len(chosen) == anchor_n + test_n:
            break
    if len(chosen) != anchor_n + test_n:
        raise ValueError(f"{domain}: selected {len(chosen)}, need {anchor_n + test_n}")
    for idx, row in enumerate(chosen):
        anchor = idx < anchor_n
        local_idx = idx if anchor else idx - anchor_n
        row.update(
            domain=domain,
            split="anchor" if anchor else "test",
            author_model=AUTHORS[local_idx % len(AUTHORS)],
        )
        if domain == "flores" and not anchor:
            row["h2_matchup"] = list(MATCHUPS[local_idx % len(MATCHUPS)])
    return chosen


def read_exclusions(path: Path) -> set[str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    ids = value.get("excluded_source_ids") if isinstance(value, dict) else value
    if not isinstance(ids, list) or any(
        not isinstance(key, str) or key.split(":")[0] not in (*DOMAINS, "xnli", "sib200", "afriqa")
        for key in ids
    ):
        raise ValueError("Expected source IDs, as a list or as excluded_source_ids")
    return set(ids)


def build(cache: Path, total: int, seed: int, exclusions: set[str]) -> dict:
    origin = []
    exclusions = set(exclusions)
    pools = {
        "belebele": belebele(cache, origin),
        "mmlu": mmlu(cache, origin, exclusions),
        "mgsm": mgsm(cache, origin, exclusions),
        "flores": flores(cache, origin),
    }
    topics = afriqa(cache, origin)
    used_articles = set()
    rows = []
    for domain, counts in zip(DOMAINS, TIERS[total], strict=True):
        rows.extend(_select(pools[domain], domain, seed, counts, exclusions, used_articles))
    _assign_h2(rows, topics, seed, exclusions)
    body = {
        "schema": 1,
        "seed": seed,
        "total_sources": total,
        "languages": list(LANGUAGES),
        "upstream": origin,
        "excluded_source_ids": sorted(exclusions),
        "eligible_counts": {domain: len(rows) for domain, rows in pools.items()},
        "afriqa_eligible": len(topics),
        "sources": rows,
    }
    return {**body, "sha256": digest(body)}


def open_benchmark(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            data = json.load(stream)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    body = {key: value for key, value in data.items() if key != "sha256"}
    if data["sha256"] != digest(body) or data["schema"] != 1:
        raise ValueError("Benchmark has an unsupported version or has been edited")
    rows, total = data["sources"], data["total_sources"]
    if len(rows) != total or len({row["source_id"] for row in rows}) != total:
        raise ValueError("Benchmark requires unique matched source IDs")
    if data["languages"] != list(LANGUAGES) or any(
        set(row["variants"]) != set(LANGUAGES) for row in rows
    ):
        raise ValueError("Incomplete language coverage")
    used_ids = {row["source_id"] for row in rows}
    if used_ids.intersection(data["excluded_source_ids"]):
        raise ValueError("An excluded source ID is present")
    for domain, (n_anchor, n_test) in zip(DOMAINS, TIERS[total], strict=True):
        for split, expected in (("anchor", n_anchor), ("test", n_test)):
            selected = [row for row in rows if (row["domain"], row["split"]) == (domain, split)]
            if len(selected) != expected:
                raise ValueError(f"Wrong {domain} {split} count")
            if total == 300 and {
                sum(row["author_model"] == author for row in selected) for author in AUTHORS
            } != {expected // len(AUTHORS)}:
                raise ValueError(f"Unbalanced author assignment in {domain} {split}")
        if domain == "flores":
            selected = [r for r in rows if r["domain"] == domain and r["split"] == "test"]
            if {
                sum(tuple(row["h2_matchup"]) == matchup for row in selected) for matchup in MATCHUPS
            } != {n_test // len(MATCHUPS)}:
                raise ValueError("Unbalanced H2 matchup assignment")
            if len({row["h2"]["topic_id"] for row in selected}) != n_test:
                raise ValueError("Repeated AfriQA topic")
            if {
                sum(row["h2"]["original_lang"] == lang for row in selected)
                for lang in LANGUAGES[1:]
            } != {n_test // 3}:
                raise ValueError("Unbalanced AfriQA provenance languages")
    return data


def write_benchmark(path: Path, data: dict) -> None:
    if path.suffix == ".gz":
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".gz.tmp")
        content = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        tmp.write_bytes(gzip.compress(content, compresslevel=9, mtime=0))
        tmp.replace(path)
    else:
        write_json(path, data)
    open_benchmark(path)
