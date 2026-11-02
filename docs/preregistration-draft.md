# Confirmatory protocol draft — not registered

This working draft preserves the original hypothesis direction while recording
what remains to be decided before independent confirmatory data collection.
The budget pilot and both offline audit versions have already been inspected.
They are development data, not the held-out confirmatory sample.

## Primary targets

1. On verified, matched correct–incorrect contrasts, measure whether panel
   agreement predicts correctness across English/Hausa/Yoruba/Igbo. Distinguish
   a lower all-comparison success rate caused by missing decisions from a higher
   wrong-consensus rate. A proficiency–consensus inversion requires a prespecified
   proficiency measure and comparison against a training-selected individual judge.
2. Distinguish same-family preference from cross-family preference under validated,
   minimally controlled content/style manipulations. Both-incorrect pairs with
   uncontrolled quality cannot identify pure self-preference. A literal-syntax,
   formatting and length bundle cannot isolate any one shortcut mechanism.
3. Analyze orthography/rubric interventions only after validating their semantic
   effects. Stripped text does not inherit gold automatically. Freeze whether the
   serialization contract is English across conditions or fully translated.

## Prerequisites before locking

- Validate source questions/keys and parallel meaning, candidate reasoning/final
  answer consistency, foils and rubrics. Record content hashes, reviewer identity,
  evidence and adjudication; leave unresolved cases uncertain.
- Freeze a new protocol/model/provider/data version and an independent test split.
  Do not pool the old and new prompts as interchangeable runs.
- Build enough common-item contrasts so conditional generator pair yields do not
  determine a different question population in each language. Document any
  constructed controls and their external-validity limits.
- Define proficiency using held-out verified items; generator accuracy alone is
  not a direct measure of the sixth judge's proficiency or a causal intervention.
- Prespecify exclusions and report uncertain cases included/excluded. Keep
  provider filtering distinct from source defects and cognitive abstention.

## Candidate analysis structure

These equations are draft specifications, not fitted results or final models.
At raw response level, analyze completion/format validity separately from content
correctness. An initial usability model could use

`logit P(valid_ijl) = alpha + language_l + judge_j + u_source_i`.

At reconciled judge level, report the probability of a stable decisive A/B vote.
Among such votes on validated gold comparisons, an initial correctness model is

`logit P(correct_ijl | decisive) = beta + language_l + judge_j + v_source_i`.

Language-by-judge interactions, task controls, source random effects and
condition effects must be finalized based on the actual crossed design and
validated independent sample. Conditional correctness under nonrandom missingness
is not an unbiased estimate of unconditional latent correctness. Report all-pair
success, conditional accuracy and coverage together; use sensitivity analyses
rather than imputing missing votes as observed cognitive errors or abstentions.

For panels, retain the six-member strict-majority threshold. Resample underlying
source IDs jointly across languages and conditions for paired comparisons.
Select the individual comparator and aggregation hyperparameters using training
anchors only; evaluate once on the independent test set.

Estimate error dependence only on clearly specified jointly observable error
vectors. Report complete-case counts and selection. Undefined constant-column
correlations are not zero. The exchangeable approximation

`effective_votes = K / (1 + (K - 1) * mean_error_correlation)`

is not an exact general Kish effective sample size for arbitrary heterogeneous
panels. Do not truncate or impute correlations to make it estimable. A marginal
column shuffle destroys item difficulty and is not a causal Condorcet benchmark.
A valid independent-voting reference and its assumptions need separate specification.

## Power and decision criteria still open

Do not use the current tiny complete-case correlations as reliable variance
inputs. Simulate planned estimands over plausible effect sizes, item difficulty,
judge dependence and missingness; calibrate using validated anchors when available.
Fix primary contrasts, multiplicity handling, uncertainty intervals, minimum
usable coverage and stopping rules before the new test data are collected.

Accept null, mixed and direction-reversed findings under those same criteria.
Publication novelty and venue suitability are separate from hypothesis confirmation.
A completed 10-comparison format check is not a power study or semantic validation.
No OSF registration or external publication has been made by this draft.
