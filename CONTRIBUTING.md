# Contributing

Install with `python -m pip install -e '.[dev]'`. Run `ruff check .`, `ruff format --check .`, and `pytest -q` before submitting changes. CI uses mocks and synthetic fixtures and never needs an API key.

Keep prompts and experimental conditions explicit. Never silently replace source data, model IDs, provider precision, labels, or missing values. Add regression tests for numerical changes, billing/recovery changes, parsing rules, and intervention construction. Keep source items grouped across splits and bootstrap samples.

Describe protocol changes in the pull request. Changes to code/config/data require a new run directory. Do not mix paid completion tests into ordinary CI. Never commit `.env`, API keys, run ledgers, or downloaded benchmark data.
