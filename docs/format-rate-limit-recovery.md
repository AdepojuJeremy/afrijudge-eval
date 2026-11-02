# Format diagnostic: rate-limit recovery

The first v2 diagnostic used the ordinary client's four short HTTP-429 retries.
A `Rate limit exhausted; retry this run later` failure releases that rejected
request's reservation. Successfully completed requests remain cached and the
finally block exports them to the diagnostic's `requests.jsonl`. The error alone
does not justify running a pending-request requeue script.

A scheduling-only launcher uses the existing, tested pilot HTTP pacer: one POST
at a time, 60/120/240/480-second cooldowns for rate limits (respecting larger
Retry-After instructions), and up to eight bounded retry batches with a
180-second inter-batch wait. Persistent provider limits can still exhaust the
retries; no cooldown guarantees service availability. Progress/model diagnostics
are printed. This does not change providers or model requests.

```bash
git pull --ff-only
caffeinate -i python scripts/run_format_paced.py \
  --source-run runs/budget --run-dir runs/format-v2 \
  --max-spend-usd 1 --execute
```

Keep the same run directory and scientific config. The launcher is outside
`src/afrijudge`, preserving the diagnostic's package code hash. Its selected
pairs, model lock, payloads, cache and ledger remain the same. Cached successful
responses are reused; filters, if encountered, are recorded as missing responses.
The $1 limit is a stopping ceiling, not a completion cost or guaranteed provider
invoice bound. Ambiguous transports, server errors, invalid cached provider
responses and budget exhaustion remain fatal; do not blindly requeue or replay
those failures. If the run reports unresolved reservations, inspect first.

Omit `--execute` for an offline plan. Logs and the report are written in
`runs/format-v2`, never the original pilot. The report remains
`runs/format-v2/format_report.json`. No paid calls were used to test this patch.
