#!/usr/bin/env bash
# Wait until an element reports ACTIVE.
#
# Usage: wait-for-element.sh <name> [timeout-seconds] [version-to-leave] [expected-version] [--show]
#
# `exordos ee l` talks to the core API, which 502s for seconds at a time while
# an element reconciles -- the core restarts under it.  Read the status into a
# variable so an unreadable one counts as "not ready yet": inlining the call in
# a `while [ $(...) != ACTIVE ]` condition makes a failed read look like
# success, because `[ != ACTIVE ]` on an empty string exits 2 and a `while`
# condition swallows the error, breaking out of the wait with the element still
# IN_PROGRESS.
set -uo pipefail

name="$1"
timeout="${2:-900}"
# Optional: a version the element must no longer report.  After `ee update` the
# record stays ACTIVE on the old version for a few seconds before the core
# picks the update up, so ACTIVE alone is not proof that anything happened.
stale_version="${3:-}"
expected_version="${4:-}"
# Fetch details within the same retry loop: core can reboot after its record
# first becomes ACTIVE, interrupting the extra API requests made by `show`.
show_details="${5:-}"

deadline=$((SECONDS + timeout))
status=""
version=""

while [ "$SECONDS" -lt "$deadline" ]; do
    read -r status version <<<"$(exordos ee l -o json -f "name=$name" 2>/dev/null \
        | jq -r '.[0] | "\(.status // "") \(.version // "")"' 2>/dev/null || true)"
    case "$status" in
        ACTIVE)
            if { [ -z "$stale_version" ] || [ "$version" != "$stale_version" ]; } &&
               { [ -z "$expected_version" ] || [ "$version" = "$expected_version" ]; }; then
                if [ "$show_details" = "--show" ] && ! exordos e e show "$name"; then
                    echo "Waiting for element $name details: the API did not answer"
                else
                    echo "Element $name is ACTIVE (version ${version:-unknown})"
                    exit 0
                fi
            else
                echo "Waiting for element $name version ${expected_version:-other than $stale_version} (current: ${version:-unknown})..."
            fi
            ;;
        ERROR)
            echo "Element $name went ERROR" >&2
            exordos e e show "$name" >&2 || true
            exit 1
            ;;
        *)
            echo "Waiting for element $name... (${status:-no status: the API did not answer})"
            ;;
    esac
    sleep 5
done

echo "Element $name did not become ACTIVE within ${timeout}s (last: ${status:-unknown})" >&2
exordos e e show "$name" >&2 || true
exit 1
