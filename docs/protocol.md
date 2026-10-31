# Pilot protocol

## Research questions

1. How does correctness-conditioned cross-family consensus vary across English, Hausa, Yorùbá and Igbo?
2. Which families prefer shortcut-rich incorrect translations once their errors are independently validated?
3. How do orthography and rubric language interact with stable judge preferences?

Proposed mechanisms and directions of effects are hypotheses. Cross-family correlation does not identify its cause. An API-only behavioral study does not directly measure hidden-state geometry.

## Sampling and pair selection

Sample 30 AfriMMLU and 30 AfriMGSM source row IDs, shared across four languages. Five families generate on every item. Parse exactly one final answer tag; unparseable or truncated generations are excluded from candidate pairing, and reported separately.

For each language/item, sample at most one correct–incorrect pair and one pair of two incorrect answers with a deterministic item-specific RNG. Randomize canonical candidate sides, then judge both AB and BA. These are correctness-conditioned contrasts: all-correct/all-wrong generator items can be absent from the valid contrast subset. Report yields and generator correctness by language. For strict cross-language comparisons, restrict to the common item intersection and report the lost coverage; do not interpret different selected subsets as a pure language effect.

Two wrong answers may differ in relevance, reasoning quality, or degree of error. Their same-pair own-family versus other-family preference contrast is descriptive. It is not an identified pure self-preference parameter. Equal-quality judgments and causal decomposition require additional annotation or stronger interventions.

## Translation foils

Use 30 aligned FLORES references per low-resource language. English is the source, and the target reference is a human translation, not original native prose. Alternate GPT-4o and Gemini foil generation across source items. Generate one concise-error foil and one styled-error foil. Their prompts ask for an error, but successful error insertion is not assumed. A judge can prefer either before its meaning has been checked; report these outcomes as preferences.

The two conditions vary a bundle of features; they do not isolate verbosity from literal syntax, formatting, or error severity. A publishable mechanistic follow-up should use minimally different, validated response variants. After a fluent reviewer assigns a supported pairwise winner, the annotation overlay enables gold-based analysis. Both reference and foil must be judged against the actual source. Translation-reference provenance does not guarantee reference perfection.

## Orthography and rubric probes

Select up to 35 distinct item IDs per language (Yorùbá/Igbo) with at least one removable mark. Cross intact/stripped responses with English/target-language rubric. The intact/English cell reuses baseline calls; three additional cells are evaluated. Remove marks from both candidates, preserving canonical side identity. Recompute surface features. The question is unchanged: this intervention is specifically candidate orthography, not total prompt orthography.

A non-changing transform is not a probe. Removing marks can change lexical identity and correctness; no original answer key is inherited for stripped conditions. Native rubrics are drafts and may introduce translation-quality confounds. Revalidate rubrics with fluent speakers before confirmatory comparisons. Tokenizer fertility and model uncertainty are not inferred from UTF-8 bytes or word counts. The current pilot stores transparent surface features only.

## Judging and missingness

Use one judge per configured family, temperature zero, with a seed only when the endpoint lists support. Temperature zero is not a determinism guarantee. Candidate identity, gold keys, and generation metadata are withheld from judge prompts; text can still reveal style.

Accept one JSON verdict A/B/TIE. A verdict must survive side-swapped judging to be stable. Explicit ties, order instability, invalid output, and missing outputs are distinct. Panel accuracy requires a strict majority of all configured judges for the gold candidate; exactly half is not a win. Report decided-only accuracy alongside coverage and all-pairs accuracy.

Agreement statistics use complete stable rows with A/B/TIE categories and report their denominator. Error dependence uses complete decisive A/B rows on gold-labeled pairs and reports that narrower denominator. Constant error columns have undefined correlations, not zero correlations. Effective-vote estimates use an explicitly approximate exchangeable-error expression; do not call them exact Kish sample sizes for arbitrary panels.

## Statistical scope

Bootstrap panel-accuracy intervals by underlying source item (1,000 draws). Source IDs shared across conditions/languages must remain grouped in any future pooled inference. Report invalidity, selection, abstention and per-language yields before hypothesis tests.

The marginal-column permutation diagnostic preserves judge marginal accuracies but destroys item difficulty. It is an exploratory dependence diagnostic, not an item-aware Condorcet counterfactual. No publication-level p-value or causal conclusion should rest on it alone. The current implementation does not fit the full planned crossed GLMM, compute partial causal variance decompositions, or implement the entire eight-ablation study.

Cross-fit aggregation weights and error-correlation penalties on training folds only. Select the comparison single judge using training folds only. Do not choose the best single judge on test labels and call it a deployable baseline. Keep anchor items, hyperparameter selection, and final test sets separate in the full study.

## Before a confirmatory study

Freeze model/provider configurations and dataset splits; validate rubrics and foil labels; audit the common item intersection; power the main estimands using pilot uncertainty; specify handling of missing/tied votes and multiple comparisons; preregister before evaluating the held-out full study. Do not choose whether an experiment is a success solely by whether it matches the favored hypothesis.
