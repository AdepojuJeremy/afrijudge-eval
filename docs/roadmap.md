# From pilot to full study

1. Run the existing pilot with the frozen model lock, inspect generation/parse coverage and spend, and validate the actual foil errors and native-language rubrics.
2. Restrict cross-language comparisons to matched source items and quantify selection bias from correctness-conditioned pairs. Estimate power using observed item-level variance.
3. Add validated equal-quality contrasts and minimally manipulated style variants before claiming a decomposition of family preference and shared shortcuts.
4. Add Swahili through `languages: [en, sw, ha, yo, ig]` in a new config; preserve a new run identity. Availability, data alignment, model proficiency and cost must be checked again.
5. Implement the full-study provenance, scoring-format, checklist, translate-test, and same-family-panel ablations as separate registered conditions with consistent gold validation.
6. Implement a predeclared proficiency anchor split and a held-out test split; compare the aggregation prototype to established methods with uncertainty estimates and item-grouped inference.
7. Add native-original text, multiple fluent annotators and adjudication. Do not infer native linguistic quality solely from translations or factual answer keys.
8. Freeze the confirmatory protocol, publish preregistration, and update README results only after collecting and auditing data.

The runtime is extensible, but a new condition is not automatically a valid experiment. Each addition needs an explicit estimand, provenance, validation rules, expected call volume, tests and interpretation limits.
