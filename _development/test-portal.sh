#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.local/portal-testing/browsers"
local_browser_libraries="$PWD/.local/portal-testing/system-libs/usr/lib/x86_64-linux-gnu"
if [[ -d "$local_browser_libraries" ]]; then
  export LD_LIBRARY_PATH="$local_browser_libraries${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
exec node tests/publications.browser.mjs
