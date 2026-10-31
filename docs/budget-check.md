# Pre-execution budget check

Public provider metadata checked on 2026-10-31. No paid completion calls were made.

The original planner reports **1,200 generations + 180 foils + at most 10,440 judgments = 11,820 calls**. It does not report an estimated dollar cost. The new `afrijudge estimate` command checks live endpoint prices and exposes conditional token-use scenarios.

| Profile | Illustrative usage + 10% margin | Full output caps + 10% margin | Longer inputs and full caps + 10% margin |
|---|---:|---:|---:|
| Original: 30 MMLU, 30 MGSM, 30 references, 35 probes | $24.79 | $54.79 | $67.97 |
| Suggested trim: 30 MMLU, 30 MGSM, 25 references, 25 probes | $22.61 | $49.87 | $61.76 |
| Added budget profile: 20 MMLU, 20 MGSM, 20 references, 20 probes | $16.08 | $35.50 | $44.00 |

These are scenario calculations, **not measured experiment spend or unconditional bounds**. Every row uses maximum planned pair yields. Illustrative usage assumes 500 generation input / 350 generation output tokens and 650 judge input / 150 judge output tokens. The full-output scenario uses 768 generation and 512 judge output tokens. The longer-input scenario raises generation input to 1,000 and judge input to 1,500 tokens. Output token assumptions include reasoning. Actual outputs, prompts, pricing, caching, missingness and pair yields vary. Payment/top-up fees are excluded.

The original full-output-cap scenario is $49.81 before the margin. The smaller 20-item profile has at most **800 generations + 120 foils + 6,720 judgments = 7,640 calls**. It preserves all control conditions while reducing statistical power. Its longer-input scenario fits narrowly below $45 with the modeled margin; it is still not a guarantee that any possible run will finish under $45. The runner's shared ledger and a provider-side key spend limit remain necessary.

The final model config uses **Sonnet 4.6**, not Sonnet 5. Gemini requests a 128-token reasoning budget; Sonnet requests reasoning effort `none`. Combined completion caps remain 768 for generation and 512 for judging. Actual endpoint behavior is untested without an authenticated paid call.

## Foil validation

English-side entity, number or negation substitution proves that the **English source** changed. It does not prove that a model faithfully translated the modified source, or that the resulting target-language foil is incorrect relative to the original. Back-translation and NLI are model-based screens, not deterministic semantic verification; API-based screens also incur inference cost. Running a local model avoids API charges but still uses compute.

Use these screens to flag candidate failures and prioritize fluent-speaker checks. Do not automatically upgrade all generated foils to human-verified gold. Gold overlays require an actual target-language validity assessment. Record automated validation separately if added later; preserve the distinction between a model screen and an independently verified semantic label.
