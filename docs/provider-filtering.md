# Provider-filtered requests are missing responses

An Azure HTTP 400 with a structured `content_filter` code is a provider policy
rejection. It is distinct from a rate limit, invalid API parameter, wrong answer,
or judgment tie. Repeating it unchanged can keep stopping an otherwise resumable run.

The paced launcher records this specific outcome as `status: provider_filtered`,
`http_status: 400`, `finish_reason: content_filter`, and empty content. It records
no generated answer and no invented provider generation ID. The actual HTTP
rejection remains in the transport event log. Other HTTP 400 errors still stop.

This is a local outcome-classification adapter outside the experiment package.
It does **not** change request text, model, provider, output format, or safety
settings. It does not transform the rejection into a successful model response.
The missing outcome is cached under its original payload hash so it is not
resubmitted repeatedly. The unchanged pipeline excludes it from candidate pairing
and leaves generation correctness undefined. A filtered judge response remains an
invalid/missing verdict, never a quality tie or a correct decision.

The original conservative reservation is retained as a cost estimate because no
actual usage charge is known from this rejection. Do not describe this estimate
as measured billing. This keeps budget accounting conservative.

`provider_filter_summary.json` lists filtered request IDs and source-item metadata,
with counts by stage, model, and available language. It is refreshed when the paced
launcher exits and attached to an existing final `report.json`. Keep the separate
summary when rerunning analysis through another CLI, which may regenerate the
report without this addendum.

Report provider-filter missingness and its selection effects in the study. The
existing generation diagnostics include these in the broad unparseable-generation
count; the separate filter summary identifies the specific reason. Do not describe
all cached request outcomes as valid candidate answers. Do not remove whole source
items or silently change providers to obtain unfiltered answers.

For the existing interrupted pilot, with the runner stopped:

```bash
git pull --ff-only
python scripts/run_paced.py --config config/pilot_budget.yaml --data data/budget --run-dir runs/budget --execute
```

The update preserves scientific package hashes and the existing response cache.
If another error stops the run, inspect its specific status and message rather
than classifying every rejection as filtering.
