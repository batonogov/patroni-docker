#!/usr/bin/env bash
# =============================================================================
# Verify the Patroni cluster running inside the Lima VMs.
#
# Runs assertion commands via `limactl shell` + `docker exec` against
# patroni-postgresql-01 and checks that etcd and Patroni formed a healthy
# 3-node cluster with exactly one leader.
# =============================================================================
set -euo pipefail

NODE="patroni-postgresql-01"

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1: $2"; FAIL=$((FAIL + 1)); }

# -----------------------------------------------------------------------------
# etcd: endpoint status --cluster -w table
#   - expect 3 data rows (one per member)
#   - expect exactly 1 row with IS_LEADER == true
#
# Table columns when split by '|':
#   $1=""  $2=ENDPOINT  $3=ID  $4=VERSION  $5=DB\ SIZE  $6=IS\ LEADER  ...
# -----------------------------------------------------------------------------
echo "==> Checking etcd cluster health..."
ETCD_OUT="$(limactl shell "$NODE" -- sudo docker exec etcd \
  etcdctl --endpoints=http://localhost:2379 endpoint status --cluster -w table 2>&1 || true)"

if [[ -z "$ETCD_OUT" ]]; then
  fail "etcd-status" "no output from etcdctl"
else
  etcd_members="$(printf '%s\n' "$ETCD_OUT" | grep -c '| http' || true)"
  etcd_leaders="$(printf '%s\n' "$ETCD_OUT" | grep '| http' \
    | awk -F'|' '{ gsub(/ /, "", $6); if ($6 == "true") c++ } END { print c + 0 }')"

  if [[ "$etcd_members" -eq 3 ]]; then
    pass "etcd-members (expected 3, got $etcd_members)"
  else
    fail "etcd-members" "expected 3 members, got $etcd_members"
  fi

  if [[ "$etcd_leaders" -eq 1 ]]; then
    pass "etcd-leader (expected 1, got $etcd_leaders)"
  else
    fail "etcd-leader" "expected exactly 1 leader, got $etcd_leaders"
  fi
fi

# -----------------------------------------------------------------------------
# Patroni: patronictl list
#   - expect exactly 1 line with "| Leader " (state: running)
#   - expect exactly 2 lines with "| Replica " (state: streaming)
# -----------------------------------------------------------------------------
echo "==> Checking Patroni cluster health..."
PATRONI_OUT="$(limactl shell "$NODE" -- sudo docker exec patroni \
  patronictl -c /etc/patroni/config.yml list 2>&1 || true)"

if [[ -z "$PATRONI_OUT" ]]; then
  fail "patroni-list" "no output from patronictl"
else
  patroni_leaders="$(printf '%s\n' "$PATRONI_OUT" | grep -c '| Leader ' || true)"
  patroni_replicas="$(printf '%s\n' "$PATRONI_OUT" | grep -c '| Replica ' || true)"
  patroni_leader_running="$(printf '%s\n' "$PATRONI_OUT" \
    | grep -c '| Leader .*| running ' || true)"
  patroni_replica_streaming="$(printf '%s\n' "$PATRONI_OUT" \
    | grep -c '| Replica .*| streaming ' || true)"

  if [[ "$patroni_leaders" -eq 1 ]]; then
    pass "patroni-leader (expected 1, got $patroni_leaders)"
  else
    fail "patroni-leader" "expected exactly 1 Leader, got $patroni_leaders"
  fi

  if [[ "$patroni_replicas" -eq 2 ]]; then
    pass "patroni-replicas (expected 2, got $patroni_replicas)"
  else
    fail "patroni-replicas" "expected exactly 2 Replicas, got $patroni_replicas"
  fi

  if [[ "$patroni_leader_running" -eq 1 ]]; then
    pass "patroni-leader-state (running)"
  else
    fail "patroni-leader-state" "Leader is not in 'running' state"
  fi

  if [[ "$patroni_replica_streaming" -eq 2 ]]; then
    pass "patroni-replica-state (streaming)"
  else
    fail "patroni-replica-state" "expected 2 Replicas in 'streaming' state, got $patroni_replica_streaming"
  fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo "==> Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
