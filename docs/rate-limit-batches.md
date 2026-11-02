# Automatic bounded rate-limit recovery

The paced launcher now allows up to eight batches of the existing client's four
HTTP-429 attempts per request. After a batch exhausts, it waits 180 additional
seconds and retries the identical request. Provider Retry-After handling and the
existing 60/120/240/480-second pacing cooldowns remain active. Waiting can therefore
be substantially longer than three minutes.

Only the exact `Rate limit exhausted; retry this run later` failure is eligible.
The client has released the rejected batch's reservation before this outer retry.
Each new batch must reserve budget again through the original ledger. Transport
uncertainty, embedded provider errors, ordinary HTTP rejections, and budget failures
still stop and retain their existing recovery rules. No provider or prompt is changed.

Defaults are bounded: eight batches mean at most 32 HTTP attempts for one persistently
rate-limited request, not infinite retries. Persistent capacity/quota problems can
still stop the run. `--rate-limit-cycles 1` restores the previous behavior. The
maximum accepted cycle count is 16. Operational settings and retry events are logged
in `transport_events.jsonl`; these do not change scientific package hashes or caches.

With the runner stopped and no unresolved reservations:

```bash
git pull --ff-only
python scripts/run_paced.py --interval-seconds 12 --rate-limit-cycles 8 --config config/pilot_budget.yaml --data data/budget --run-dir runs/budget --execute
```

This increases resilience, not provider availability. Do not treat repeated HTTP 429s
as evidence about model quality or discard the affected family's judgments selectively.
