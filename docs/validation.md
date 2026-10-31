# Implementation verification

Checked on 2026-10-31 with Python 3.12.14. No paid completions were sent.

- 30 offline regression tests passed.
- Ruff lint and formatting checks passed.
- The synthetic demo exercised all three experiment paths and produced a labeled report.
- Real source preparation completed: 240 verifiable items and 90 parallel translation references.
- Source duplicates were excluded before aligned sampling; raw data were not committed.
- Public catalog and provider endpoint checks passed for all six configured models.

## Endpoint snapshot

This is an observed metadata snapshot, not a guarantee of future availability or key access. The runner resolves and freezes its own endpoint lock at execution.

| Alias | Provider endpoint | Precision reported | Input / output USD per million tokens |
|---|---|---|---:|
| `gpt4o` | `azure` | unknown | 2.5 / 10 |
| `gemini25pro` | `google-ai-studio` | unknown | 1.25 / 10 |
| `claude_sonnet` | `amazon-bedrock/global` | unknown | 3 / 15 |
| `llama33_70b` | `novita/bf16` | bf16 | 0.135 / 0.4 |
| `qwen25_72b` | `deepinfra/fp8` | fp8 | 0.36 / 0.4 |
| `cohere_multilingual` | `cohere` | unknown | 0.15 / 0.6 |

Qwen FP8 is explicitly permitted by the researcher. No claim of precision equivalence is made. Closed-weight endpoints reporting `unknown` precision cannot be described as verified BF16.

## Remaining live verification

An authenticated paid smoke run is still required to validate account permissions, actual provider behavior, parse coverage, latency, reasoning-token settings, and real billing. Catalog access alone does not validate those. The OpenRouter key was not supplied or requested for inclusion in this repository.

The $45 ceiling is a per-run application limit shared across stages, not an estimate that the entire expanded pilot must fit. Research hypotheses remain untested.

## Reasoning settings

Gemini 2.5 Pro requires reasoning; the request caps reasoning at 128 tokens while allowing a larger combined output budget. Sonnet 4.6 requests reasoning effort `none`. Output budgets are 768 generation tokens and 512 judge tokens; truncated responses remain invalid and are not reclassified as errors. Actual endpoint support must be checked in the paid smoke run.

## Sources

- https://openrouter.ai/api/v1/models
- https://openrouter.ai/docs/guides/routing/provider-selection
- https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
- https://huggingface.co/datasets/masakhane/afrimmlu
- https://huggingface.co/datasets/masakhane/afrimgsm
- https://github.com/facebookresearch/flores/tree/main/flores200
