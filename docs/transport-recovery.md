# Continue after an ambiguous transport failure

A transport failure does not establish whether a request was processed or billed.
Successful responses stay cached, but unresolved reservations intentionally block
the next run. Never delete the ledger to bypass that check.

There are two valid recovery approaches:

1. Reconcile against provider records and recover the response or establish that
   the request was not billed.
2. Conservatively retain the full uncertain reservation as an accounting entry,
   then deliberately retry the missing response. This may pay for the original
   attempt and the retry, but keeps both within the same budget accounting.

The second option is implemented for identified **generation-stage** requests:

```bash
python scripts/requeue_pending.py --run-dir runs/budget --data data/budget
# Review the pending requests. The next command changes the ledger, not the API:
python scripts/requeue_pending.py --run-dir runs/budget --data data/budget --apply
python scripts/run_paced.py --config config/pilot_budget.yaml --data data/budget --run-dir runs/budget --execute
```

The helper takes the run lock, checks input and model identities, backs up SQLite
including committed WAL contents, and moves pending rows atomically to
`accounting` entries with new IDs. Amounts are unchanged. `Ledger.spent` sums all
states, so uncertain reservations remain counted against the original ceiling.
Only the missing request IDs become eligible for retry. Successful responses and
their hashes are untouched; accounting entries are not candidate responses and
are not included in the completed-request count.

Billing uncertainty is recorded in SQLite and `uncertain_charges.jsonl`. These
are retained charge estimates, not assertions of actual provider billing. The
backup remains in the run directory. Unknown/non-generation requests are refused;
they require a supported identification/reconciliation path first. The current
helper does not recover missing provider responses from Activity.

The paced launcher now uses a 300-second HTTP timeout by default, configurable
with `--timeout-seconds`, and logs the transport exception class and affected model.
This is a scheduling/transport change outside the experiment package, preserving
the old run's code hash and request payloads. It may help slow responses, but cannot
prevent connection outages. Request-interval pacing and provider locks are retained.

No retry is called free. If a real charge exceeded its conservative reservation,
provider billing remains authoritative; use a provider-side spend cap and reconcile
the final bill. Interrupted and retried calls should be disclosed with the run logs.
