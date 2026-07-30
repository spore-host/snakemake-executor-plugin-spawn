#!/usr/bin/env bash
# composition-test.sh — proves REAL `snakemake --executor spawn` drives the spawn
# CLI end-to-end, against the Substrate AWS emulator (no real AWS, no workload
# execution, no cost).
#
# Exercises the honest seam:
#   real `snakemake --executor spawn` → SpawnExecutor.run_job → real
#   `spawn task run` (real RunInstances + real `aws s3` staging, all vs. Substrate)
#   → check_active_jobs polls the completion record → exit code → Snakemake marks
#   the job succeeded/failed.
#
# Substrate (v0.75.0+) serves the completion record as a seedable, clock-aware
# outcome (scttfrdmn/substrate#360): unseeded ⇒ nominal exit 0/completed (happy
# path needs NO seed); POST /v1/spawn/task-completion with a nonzero exit_code
# drives the failure path. Substrate does NOT execute the job, so this uses a
# NO-OUTPUT rule (tests/composition/Snakefile) — Snakemake gates a run on its
# declared `output:` existing in storage (wait_for_files), which needs real
# execution; a rule with no output has no such gate. See #3.
#
# Requires on PATH / in env (the CI job provides): `snakemake` (with the spawn
# executor plugin + snakemake-storage-plugin-s3 installed), `spawn`, `aws`;
# AWS_ENDPOINT_URL → the Substrate server. Exits nonzero on any assertion miss.
set -euo pipefail

: "${AWS_ENDPOINT_URL:?set to the Substrate server, e.g. http://localhost:4566}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"
export SPAWN_REGION="$AWS_REGION"
# Blank the named-profile defaults so the SDK uses the static test creds +
# AWS_ENDPOINT_URL (→ Substrate), not a real named profile.
export SPAWN_INFRA_PROFILE=""
export SPAWN_COMPUTE_PROFILE=""

BUCKET="snakemake-spawn-ci"
STORAGE_PREFIX="s3://${BUCKET}/runs"

HERE="$(cd "$(dirname "$0")" && pwd)"
# Run from a scratch dir with the Snakefile copied in: Snakemake uploads a source
# archive of everything under the working dir and warns/misbehaves if the
# Snakefile lives outside it, so keep cwd == where the Snakefile is.
WORKDIR="$(mktemp -d)"
cp "$HERE/Snakefile" "$WORKDIR/Snakefile"
ENDPOINT="$AWS_ENDPOINT_URL"

fail() { echo "COMPOSITION TEST FAILED: $*" >&2; exit 1; }

echo "spawn=$(command -v spawn)  snakemake=$(command -v snakemake)  endpoint=$ENDPOINT"

# spawn stages uploads under the workdir base before `spawn task run` (spawn
# creates the results bucket itself, but the workdir base bucket must exist).
aws --endpoint-url "$ENDPOINT" s3 mb "s3://${BUCKET}" 2>/dev/null || true

# The single job's task id (smk-<rulename>-<attempt>) is deterministic.
TASK_ID="smk-noout-1"

# Robust to Substrate state from an earlier run in the same server: clear any
# seeded completion so TEST 1 is genuinely unseeded (⇒ nominal exit 0).
curl -fsS -X DELETE "$ENDPOINT/v1/spawn/task-completion?taskId=${TASK_ID}" >/dev/null 2>&1 || true

run_snakemake() {  # $1 = log file → prints snakemake's exit code
    local log="$1"
    ( cd "$WORKDIR" && snakemake \
        --snakefile Snakefile \
        --executor spawn \
        --default-storage-provider s3 \
        --default-storage-prefix "$STORAGE_PREFIX" \
        --storage-s3-endpoint-url "$ENDPOINT" \
        --spawn-region "$AWS_REGION" --spawn-ttl 20m \
        --spawn-workdir-s3 "$STORAGE_PREFIX" \
        --jobs 1 noout ) > "$log" 2>&1 && echo 0 || echo $?
}

echo "=== TEST 1: happy path — unseeded completion ⇒ nominal success ==="
RC1="$(run_snakemake "$WORKDIR/t1.log")"
[ "$RC1" = 0 ] || { tail -30 "$WORKDIR/t1.log"; fail "TEST 1: snakemake exited $RC1 on the happy path"; }
grep -qF "dispatching ${TASK_ID} via \`spawn task run\`" "$WORKDIR/t1.log" \
    || fail "TEST 1: executor never dispatched via spawn task run:
$(tail -20 "$WORKDIR/t1.log")"
grep -qF "1 of 1 steps (100%) done" "$WORKDIR/t1.log" \
    || fail "TEST 1: snakemake did not report the job done:
$(tail -20 "$WORKDIR/t1.log")"
echo "TEST 1 PASS: real snakemake run succeeded; dispatched ${TASK_ID}, completion resolved to exit 0"

echo "=== TEST 2: failure path — seed ${TASK_ID} to exit 7, expect snakemake to fail ==="
curl -fsS -X POST "$ENDPOINT/v1/spawn/task-completion" \
    -H 'content-type: application/json' \
    -d "{\"task_id\":\"${TASK_ID}\",\"exit_code\":7,\"state\":\"failed\",\"started_at\":\"2026-01-01T00:00:00Z\",\"ended_at\":\"2026-01-01T00:00:01Z\"}" \
    >/dev/null || fail "TEST 2: could not seed the failure completion"
RC2="$(run_snakemake "$WORKDIR/t2.log")"
[ "$RC2" != 0 ] || { tail -30 "$WORKDIR/t2.log"; fail "TEST 2: snakemake SUCCEEDED despite a seeded FAILED completion"; }
grep -qF "exited with code 7" "$WORKDIR/t2.log" \
    || fail "TEST 2: snakemake failed but not with the seeded exit 7:
$(tail -20 "$WORKDIR/t2.log")"
echo "TEST 2 PASS: seeded exit 7 → snakemake reports the job 'exited with code 7' (executor surfaced the code)"

# Leave Substrate clean for any re-run in the same server.
curl -fsS -X DELETE "$ENDPOINT/v1/spawn/task-completion?taskId=${TASK_ID}" >/dev/null 2>&1 || true

echo "=== COMPOSITION VERIFIED: real snakemake --executor spawn ↔ spawn ↔ Substrate (dispatch + completion + exit-code) ==="
