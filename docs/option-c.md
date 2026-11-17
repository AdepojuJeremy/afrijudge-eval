# Option C multilingual judge study

Option C uses four-way aligned English, Hausa, Yorùbá and Igbo materials. Each H1
domain contributes 15 anchor and 60 held-out source groups. A source group stays
together across languages and H1 conditions. The default mixed Domain 2 uses **45 AfriMMLU** and
**30 AfriXNLI** sources at full scale (9 and 6 anchors, 36 and 24 test sources).
AfriXNLI contributes at most one hypothesis per premise. The 60 explanatory test slots each
carry one separate AfriQA topic for H2, assigned across the three matchups and the
three original-question languages. The original 75-AfriMMLU specification is also
available as `--domain2 afrimmlu` with a prepared benchmark and a separate
run directory. Both options keep the same call counts.

| Component | Source groups | Pairs at 75 sources | Calls at 75 sources | Pairs at 300 sources | Calls at 300 sources |
|---|---:|---:|---:|---:|---:|
| H1 anchor | 15 or 60 | 60 | 720 | 240 | 2,880 |
| H1 test | 60 or 240 | 480 | 5,760 | 1,920 | 23,040 |
| H2 supplementary AfriQA | 15 or 60 | 120 | 1,440 | 480 | 5,760 |
| **Total judging** | | **660** | **7,920** | **2,640** | **31,680** |
| Generation before repairs | | | **915** | | **3,660** |

There are six judges, each run in both orders. The 300-source benchmark is already
in `study/benchmark-300.json.gz`. The 75-source tier has its own benchmark, schedule,
and default run directory. Use that tier only by explicitly passing `--total-sources 75`.

## Setup and free verification

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[study]'
afrijudge study-plan
afrijudge study-preflight
```

Preflight verifies the benchmark checksum and checks the public model catalog.
It reports route pins, token assumptions, and separate cost estimates for
generation and judging. Model output length, reasoning tokens and retries affect
billing. The catalog lists Llama FP8 as `deepinfra/turbo` and Qwen FP8 as
`deepinfra/fp8`. The branch pins them separately. Four-second pacing across six
queues allows about 5.9 hours of minimum start spacing for judging, with request
latency and cooldowns extra. Use `afrijudge study-preflight --domain2 afrimmlu` to
check the AfriMMLU-only benchmark.

## Generate and judge

Set `OPENROUTER_API_KEY` in your environment. The two stages use the same
ledger and total budget. Set `OPTION_C_BUDGET` to your approved total amount in
US dollars. This one command generates the stimuli, exports the audit and judges
after the programmatic checks pass.

```bash
caffeinate -i afrijudge study-run --auto-approve-programmatic \
  --gen-max-tokens 1024 --judge-max-tokens 256 \
  --max-spend-usd "${OPTION_C_BUDGET:?Set OPTION_C_BUDGET}" --execute
```

On Linux, omit `caffeinate -i`. Paid execution requires `--execute` and a positive
budget ceiling. Generation retries only failed drafts, using at most four
validation attempts and raising the token cap for truncated drafts. Judging
uses a separate 256-token limit. The completion is read using the strict v2
protocol requiring a full JSON verdict and short reasoning. Invalid, tied,
and position-unstable judgments are retained explicitly.

To stop for review first, run `generate-all-stimuli` with the same token caps,
budget and profile. Both paths freeze the pairs and export the review sheets
plus a deterministic stratified 10% audit sample (264 comparisons at full scale).
For human sign-off, give each row in the three review sheets a `PASS`,
reviewer and evidence, then run `study-run` without the auto-approval flag. To complete the audit, have fluent reviewers
independently check reasoning correctness, consistency of the foil across H1
conditions, number-word grammar, and fidelity and style in H2. The audit file
starts with pending rows and makes no claim about human agreement. Deterministic
checks cover answer tags and the designated conclusion in the prose, the
arithmetic conclusion form, the absence of judge-facing tags and symbolic math,
paired lengths, formal style markers, and the complete H2 grid. The check for
the conclusion is a content check. Fluent reviewers still assess whether the
surrounding prose supports that conclusion or preserves the intended error.

On interruption, rerun the same stage and arguments. The SQLite ledger caches
completed requests and applies the ceiling across both stages. A model held back
by 429s receives up to eight, 180-second cooldowns while other model queues
continue. Transport failures with uncertain billing retain their reservation
and require the ledger recovery described in [operations.md](operations.md).
A cached provider error can be inspected and recovered by request ID with
`scripts/recover_api_error.py`. Review `requests.jsonl` and the ledger together
for generation and judge request history. Preserve `pairs.json` and
`judge_requests.jsonl` to recompute `report.json` with `afrijudge study-analyze`.

## Real benchmark sources

| Use | Published source | Alignment and preprocessing |
|---|---|---|
| Reading | [Belebele](https://huggingface.co/datasets/facebook/belebele) | Join by article link and question number, check the choice key, select at most one question per article. |
| Conceptual | [AfriMMLU](https://huggingface.co/datasets/masakhane/afrimmlu) | Align test row and subject, check the answer key in all four languages. |
| Arithmetic | [AfriMGSM](https://huggingface.co/datasets/masakhane/afrimgsm) and [GSM8K](https://github.com/openai/grade-school-math) | Align by test row and final gold, then verify published arithmetic expressions and every intermediate result against the 1–1,000 integer restriction. Render digits and currency markers into words. |
| Explanatory | [FLORES-200](https://github.com/facebookresearch/flores/tree/main/flores200) and [SIB-200](https://huggingface.co/datasets/Davlan/sib200) | Group FLORES sentences by article URL and verify SIB labels on matching four-language text. Use the SIB label as gold for an open-ended three- to four-sentence synthesis prompt. |
| H2 | [AfriQA](https://huggingface.co/datasets/masakhane/afriqa) and [published gold passages](https://github.com/masakhane-io/afriqa/tree/5c29933753692c28773c34ac1f68482007f1d2bb/data/gold_passages) | Exact normalized original and English question join. Retain a distinct article and answer-bearing evidence passage per topic. |
| Logical inference (Domain 2) | [AfriXNLI](https://huggingface.co/datasets/masakhane/afrixnli) | Align test rows and check labels. Select a single hypothesis per premise before splitting. |

Each upstream revision or archive hash and each downloaded file checksum is
recorded in the frozen benchmarks. The downloads require no dataset credentials.
The Git repository and ZIP include the real selected passages and questions.
Candidate generations and judgments are produced by the named model endpoints at
execution time.

To rebuild either tier or extract the full eligible pools:

```bash
python scripts/build_scaled_benchmark.py --total-sources 300
python scripts/build_scaled_benchmark.py --total-sources 75
python scripts/build_scaled_benchmark.py --domain2 afrimmlu
python scripts/extract_open_benchmarks.py
```

Extracted JSONL records use the requested per-source shape: `source_id`,
`domain`, `dataset`, `license`, and `language_sources`. Reading and
conceptual records carry the original question, choices, and gold and foil
options. Arithmetic records carry integer gold/foil and both the original
question and its number-word rendering. AfriXNLI records carry premise,
hypothesis and label. SIB records carry passage and gold/foil categories.
AfriQA preserves the native question, English translation and published
answer passage. Its `language_sources` contains the two published variants.
The frozen run manifest nests the source fields and compiled prompts separately
from judge messages. Default run directories follow
`runs/option-c-v3-<profile>-<tier>`. This keeps both profiles and any earlier run
separate.

The published selections exclude all 57 source IDs recovered from the 672
frozen Study 1 pairs, together with previous exclusions and repository pilot
samples reproduced using their original settings. The manifest records the
input fingerprint and IDs in `study/excluded_source_ids.json`. The original
independent quarantine list referenced in the proposal remains unavailable.
Additional quarantines can be added using
`--exclude /path/to/excluded_source_ids.json --output study/benchmark-300-local.json.gz`
and passed to the runner via `--benchmark`. Earlier FLORES
pilot articles are excluded at document level. H1 and H2 retain separate source
IDs even though they share an allocation schedule. The 60 FLORES-200 test groups
and 60 AfriQA topics come from different releases. Only the AfriQA original
language and English pivot are human-authored versions in each H2 topic. The
other target-language versions are generated and labeled in the review and report.

### Dataset attribution

The MIT license covers the software. The benchmark includes material adapted
from readers and passages in Belebele (Bandarkar et al.), FLORES-200 (NLLB Team),
SIB-200 (Adelani et al.), and AfriQA (Adelani et al.), distributed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). The dataset
URLs and, where available, article URLs and AfriQA passage titles are included
in the benchmark. Selection, grouping, number rendering and prompts are
documented above. The AfriMMLU, AfriMGSM and AfriXNLI releases (Adelani et al.,
IrokoBench) carry the [Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0).
GSM8K (Cobbe et al.) is used for validation against its released answer steps.
The frozen materials retain the upstream terms.

## Analysis definitions

- **H1.** Compare neutral with wrong-calqued shortcut pairs using the same
  question, correct response and foil conclusion. Format, length and calqued
  phrasing form one intervention. Test agreement, wrong majorities, coverage,
  position instability and shared errors. Compare Top-3 and Bottom-3 ranks
  learned separately in each language from anchors. The rubric judges
  correctness and clarity without prompting against the tested shortcut.
- **H2.** Test four languages by two styles. Each AfriQA topic has one
  human-authored Hausa, Yorùbá or Igbo question and one released human English
  pivot. The other LRL question forms are derived by models. The same evidence
  within each language is used in both styles. English uses formal Latinate
  prose in the template condition. Both question and candidate style change,
  so the contrast estimates their joint effect. The report includes
  provenance, coverage, decisive-only gaps and leave-one-matchup-out estimates.
- **H3.** Compare anchor-calibrated LRL-CARE against the six-judge majority,
  Top-1, Top-3 and an anchor-fitted symmetric Dawid–Skene rule. With one judge
  per family, family-equal majority and ordinary majority coincide. Calibrate
  thresholds and weights on anchors, then score correct and wrong decisions
  and abstention separately on test items.

Intervals resample paired source groups within H1/H3 domains or H2 matchups.
They are individual 95% intervals. A positive H2 score is a selection-rate gap,
with candidate selection and abstention reported separately.
