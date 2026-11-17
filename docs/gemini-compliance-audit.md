# Option C requirements audit

Audited on 17 November 2026 against the three supplied Gemini documents and the
dataset-pin instructions. The audit started at GitHub revision
`694ed8ffa689f585be4eedabec73904995ede88a`. Implementation corrections were
published in `a3fd2d7f272873867fc44ac6b368e0ddf24b141e`.

## Verification performed

- Rebuilt all four packaged manifests from the pinned inputs and compared their
  complete serialized contents with the packaged selections.
- Downloaded all 36 distinct upstream files without dataset credentials and
  checked their SHA-256 hashes against the frozen manifest. This includes the
  FLORES archive, AfriQA questions and gold passages, and GSM8K validation data.
- Recovered 57 unique source IDs directly from the uploaded 672-comparison
  Study 1 file and verified zero overlap with every packaged selection.
- Re-extracted all seven export files and reproduced the existing exports.
- Rechecked all six pinned model routes through the live public catalog.
- Passed all 125 tests and the repository lint and formatting checks, including
  tests for the complete 31,680-slot offline schedule,
  order mapping, analysis, rate-limit recovery, and automatic audit export.

Candidate generation and the paid Study 2 judgments await execution. The offline
schedule uses explicitly identified test fixtures.

## Requirement mapping

| Requested requirement | Verified implementation |
|---|---|
| 300 H1 sources across four languages and four domains | 75 sources per domain, each with 15 anchors and 60 tests. The totals are 60 anchor sources, 240 test sources and 1,200 language-items. |
| Every named dataset | Belebele, AfriMMLU, AfriMGSM, AfriXNLI, SIB-200, FLORES-200 and AfriQA with published gold passages are extracted. The default schedule uses each release. |
| Pinned downloads and portable exports | Exact revisions and downloaded file hashes are frozen. JSONL exports use `source_id`, `domain`, `dataset`, `license` and `language_sources`. |
| Previous-source exclusions | Each frozen manifest carries 153 exclusions, including IDs reproduced from earlier repository pilot profiles and all 57 recovered Study 1 IDs. Canonical IDs, legacy aliases and constituent FLORES/SIB IDs are checked. |
| Disjoint anchors | A source remains together across languages and conditions. Article-level selection also avoids repeated Belebele/FLORES articles, and AfriXNLI contributes one hypothesis per selected premise. |
| Balanced H1 authors | GPT-4o, Gemini and Claude each author five anchors and 20 tests per domain at full scale. Both H1 candidates for an item use the assigned author. |
| Internal answer tags removed | Tags are validated during generation and removed from judge-facing prose. Judge messages contain the question and response text. |
| Naturalistic judging | The study entry point selects the naturalistic rubrics. The explicit warning against length and formatting is absent from those rubrics. |
| Two H1 test conditions | Each neutral and shortcut pair shares the exact question and correct response. Shortcut foils require expanded length, Markdown structure, the designated conclusion and an assigned formal transition. |
| Arithmetic in words | The compiler supports integers from zero through 10,000. Selected published operands and intermediate results fall between one and 1,000. Compiled arithmetic questions and responses are checked for digits and symbolic arithmetic. |
| H2 four-by-two design | Each of 60 AfriQA topics appears in all four languages and both styles. Each matchup receives 20 topics. Original-question language is balanced overall and distributed six or seven per matchup. |
| Automatic launch and 10% audit | `study-run --auto-approve-programmatic` freezes and checks pairs, exports 264 audit rows and proceeds to judging. Audit rows include matched conditions and published H2 question/evidence references. |
| Independent model pacing | Pacing keys contain both provider and model. The default interval is four seconds. Rate-limited queues get up to eight cooldowns of 180 seconds each while other queues proceed. |
| Separate token limits | Generation defaults to 1,024 and judging to 256. Length-truncated generation can receive bounded repairs up to four times the starting cap. |
| Cached requests and budget accounting | The shared SQLite ledger retains completed requests and reservations. Explicit execution and a positive total budget ceiling control paid calls. |
| H1 and H3 held-out analysis | Anchor-based rankings and shared-error-adjusted weights are evaluated on held-out tests. The report includes correct decisions, wrong decisions, coverage, agreement, shared errors and paired source-group intervals. |
| H2 uncertainty | Paired topic intervals preserve all eight cells and stratify by matchup. The report includes decision coverage, decisive-only estimates, leave-one-matchup-out estimates and matched human-original subsets. |

## Dataset allocation and extracted counts

These counts are the pools produced by the implemented eligibility rules.

| Export | Eligible exported rows | Full-scale allocation |
|---|---:|---|
| Belebele | 892 | 75 H1 sources |
| AfriMMLU | 344 | 45 H1 sources in the default profile |
| AfriXNLI | 600 | 30 H1 sources in the default profile |
| AfriMGSM | 102 | 75 H1 sources |
| SIB-200 | 1,004 | Supplies labels for FLORES article groups |
| Grouped FLORES with SIB labels | 128 | 75 H1 sources |
| AfriQA with aligned gold evidence | 287 | 60 supplementary H2 topics |

`--domain2 afrimmlu` selects 75 AfriMMLU sources. Both Domain 2 profiles are
packaged at 75-source and 300-source scales. Raw release counts differ from the
eligible pools after exclusions, duplicate grouping and quality restrictions.

## Corrections made during this audit

- Generation repairs now receive the rejected draft together with validation
  feedback and a distinct attempt number. Previously, the repair prompt referred
  to a draft that it omitted from the request.
- Conclusion matching preserves Unicode combining marks, including Yorùbá tone
  marks, when checking token sequences.
- Audit rows now contain the other condition and the published H2 references
  required to assess error preservation, translation fidelity and style.
- H2 now includes paired estimates restricted to each language's 20
  human-original topics at full scale.
- H1 now includes the lower-versus-higher proficiency interaction in the change
  under the shortcut, neutral coverage, and full-majority versus Top-1 correctness
  under the shortcut.
- The benchmark reader now rechecks exclusion aliases and all constituent
  sentence IDs when loading a frozen manifest.

## Specification differences and remaining verification

1. The original design specified 75 AfriMMLU items. The later request to use all
   datasets led to a default of 45 AfriMMLU plus 30 AfriXNLI items. The original
   allocation remains selectable.
2. H2 uses 60 additional AfriQA topics attached to the allocation slots of the
   60 FLORES test groups. H1 and H2 together therefore use 360 distinct source
   groups. Their total judgment count remains 31,680.
3. Each AfriQA topic supplies one human-authored local-language question and one
   human English translation. Two other local-language questions, all formal
   questions, and local-language evidence passages are model-derived. These
   provenance distinctions appear in the frozen pairs and the report.
4. H2 varies question style and candidate-answer style together. Its contrast
   estimates their combined effect. A prompt-only effect would require an
   additional controlled design.
5. Deterministic checks establish label presence, structure and assigned marker
   presence. Fluent reviewers still assess correctness of the reasoning, the
   single-error foil, equivalent meaning, genuine calquing and number-word
   grammar. The pending 264-row audit is ready for that assessment.
6. The separate original quarantine list remains unavailable. Verified
   disjointness covers the supplied Study 1 file and exclusions recoverable from
   repository profiles and records.
7. The live catalog identifies Llama's FP8 route as `deepinfra/turbo` and Qwen's
   as `deepinfra/fp8`. The configuration uses those distinct route names.
8. The fixed LRL-CARE rule uses anchor reliability, coverage and shrunk positive
   shared-error correlations. Its voting threshold is fixed at 0.6. The
   Dawid–Skene baseline is an anchor-fitted symmetric reliability model.
   Family-equal majority coincides with ordinary majority because each family
   supplies one judge. A separate reproduction of the published PoLL protocol
   is outside the implemented comparisons.
9. The preflight estimate uses 600 input and 80 output tokens per judge call,
   and 750 input and 320 output tokens per generation call. At the catalog
   prices checked for this audit it totals about $56.58 before repairs.
   Four-second spacing permits about 5.9 hours of minimum judging start spacing.
   Actual generation, latency, rate limits, reasoning and retries affect both
   runtime and spend. The 256-token cap still permits truncated or invalid judge
   responses, which are retained in the analysis.

The implementation tests H1, H2 and H3 as falsifiable hypotheses. The eventual
direction or strength of those results depends on the completed observations.
