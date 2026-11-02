# Pilot audit and protocol revision — 2 November 2026

## Status

The budget pilot completed 800 candidate-generation, 120 foil-generation and
4,824 judge records. Eight records were provider-filtered: three generation
and five judge records, all GPT-4o/Azure on source `mgsm:246`. The accounting
readout was approximately $13.80, including conservative/uncertain charges;
it is not an independently verified invoice or current account balance.

The offline audit reproduced the baseline report and identified 205
recoverable *completed* final-JSON responses, 631 token-limit truncations,
and other format/label failures. Recovery is a separate post-hoc sensitivity
analysis. It must never overwrite the original `report.json`, ledger or
verdict files. Truncation is missing output, not a measured cognitive
abstention. Undefined correlations remain undefined.

Source and translation review identified problems in inherited gold keys,
question completeness, units, parameters and answer-tag consistency. The
expanded review flags are provisional assistant review, not independently
fluent-human-validated annotations. There is no validated CLEAN subset yet.
Do not infer that comparisons without detected defects are clean.

## What v2 changes

`config/pilot_revision_v2.yaml` explicitly opts into `verdict_first_v2`.
The original YAML profiles and version-1 prompt strings/parser stay available.
The new protocol uses RESPONSE_1/RESPONSE_2/TIE, requires the verdict first,
and bounds reasoning to 40 whitespace-separated words. The parser rejects
wrong keys/order, duplicate keys, wrong option labels, excessive reasoning,
extra prose and unsuccessful or truncated completions. Responses map back
to internal A/B/TIE only after this validation. AB/BA disagreement remains
ORDER_UNSTABLE; neither tie overrides nor partial-verdict guesses are used.

The same English serialization contract is appended to all v2 semantic
rubrics. The Yoruba and Igbo semantic rubrics remain drafts. This is an
explicit mixed-language format contract, not a claim of validated equivalent
native-only prompting. Do not combine v1 and v2 responses as replications of
the same prompt. Neither label changes nor a word limit guarantees reliability.

New raw v2 judgments record a parse diagnostic. Generation prompts remain
version 1; judge metadata records version 2. Full-run code/data/config hashes
continue to refuse resuming an old run with changed code. Keep the completed
pilot frozen at commit `235ac43fc1a0d8100aadfd517206a4ffb664ea71` if its original
executable environment is needed. Offline audit reads remain available without
running or changing it.

## Source quarantine

The v2 profile excludes these underlying source IDs in **all languages before
sampling**, preserving matched source sampling. New exclusions change the
prepared-data fingerprint; use a new data directory. This is conservative
quarantine, not a repaired dataset or exhaustive semantic audit.

| Source | Reason for quarantine |
|---|---|
| mmlu:398 | Inherited C=80% key conflicts with primary-source 89% electricity access in 2017; D=90% is the closest offered choice. |
| mmlu:426 | Labor quantity cannot be inferred from a wage without a demand/productivity schedule. |
| mgsm:47 | Provisional Igbo omission of the 50% red-tie price premium. |
| mgsm:82 | Provisional Hausa kilogram/pound inconsistency. |
| mgsm:110 | Provisional Yoruba omission of a required width. |
| mgsm:130 | Provisional Igbo omission of the starting worker count. |
| mgsm:183 | Provisional Igbo change from three seconds to four. |

Electricity evidence: [UN SDG 2019 Goal 7](https://unstats.un.org/sdgs/report/2019/goal-07/)
and [World Bank Energy Progress Report 2019](https://www.worldbank.org/en/topic/energy/publication/tracking-sdg7-the-energy-progress-report-2019).
Do not silently substitute D as gold, repair translations, reclassify generated
answers or reuse old response caches under new source meanings. Corrections
need content-bound reviewed overlays and new immutable dataset versions.

`mgsm:246` is **not quarantined as a source defect**. Its provider filtering
remains a separate missing-data sensitivity. Candidate-level reasoning/tag
contradictions also require response review: they do not justify automatically
excluding the whole source in every future generation. Bad reasoning in a
response that is genuinely wrong is not by itself an exclusion criterion.

## Offline reproduction

Run the conservative audit against the completed run, into a fresh directory:

```bash
python scripts/audit_completed_pilot.py \
  --requests runs/budget/requests.jsonl \
  --pairs runs/budget/pairs.jsonl \
  --report runs/budget/report.json \
  --raw-verdicts runs/budget/raw_verdicts.jsonl \
  --out runs/audit-v1
```

This script reproduces the original pilot-specific panel/family definitions,
then writes separate recovered verdicts, failure taxonomy and sensitivity
CSVs. It contains the initial conservative seven-pair screening rules; the
expanded semantic review is a separate annotation exercise, not a certified
clean set. Empty CLEAN-only subsets produce null rates. A/B/TIE labels in this
audit refer to the original v1 prompt; do not feed v2 RESPONSE_1 outputs to it.

## Small format validation

The format command uses saved baseline pairs and frozen source-run endpoints.
It generates no new candidate or foil responses and evaluates no hypotheses.
It selects comparisons deterministically across languages without using judge
outcomes. The selected responses themselves are not semantically certified.

Plan without network calls, API key or output-directory writes:

```bash
afrijudge validate-format --source-run runs/budget --run-dir runs/format-v2
```

Ten comparisons × six judges × AB/BA = **120 requests**, not ten requests.
The current diagnostic uses English semantic rubrics on saved baseline pairs;
it does not establish reliability of the native-rubric conditions. Validate
those separately after fluent rubric review. The format report separates
validity, truncation and order instability; it does not compute accuracy.

Only a deliberate `--execute` enables paid requests. The default new-run
stopping ceiling is $1 and cannot be raised above $1 by this command. Before
execution it reads the original SQLite accounting in read-only mode and caps
this diagnostic to the remaining pilot configuration headroom. The source
and validation run are locked during execution. Other runs, payment fees and
external spending are not included in that two-run check; maintain an
independent provider/account cap. A ceiling does not guarantee completion.

Execution requires the key locally, the original ledger and frozen model
lock. It writes a separate validation ledger/manifest/cache and preserves
pilot results. Cached successful calls are reused. Transport ambiguity retains
its reservation; do not automatically requeue uncertain calls. General
pilot pending-reconstruction helpers are not a validated recovery path for
this diagnostic. Inspect its ledger/status first. Fixed model routes may
become unavailable; failure must not silently change the route.

No paid validation was executed during this code revision. Zero failures on
this small repeated-item sample would still not prove reliability or validate
semantics. The new full-run profile is a draft: do not launch it as a
confirmatory study before the data, rubric, contrasts and sampling gates pass.

## Correct interpretation of the proposed narrative

The pilot does not establish that surviving consensus is contaminated by
translationese shortcuts. Foil semantics have not been validated. It also
does not establish that language proficiency causes format failure, that
models are cognitively abstaining, or that they suffer a high-entropy collapse.
A new name such as “Coverage–Consensus Dilemma” is a hypothesis/framing proposal,
not an empirical mechanism demonstrated by these artifacts.

The observed low coverage is worth investigating after separating technical
failure, source defects, order instability and explicit ties. Do not replace
H1/H2 with a favored explanation based on pilot outcomes. Determine the
confirmatory estimands and possible null/mixed outcomes in advance.

## Literature and novelty check

A targeted check on 2 November 2026 does **not** establish an exhaustive novelty
claim. It identifies material overlap that a contribution matrix must address:

- [Fu and Liu (2025)](https://aclanthology.org/2025.findings-emnlp.587/)
  evaluate multiple judge families across 25 languages and discuss ensembles.
  Describing prior multilingual work as only a static pointwise check is too narrow.
- [Kohli (2026)](https://arxiv.org/abs/2605.29800)
  measures correlated errors, effective votes and the independent-voting gap.
- [Mukherjee et al. (2026)](https://aclanthology.org/2026.findings-emnlp.1696/)
  examine consensus and human alignment with 42 judges across eight Indic languages.
  Thus multilingual consensus validity is already an active research topic.
- Primary arXiv pages for `2609.22512` and `2610.31172` could not be retrieved
  during this check. Secondary discovery records are insufficient for asserting
  their exact language scope or experimental exclusions; full-text verification
  remains open.

The specific African-language comparison and controlled decomposition remain
candidate contributions. “No one else has combined these” and “absolutely novel”
are not warranted by a targeted search or by finding the words together.
Measure the actual overlap in datasets, controls, estimands, human validation
and mechanism identification before stating the contribution.

## Preregistration gate

Draft the protocol now, but do not lock a sample size or n_eff using incomplete,
mostly unmatched and potentially mislabeled pilot contrasts. Separate technical
usability from content accuracy; estimate uncertainty using validated matched
anchors. See [preregistration draft](preregistration-draft.md). Do not register
hypotheses as if the already-inspected pilot were unseen confirmatory evidence.
