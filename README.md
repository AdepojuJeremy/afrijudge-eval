# AfriJudge-Eval

[![CI](https://github.com/AdepojuJeremy/afrijudge-eval/actions/workflows/ci.yml/badge.svg)](https://github.com/AdepojuJeremy/afrijudge-eval/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Research status](https://img.shields.io/badge/status-pilot%20implementation-64748b.svg)](docs/protocol.md)

Reproducible experiments on **LLM judge consensus, model-family preference, and shared errors in low-resource languages**.

[Quick start](#quick-start) · [Experiments](#experiments) · [Models](#models) · [Protocol](docs/protocol.md) · [Operations](docs/operations.md) · [Code audit](docs/code-audit.md) · [Verification](docs/validation.md)

AfriJudge-Eval investigates when agreement among judges from different model families is informative about correctness—and when it reflects shared mistakes. The pilot compares English with Hausa, Yorùbá, and Igbo, using verifiable tasks, exploratory translation foils, and controlled orthographic and prompt-language probes.

This repository contains the experiment runner, source-data preparation, provider validation, request ledger, and statistical readout. **Research results are pending.** Offline examples test the software only; they are not empirical findings. The proposed proficiency-consensus inversion and LRL-CARE improvement remain hypotheses.

## Experiments

| Experiment | Question | Implementation |
|---|---|---|
| **1 · Verifiable consensus** | Does cross-family agreement predict correct judgments? How do same-family preferences differ from other judges' preferences? | Parallel AfriMMLU and AfriMGSM items; five generator families; correct–incorrect contrasts and a separately labeled both-incorrect stratum |
| **2 · Shortcut-rich foils** | Do different families prefer a deliberately corrupted translation over a human reference? | Concise-error and styled-error foils; exploratory preferences first; false-consensus metrics only after semantic validation |
| **3 · Orthography × prompt language** | How do removing diacritics and changing rubric language affect verdicts? | A crossed 2×2 design for Yorùbá and Igbo; original baseline reused; both candidates transformed consistently |

All three experiments run through one command and share one API budget and request cache. Generation precedes pair construction; judging runs concurrently with a bounded worker pool. They cannot execute as three independent simultaneous jobs because Experiments 2 and 3 share upstream artifacts.

Both-incorrect responses are **not assumed equal quality**. A changed verdict after diacritic stripping is an intervention effect on judging; stripping can also change meaning. Target-language rubrics are drafts awaiting fluent-speaker validation. See the [protocol](docs/protocol.md) for estimands, exclusions, and interpretation limits.

## Quick start

Use Python 3.11 or 3.12 on Linux/macOS; Windows users should use WSL.

```bash
git clone https://github.com/AdepojuJeremy/afrijudge-eval.git
cd afrijudge-eval
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Test the complete offline workflow without a key or API charges:

```bash
pytest -q
afrijudge demo --run-dir runs/demo
```

Inspect the plan, validate model endpoints, and prepare real data:

```bash
afrijudge plan
afrijudge preflight
afrijudge prepare
```

The default config requests **240 parallel verifiable items**, **90 translation references**, and up to **35 probe baselines per language** in Yorùbá and Igbo. With both foil styles and all crossed probes, the maximum is **1,200 generation calls + 180 foil calls + 10,440 judge calls**. Actual yields depend on generator correctness, parsing, and available diacritics. These bounds replace the inconsistent call counts in the original sketch.

Enter your OpenRouter key locally, then launch the three-experiment suite:

```bash
read -rsp 'OpenRouter API key: ' OPENROUTER_API_KEY; echo
export OPENROUTER_API_KEY
afrijudge run --execute
```

The key is read from the environment, never from the YAML config. `.env.example` is a reference template; the CLI does not automatically load `.env`. Never paste a key into a GitHub issue, commit, config, or shared result file.

`afrijudge run` without `--execute` only prints a plan. Resume an interrupted run with the **same command and unchanged inputs/code**. Successful responses are reused. Potentially billed ambiguous requests require reconciliation first; see [operations](docs/operations.md).

Optional small **paid** smoke run using real data:

```bash
afrijudge run --smoke --data data/smoke --run-dir runs/smoke --execute
```

Smoke and pilot directories have separate ledgers and spend limits. Use the free demo for initial verification; any paid smoke spend is additional to the full run's ceiling. The default ceiling is **$45 per run**, shared across every generation and judgment stage. It is a stop limit, not a promise that the expanded suite will finish for $45. Set an OpenRouter key/account limit as an independent billing backstop.

## Models

The pilot retains five generator families and six judge families. Endpoint availability, rates, precision, and provider identity are checked and recorded before paid execution.

| Alias | OpenRouter model ID | Generate | Judge |
|---|---|:---:|:---:|
| `gpt4o` | `openai/gpt-4o-2024-08-06` | ✓ | ✓ |
| `gemini25pro` | `google/gemini-2.5-pro` | ✓ | ✓ |
| `claude_sonnet` | `anthropic/claude-sonnet-4.6` | ✓ | ✓ |
| `llama33_70b` | `meta-llama/llama-3.3-70b-instruct` | ✓ | ✓ |
| `qwen25_72b` | `qwen/qwen-2.5-72b-instruct` | ✓ | ✓ |
| `cohere_multilingual` | `cohere/command-r-08-2024` | — | ✓ |

Sonnet 4.6 replaces the unavailable Claude 3.5 Sonnet ID; Command R replaces the unavailable Aya Expanse 32B ID. These are **model changes**, not equivalent checkpoints. Cohere remains an external family control; no Aya-specific claim should be made. The original IDs and rationale are documented in the [audit](docs/code-audit.md).

Llama endpoints must meet the `bf16`/`fp16` filter. Qwen explicitly permits `bf16`/`fp16`/`fp8`; its verified available route was DeepInfra FP8. This is a recorded precision change, with no assumption that FP8 is equivalent to BF16. Provider fallback is disabled. `preflight` selects an eligible endpoint; the first real run saves `models.lock.json` and reuses it on resume. Edit the configuration to change a model or provider and start a new run directory. Availability is checked at runtime; an endpoint listing does not guarantee that your key has access.

## Data

| Source | Use | Provenance / license |
|---|---|---|
| [AfriMMLU](https://huggingface.co/datasets/masakhane/afrimmlu) | Multiple-choice questions | Human-translated IrokoBench task; consult source card |
| [AfriMGSM](https://huggingface.co/datasets/masakhane/afrimgsm) | Numeric-answer reasoning | Human-translated IrokoBench task; consult source card |
| [FLORES-200](https://github.com/facebookresearch/flores/tree/main/flores200) | Parallel translation references | Human translations; CC BY-SA 4.0; **not native-original prose** |

IrokoBench is a collection: the loader uses the actual `masakhane/afrimmlu` and `masakhane/afrimgsm` repositories, with `eng`, `hau`, `yor`, and `ibo` source codes. Revisions are pinned to commit hashes. FLORES is downloaded from the official public archive and checked against a SHA-256 checksum. It provides one aligned reference source across all pilot languages; MENYO-20k and SSA-MTE are not silently substituted or claimed as evaluated.

Sampling uses the same source row IDs across languages and checks lengths and answer-key alignment. This verifies structural alignment, not every translation's semantic accuracy. Downloads and schemas fail visibly; there is **no synthetic fallback**. Data remain local and are excluded from Git. Preserve source attribution and licenses before redistributing any derivative dataset.

## Outputs and analysis

```bash
afrijudge status --run-dir runs/pilot
afrijudge analyze --run-dir runs/pilot
```

| Artifact in `runs/pilot/` | Contents |
|---|---|
| `manifest.json`, `models.lock.json` | Config, source/code identity, environment, provider and pricing snapshot |
| `ledger.sqlite`, `requests.jsonl` | Durable paid-request accounting and reusable responses |
| `generations.jsonl`, `generation_diagnostics.json` | Generator outputs, parsing coverage, correctness and exclusions |
| `pairs.jsonl` | Candidate provenance, conditions, baseline IDs, validated or absent gold |
| `raw_verdicts.jsonl`, `verdicts.jsonl` | AB/BA judgments and reconciled outcomes |
| `foil_review.jsonl` | Content-bound foil validation worksheet; preserve and complete locally |
| `report.json` | Agreement, validity, error dependence, probe shifts and exploratory calibration |

AB/BA conflicts are `ORDER_UNSTABLE`, not quality ties. Invalid outputs stay invalid. Accuracy uses fixed panel membership and reports abstention/decision coverage. Unanimous error requires every judge to choose the same objectively wrong candidate. Undefined correlations remain undefined. Bootstrap intervals resample underlying item IDs.

Calibration compares majority voting, accuracy weighting, a covariance-penalized **CARE prototype**, and a single judge selected on training data. Five-fold splits keep the same underlying item out of calibration and evaluation simultaneously. The prototype has not established an algorithmic contribution. The report explicitly labels its marginal-independence shuffle diagnostic; it is not an item-difficulty-adjusted Condorcet theorem test.

Generated foils initially have no gold winner. A fluent reviewer can fill `gold`, `reviewer`, and supporting `notes` in `foil_review.jsonl`, then rerun `analyze` without API calls. Labels are bound to candidate-content hashes. For publication, use a documented multi-rater adjudication process; a completed worksheet alone is not proof of annotation quality.

## Research status

| Milestone | Status |
|---|---|
| Three-experiment pipeline and offline tests | Implemented |
| Live paid pilot | Pending researcher execution |
| Foil and target-language rubric validation | Pending |
| Proficiency-consensus inversion | Hypothesis; untested |
| LRL-CARE gains | Hypothesis; prototype only |
| Full study, additional languages and ablations | Planned |
| Paper / preregistration / released empirical results | Pending |

Results, exact sample yields, confidence intervals, model snapshots, and limitations will be added after the pilot. There are no fabricated scores, publication claims, or placeholder paper links.

## Development

```bash
ruff check .
ruff format --check .
pytest -q
```

A tested Python 3.12 environment is pinned in `requirements-py312.lock` (`pip install -r requirements-py312.lock`). The package follows the Python `src/` layout. Add models in YAML, intervention conditions in `pipeline.py`, prompts in `prompts.py`, and estimands in `stats.py`. Prompt contents, source data, code, and model routing enter run identity or request hashes. See [CONTRIBUTING.md](CONTRIBUTING.md) and the [future-study roadmap](docs/roadmap.md).

## Citation

For now, cite this repository and the exact commit used. Software metadata are in [CITATION.cff](CITATION.cff). Cite each underlying dataset and relevant methodological paper separately. A paper citation will be added when available.

## License

Code is released under the existing [MIT License](LICENSE). Dataset licenses and model/provider terms remain separate. Do not infer permission to redistribute data from this repository's code license.
