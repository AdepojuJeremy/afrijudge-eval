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

The second option is implemented for hash-matched **generation, foil, and judging-stage** requests:

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
backup remains in the run directory. Unknown or unmatched requests are refused;
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


## Several providers fail together

If a timeout is followed by connection errors for multiple providers, check your
internet connection before resuming. The log alone does not prove whether the
failure was local networking, routing, or upstream service availability. A free
public metadata GET can check basic connectivity, but does not guarantee paid
inference access or provider health.

The pending inspector reconstructs request hashes for all three stages from the
frozen source data, model lock, and saved pair set. A matched hash identifies the
original payload; an unmatched request is never guessed. The recovery helper can
then retain the uncertain charge reservations and requeue those identified calls,
including AB/BA judging requests. It still refuses to act while a runner holds the
run lock, and does not change successful response records or scientific inputs.
