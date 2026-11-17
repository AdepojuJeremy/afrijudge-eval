# AfriJudge — Study 1

**Status:** reconstructed working manuscript and aggregate publication assets. This directory is distinct from Study 2.

- [Manuscript](manuscript/manuscript.md)
- [Tables 1–3](tables/tables.md) · [LaTeX source](tables/tables.tex) · [standalone LaTeX wrapper](tables/tables-standalone.tex)
- [Figure 1: coverage](figures/figure-1-coverage.svg)
- [Figure 2: anchor proficiency and Top/Bottom-3](figures/figure-2-proficiency.svg)
- [Figure 3: family preference](figures/figure-3-family-preference.svg)
- [Reported results (JSON)](results/reported-aggregates.json) · CSV: [anchors](results/anchors.csv), [aggregation](results/aggregation.csv), [H2 cells](results/h2_cells.csv), [H2 contrasts](results/h2_contrasts.csv)
- [Reproducibility and missing artifacts](REPRODUCIBILITY.md)

## Regenerate summary figures

From the repository root, using Node.js 18 or later (no dependencies or API calls):

```sh
node study1/analysis/render-figures.mjs
```

The script validates basic counts and regenerates the three SVGs from the summary JSON. This is not reproduction of the original item-level analysis.

## Main results

Majority-6: 311/360 correct, 0 wrong, 49 undecided. Anchor Top-1: 345/360 correct. LRL-CARE and competence-only weighting: 343/360 correct, 0 wrong. Top-3: 347/360 correct, 1 wrong. Dawid–Skene: 356/360 correct, 3 wrong. The shared-wrong-consensus prediction was not supported; coverage-driven underperformance was observed. H2 attenuation has directional evidence, not a consistent calqued rebound.

No raw provider payloads, private reviewer records, credentials, or dataset text are committed in this reconstruction.
