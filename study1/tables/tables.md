# Study 1 — reported aggregate tables

## Table 1. Anchor proficiency
| Language | Stable correct | Assigned votes | Stable correct rate |
|---|---:|---:|---:|
| English | 86 | 90 | 95.56% |
| Hausa | 73 | 90 | 81.11% |
| Yoruba | 63 | 90 | 70.00% |
| Igbo | 64 | 90 | 71.11% |

Per-judge instability and proficiency values are not recoverable from the transcript.

## Table 2. Held-out aggregation (360 comparisons)
| Rule | Correct | Wrong | Undecided | Correct / assigned | Coverage | Correct / decided |
|---|---:|---:|---:|---:|---:|---:|
| Majority-6 | 311 | 0 | 49 | 86.39% | 86.39% | 100.00% |
| Majority-5 | 331 | 0 | 29 | 91.94% | 91.94% | 100.00% |
| Anchor Top-1 | 345 | 2 | 13 | 95.83% | 96.39% | 99.42% |
| Anchor Top-3 | 347 | 1 | 12 | 96.39% | 96.67% | 99.71% |
| Accuracy-only | 343 | 0 | 17 | 95.28% | 95.28% | 100.00% |
| LRL-CARE | 343 | 0 | 17 | 95.28% | 95.28% | 100.00% |
| Anchor-initialized Dawid–Skene | 356 | 3 | 1 | 98.89% | 99.72% | 99.16% |

Reported source-cluster bootstrap gains (percentage points relative to Majority-6): LRL-CARE +8.89 [4.72, 13.89]; Top-3 +10.00 [5.56, 15.56]. Earlier summary gives LRL-CARE upper bound 13.6; confirm against archived output before submission. Other intervals not present in the supplied record.

## Table 3. Own-family selection gap
| Language | Prompt provenance | Gap (pp) |
|---|---|---:|
| English | Original | 11.81 |
| Hausa | Original | 3.82 |
| Hausa | Calqued | 3.47 |
| Yoruba | Original | 6.25 |
| Yoruba | Calqued | 9.38 |
| Igbo | Original | 10.42 |
| Igbo | Calqued | 1.39 |

English gap: 95% CI [3.82, 20.14]. Paired 12-topic bootstrap contrasts:

| Contrast | Estimate (pp) | 95% interval |
|---|---:|---:|
| Hausa: original − English | -8.0 | [-16.7, 0.3] |
| Yoruba: original − English | -5.6 | [-17.0, 5.2] |
| Igbo: original − English | -1.4 | [-10.4, 6.9] |
| Pooled originals − English | -5.0 | [-13.8, 3.4] |
| Hausa: calqued − original | -0.3 | [-6.6, 6.3] |
| Yoruba: calqued − original | 3.1 | [-10.1, 16.0] |
| Igbo: calqued − original | -9.0 | [-18.1, -0.3] |

Decisive-only English gap: 0 pp, on 20/72 candidate comparisons. All other decisive-only cell estimates are unavailable here. Intervals are individual, not multiplicity-adjusted.
