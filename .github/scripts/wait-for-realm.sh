#!/usr/bin/env bash
# Wait until a realm reports ACTIVE.
#
# Usage: wait-for-realm.sh <name-or-uuid> [timeout-seconds]
#
# The connection comes from the environment -- ENDPOINT, PROJECT_ID, USERNAME,
# USER_PASSWORD -- which also keeps the password out of the step's `set -x`
# trace.
#
# Same shape as wait-for-element.sh, and for the same reason: read the status
# into a variable so an unanswered API counts as "not ready yet".  Inlining the
# call in a `while [ $(...) != ACTIVE ]` condition makes a failed read look like
# success, because `[ != ACTIVE ]` on an empty string exits 2 and a `while`
# condition swallows the error, breaking out of the wait with the realm still
# PROVISIONING.
set -uo pipefail

name="$1"
timeout="${2:-900}"

: "${ENDPOINT:?ENDPOINT is not set}"
: "${PROJECT_ID:?PROJECT_ID is not set}"
: "${USERNAME:?USERNAME is not set}"
: "${USER_PASSWORD:?USER_PASSWORD is not set}"

exo=(exordos --endpoint "$ENDPOINT" --project-id "$PROJECT_ID"
     --user "$USERNAME" --password "$USER_PASSWORD")

deadline=$((SECONDS + timeout))
status=""

while [ "$SECONDS" -lt "$deadline" ]; do
    status="$("${exo[@]}" realms show "$name" -o json 2>/dev/null \
        | jq -r '.[] | select(.field == "status") | .value' 2>/dev/null || true)"
    case "$status" in
        ACTIVE)
            echo "Realm $name is ACTIVE"
            exit 0
            ;;
        # ERROR is terminal; a realm that is already DELETING will never reach
        # ACTIVE either, so do not sit out the whole timeout on it.
        ERROR|DELETING)
            echo "Realm $name went $status" >&2
            "${exo[@]}" realms show "$name" >&2 || true
            exit 1
            ;;
    esac
    echo "Waiting for realm $name... (${status:-no status: the API did not answer})"
    sleep 5
done

echo "Realm $name did not become ACTIVE within ${timeout}s (last: ${status:-unknown})" >&2
"${exo[@]}" realms show "$name" >&2 || true
exit 1
