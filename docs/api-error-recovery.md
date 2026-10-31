# Recovering an error inside a provider response

A provider can return an error object in a successful HTTP response envelope.
The original client stores an empty invalid completion before reporting
`Provider returned an error for REQUEST_ID; inspect local ledger`. The failed
record must not be silently accepted as an ordinary invalid judgment on resume.

The paced launcher now logs the sanitized upstream error and marks new cached
error envelopes as `provider_error`. It stops again if such a record is found in
cache, requiring explicit recovery. It does not count an error envelope as a
successful HTTP result in its progress counter. Other completed records are
unchanged, as are model requests, providers, and the package code hash.

With the runner stopped, use the exact ID from the terminal error:

```bash
python scripts/recover_api_error.py --run-dir runs/budget --request-id REQUEST_ID
python scripts/recover_api_error.py --run-dir runs/budget --request-id REQUEST_ID --apply
python scripts/run_paced.py --config config/pilot_budget.yaml --data data/budget --run-dir runs/budget --execute
```

The helper refuses valid responses, content-filter outcomes, truncated responses,
and nonempty completions. It supports both the original empty invalid error
record and the newly marked `provider_error` record. Selecting an original record
requires matching the terminal's provider-error ID; ordinary invalid completions
should not be selected just because they look similar.

Recovery backs up SQLite, atomically moves that one record to an accounting entry,
and retains its full previously accounted cost. Only its request ID becomes
eligible for retry. No API calls are made by the helper. Retries can incur a new
charge, and the old amount stays counted against the same ceiling. Accounting
history remains in SQLite and `uncertain_charges.jsonl`. The completed-outcome
count may decrease by one until the request is retried, because the old error is
no longer counted as a completed outcome.

Run `afrijudge status` before resuming. If pending reservations remain **after**
the runner has stopped, they need separate diagnosis; this helper handles the
specific cached error record, not arbitrary in-flight or ambiguous requests.
