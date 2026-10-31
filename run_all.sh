#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# No paid call occurs without the explicit --execute argument.
exec afrijudge run "$@"
