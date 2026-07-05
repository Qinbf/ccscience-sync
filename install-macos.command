#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python3 ccscience_sync.py install
python3 ccscience_sync.py status

echo
echo "Done. You can close this window."
read -r -n 1 -s -p "Press any key to close..."
echo
