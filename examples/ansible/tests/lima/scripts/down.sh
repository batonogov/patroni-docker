#!/usr/bin/env bash
# =============================================================================
# Tear down the three Lima VMs and remove the generated ansible inventory.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY="$SCRIPT_DIR/../inventory.lima.yaml"

NODES=(patroni-postgresql-01 patroni-postgresql-02 patroni-postgresql-03)

for node in "${NODES[@]}"; do
  echo "==> Deleting $node ..."
  limactl delete -f "$node" || echo "    (skipped: not found)"
done

rm -f "$INVENTORY"
echo "==> Removed generated inventory.lima.yaml"
echo "==> Done."
