# Running and recovering experiments

## Stages and cost

`plan`, `prepare`, `preflight`, `demo`, `analyze`, and `status` make no paid completion requests. `prepare` downloads real source data; `preflight` makes public model/endpoint metadata GETs. Only `run --execute` sends paid completions. Every stage of that run shares a SQLite ledger and budget.

The ledger reserves a conservative UTF-8-byte-based input allowance and full output allowance at the selected endpoint's rates. It includes a 10% reservation margin. `usage.cost` replaces the reservation when reported; missing cost retains the conservative estimate. Prompt/output caps and provider price ceilings reduce exposure. These are application controls, not a billing guarantee; use a provider-side key spend cap too. Top-up/payment fees are not per-generation inference charges and are not falsely labeled exact token costs.

The run stops when another reservation cannot fit. Completed responses remain cached. The expanded pilot might stop before finishing under $45; inspect spend and yield before deciding to increase scope or budget. No model is silently replaced and no quantization restriction is removed on error.

Use one process per run directory. The process lock is supported on Linux/macOS and WSL. Distinct run directories have distinct budgets; do not launch copies expecting them to share a $45 account-wide ceiling.

## Recovery

Repeat the identical run command to reuse completed requests. Request IDs hash the full model payload, messages, routing, sampling parameters and experimental metadata. Different prompts cannot accidentally reuse old responses. Changes to config/data/code require a new run directory. Keep the original environment/commit available to resume an old run.

HTTP 429 responses retry with capped backoff. A clear HTTP 4xx rejection releases its reservation and stops. Transport errors, HTTP 5xx, malformed responses, crashes and manual cancellation can leave a `pending` reservation because the provider may have billed the request. These calls are **not automatically resent**.

Inspect:

```bash
afrijudge status --run-dir runs/pilot
```

Before clearing any pending row, check OpenRouter Activity and reconcile the charge. Copy `ledger.sqlite` and its WAL/SHM files together while the runner is stopped. If a request was definitely not billed, an operator may remove only that pending reservation:

```bash
# Replace REQUEST_ID with the exact unresolved ID printed by `status`.
python - <<'PY'
import sqlite3
db = sqlite3.connect('runs/pilot/ledger.sqlite')
request_id = input('Confirmed NOT billed request ID: ').strip()
db.execute("DELETE FROM calls WHERE id=? AND state='pending'", (request_id,))
db.commit()
PY
```

If a request was billed or its status is uncertain, retain the reservation and audit/recover the response before proceeding. Do not delete the ledger to force a rerun. Exactly-once delivery across a client crash and a remote billing service cannot be promised here.

## Updating foil labels

`foil_review.jsonl` is generated once and is not overwritten on resume. Fill `gold` with `A` or `B` only after inspecting both candidates against the source, and fill reviewer identity and supporting notes. Unreviewed rows keep `gold: null`. Do not edit candidate text or hashes in the worksheet. Run `afrijudge analyze` to regenerate statistics without new API spend. The worksheet contains an initial validation record, not a full multi-annotator agreement system.

## Reproducibility and publication

Archive the run manifest, model lock, ledger, raw judgments, pair set, labels and environment lock with results. Do not commit API keys, downloaded datasets, SQLite files, or unreviewed provider outputs. The default `.gitignore` excludes data and runs. Check source licenses, output provenance and permissions before publishing a dataset. Pin an environment with `pip freeze` for the actual run; package version ranges alone do not freeze every transitive dependency.
