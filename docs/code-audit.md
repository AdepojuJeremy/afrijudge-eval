# Audit of the supplied prototype

The pasted source contains multiple overlapping versions and a repository-generator script. It was reviewed as untrusted source text, not executed. The following changes replace correctness and research-validity defects rather than merely repairing indentation.

| Finding in supplied code | Correction |
|---|---|
| Mangled indentation, `init` instead of `__init__`, `if name == 'main'`, nested string artifacts | Installable `src/afrijudge` package, one CLI, linting and executable tests |
| Dataset failures become repeated synthetic questions and synthetic “verified native” references | Verified real source files; explicit failure; offline synthetic demo isolated from research runs |
| Source codes `en/ha/yo/ig` do not match IrokoBench configs | Explicit `eng/hau/yor/ibo` source mapping |
| Cached smoke data can be reused as full data | Configuration-bound data manifests and separate smoke directories |
| Answers guessed from arbitrary output text; parse failures treated as wrong candidates | Exactly one final answer tag; invalid generations excluded and counted |
| Two wrong responses called equal quality with gold TIE | Separate both-incorrect exploratory stratum without a gold winner |
| Correct answer always placed on canonical A | Deterministic randomized sides plus AB/BA judging |
| Separate generation/judge ledgers each allowed the full ceiling | One transactional shared ledger for every stage of a run |
| Budget check before concurrency admission; no in-flight reservation | Atomic reservations include in-flight calls and survive crashes |
| Cache hashes metadata only | Hash full request payload and metadata |
| Silent removal of provider precision constraints after endpoint failure | Endpoint preflight and immutable route lock; no precision/model fallback |
| Fixed stale rates and top-up fee called exact inference cost | Live endpoint prices; reported usage cost or labeled conservative estimate |
| Aya/Claude legacy IDs unavailable | User-selected Sonnet 4.6 and Command R replacements, recorded as design changes |
| Every generated corruption assumed semantically wrong | Unverified foil preferences separated from reviewer-validated error metrics |
| Diacritics stripped only from one candidate; old gold and token counts retained | Both candidates transformed, surface features recomputed, transformed gold cleared |
| Native prompt and orthography interventions not crossed | Full 2×2 probe with baseline reuse |
| AB/BA disagreements collapsed to quality ties or selectively resolved | `ORDER_UNSTABLE` distinct from TIE and INVALID |
| Six-judge 3–3 panel counted correct | Strict majority and explicit decision coverage |
| Error bits conflate candidate errors, ties, missingness and consensus | Gold candidate votes used directly; false consensus requires shared wrong candidate |
| Undefined correlations set to zero and negative correlations clipped | Undefined and negative correlations retained transparently |
| CARE estimates redundancy on evaluated trap gold | Training-fold-only fitting, held-out evaluation and calibration-selected single judge |
| Shuffle “Condorcet” test ignores item difficulty | Diagnostic explicitly labeled marginal-independence-only; no theorem claim |
| Repeated prompts treated as independent observations | Item-grouped bootstrap and cross-validation |
| Original pilot call arithmetic inconsistent | Explicit upper-bound planner; actual yield and spend reported |

## Model changes

The supplied plan used `anthropic/claude-3.5-sonnet` and `cohere/aya-expanse-32b`. Neither appeared in the public OpenRouter catalog checked during implementation. The researcher selected `anthropic/claude-sonnet-4.6` and `cohere/command-r-08-2024` as replacements. Public catalog checks confirmed these IDs. Runtime preflight still must verify an eligible endpoint and account access. Static price claims in the conversation are not treated as guaranteed current endpoint rates.

## Data change

The supplied MENYO/SSA-MTE loader did not actually load Hausa/Igbo references; it generated repeated seed sentences instead. This implementation explicitly uses the public official FLORES-200 archive across all three languages. The FLORES+ Hugging Face files could not be downloaded without access during implementation. The public archive was downloaded and SHA-256 checked. Human-translated references are not labeled native-original prose. A later native-prose study needs a different validated source.

## Scope retained and deferred

Implemented: all three pilot experiments, real-data preparation, exploratory foil review overlay, basic consensus metrics, family preference contrasts, orthography/rubric probes, and cross-fitted aggregation prototypes. Deferred: all eight main-study ablations, full native-expert annotation platform, tokenizer-specific fertility, internal representation measurements, formal item-aware independence modeling, crossed GLMMs and a confirmatory LRL-CARE evaluation. No empirical research results or venue guarantees are claimed.

Qwen precision update: the researcher explicitly permitted `bf16`/`fp16`/`fp8` after the only listed Qwen endpoint was verified as DeepInfra FP8. The actual chosen precision is locked per run. The final Anthropic selection follows the researcher's later Sonnet 4.6 config.
