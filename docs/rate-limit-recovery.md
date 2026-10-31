# Resuming a rate-limited existing run

Repeated HTTP 429 responses can reflect provider capacity or account/provider quotas. Slower pacing may help; it cannot cure a depleted quota or unavailable route. Keep successful request records and inspect the provider's error message rather than repeatedly restarting at the same speed.

The standalone `scripts/run_paced.py` launcher changes HTTP scheduling only. It serializes completion POSTs, adds a six-second gap after each response, honors numeric or HTTP-date Retry-After headers, and applies 60/120/240/480-second cooldowns after repeated 429s from a model. The original client's bounded retry count remains in force. It never retries ambiguous transport errors or changes the model, provider, prompt, request ID, dataset, or budget.

The launcher lives outside `src/afrijudge`; this update does not change the package code hash saved in an existing run. Operational events are appended to `runs/budget/transport_events.jsonl`, including the launcher hash, pacing policy, and sanitized provider error messages. Cached calls are not delayed because they do not make HTTP requests. A 10-requests-per-minute ceiling plus request latency can make a large run take many hours.

This additive update is safe for a run created with the cost-estimator version (`8f4159b`). Check out that version if your run uses an older code hash before introducing this launcher separately. In general, do not pull arbitrary package-code updates into an unfinished run.

With the old runner stopped at the shell prompt:

```bash
git pull --ff-only
python scripts/run_paced.py --config config/pilot_budget.yaml --data data/budget --run-dir runs/budget --execute
```

Keep the existing environment key. If the next error indicates exhausted quota, credits, or a persistent provider outage, stop retrying and inspect the provider/account limits. Do not delete the ledger or switch the frozen provider in place. Share the sanitized model/error line for diagnosis. A separate fresh-run design is needed if changing models or providers.
