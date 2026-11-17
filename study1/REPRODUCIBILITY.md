# Reproducibility status

## Available
The source is the user-supplied conversation export, LLM Judge Research Focus (2).md, particularly its completed unified-study report and later offline-analysis summaries (approximately lines 12470–12840). The original study's analysis was reported as replaying 8,064 calls; that replay has **not** been independently rerun in this commit. Summary figures are regenerated from documented aggregate values; no missing points are imputed. The English/LRL pooled counts are arithmetic derivations from reported totals. The 60 anchor comparisons, 360 H1 test comparisons and 252 H2 comparisons sum to 672, consistent with six judges and two orders.

## Required before archival release
Restore the exact previously generated v4 ZIP, manuscript PDF and source, full Figure 1 by language/domain/condition, full Figure 2 scatter across 20 sub-panels per language, all seven H2 cell intervals and decisive-only coverage, LaTeX tables with full intervals, item-level analysis scripts and outputs. In particular retrieve the frozen run's report.json, pairs.json, requests.jsonl, anchor and H2 review records, number-word sign-off, locked model/configuration manifest and prompt version identifiers. Audit their publication rights and redact secrets before committing. Raw data and private reviewer records should only be published if authorized.

Recompute order reconciliation, 4,000-draw source/topic and anchor bootstrap, categorical (three/five-outcome) dependence, effective jury size per language and aggregation comparisons against the original scripts. Check the conflicting LRL-CARE upper interval (13.6 vs 13.89). Confirm exact authorship and bibliography. Do not present the aggregate renderer as raw-data replication.

No changes to experiment implementation or Study 2 branches are necessary for this summary release.
