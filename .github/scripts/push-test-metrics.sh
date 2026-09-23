#!/usr/bin/env bash
# Push the result of the current CI job to VictoriaMetrics (exordos
# observability), where the "Exordos Tests" Grafana dashboard reads it.
#
# Usage: push-test-metrics.sh <job-status>
#
#   job-status  ${{ job.status }}: success, failure or cancelled
#
# Environment:
#   VM_IMPORT_URL   VictoriaMetrics Prometheus-import endpoint, e.g.
#                   http://<victoria-host>:8428/api/v1/import/prometheus
#                   (the vmauth write path, open without credentials).
#                   Unset -> nothing is pushed.
#   VM_IMPORT_USER, VM_IMPORT_PASSWORD
#                   Optional Basic Auth, for a write path behind a proxy.
#   ELEMENT_NAME, BASE_CORE_VERSION
#                   Copied into labels when the workflow sets them.
#   GH_TOKEN        Token for the GitHub API (needs `actions: read`), used
#                   for the job duration and per-step results.  Without it
#                   only the job result is pushed.
#
# Metrics (one sample per job run):
#   exordos_tests_run_success{...}            1 = success, 0 = failure/cancelled
#   exordos_tests_run_duration_seconds{...}   job wall time up to this step
#   exordos_tests_run_info{..., result, run_id, run_attempt, sha} 1
#   exordos_tests_step_success{..., step}     1/0 per finished, non-skipped step
#   exordos_tests_step_duration_seconds{..., step}
#
# Reporting must never fail the job: every error is logged and the script
# exits 0.
set -uo pipefail

job_status="${1:-unknown}"

if [ -z "${VM_IMPORT_URL:-}" ]; then
    echo "VM_IMPORT_URL is not set, skipping metrics push"
    exit 0
fi

# Prometheus text format label value escaping: \ " and newline.
esc() {
    local v="$1"
    v="${v//\\/\\\\}"
    v="${v//\"/\\\"}"
    v="${v//$'\n'/\\n}"
    printf '%s' "$v"
}

labels="repository=\"$(esc "$GITHUB_REPOSITORY")\""
labels+=",workflow=\"$(esc "$GITHUB_WORKFLOW")\""
labels+=",job=\"$(esc "$GITHUB_JOB")\""
labels+=",branch=\"$(esc "$GITHUB_REF_NAME")\""
labels+=",event=\"$(esc "$GITHUB_EVENT_NAME")\""
labels+=",element=\"$(esc "${ELEMENT_NAME:-}")\""
labels+=",base_version=\"$(esc "${BASE_CORE_VERSION:-}")\""

success=0
[ "$job_status" = "success" ] && success=1

payload="exordos_tests_run_success{$labels} $success
exordos_tests_run_info{$labels,result=\"$(esc "$job_status")\",run_id=\"$GITHUB_RUN_ID\",run_attempt=\"$GITHUB_RUN_ATTEMPT\",sha=\"$GITHUB_SHA\"} 1
"

# Job duration and per-step results come from the GitHub API.  The job is
# matched by name: jobs here have no `name:`, so the display name is the
# job id.  The step running this script is still in progress and is left
# out (it has no conclusion yet).
jobs_json=""
if [ -n "${GH_TOKEN:-}" ]; then
    jobs_json="$(gh api \
        "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/attempts/$GITHUB_RUN_ATTEMPT/jobs" \
        2>/dev/null)" || { echo "GitHub API unavailable, pushing the job result only"; jobs_json=""; }
fi

if [ -n "$jobs_json" ]; then
    payload+="$(jq -r --arg job "$GITHUB_JOB" --arg labels "$labels" '
        def esc: gsub("\\\\"; "\\\\") | gsub("\""; "\\\"") | gsub("\n"; "\\n");
        def secs: sub("\\.[0-9]+"; "") | fromdateiso8601;
        (.jobs[] | select(.name == $job)) as $j
        | (
            "exordos_tests_run_duration_seconds{\($labels)} \(now - ($j.started_at | secs) | floor)",
            ($j.steps[]
              | select(.conclusion == "success" or .conclusion == "failure")
              | "step=\"\(.name | esc)\"" as $step
              | "exordos_tests_step_success{\($labels),\($step)} \(if .conclusion == "success" then 1 else 0 end)",
                "exordos_tests_step_duration_seconds{\($labels),\($step)} \((.completed_at | secs) - (.started_at | secs))")
          )
    ' <<<"$jobs_json" 2>/dev/null)" || echo "Could not parse the GitHub API response, pushing the job result only"
    payload+=$'\n'
fi

echo "Pushing to VictoriaMetrics:"
echo "$payload"

auth=()
if [ -n "${VM_IMPORT_USER:-}" ]; then
    auth=(-u "$VM_IMPORT_USER:${VM_IMPORT_PASSWORD:-}")
fi

for i in 1 2 3; do
    if curl -fsS --max-time 20 "${auth[@]}" --data-binary "$payload" "$VM_IMPORT_URL"; then
        echo "Metrics pushed"
        exit 0
    fi
    echo "Push failed (attempt $i/3)"
    sleep 5
done

echo "Could not push metrics to VictoriaMetrics" >&2
exit 0
