#!/usr/bin/env bash
# Wait until elements of one version are AVAILABLE in the realm's catalog.
#
# Usage: wait-for-repo-version.sh <version> <timeout-seconds> <element>...
#
# Talks to whichever realm the CLI is pointed at.  The realm's repositories
# sync lazily, so a version pushed moments ago is not in its catalog until a
# refresh picks it up; refresh on every round, as the push may still be
# reaching the repo's mirror.
set -uo pipefail

version="$1"
timeout="$2"
shift 2
pending="$*"

deadline=$((SECONDS + timeout))
while [ "$SECONDS" -lt "$deadline" ]; do
    exordos repo refresh > /dev/null || true
    still=""
    for name in $pending; do
        status="$(exordos repo e l --dev -f "name=$name" -o json 2>/dev/null \
            | jq -r --arg v "$version" \
                '[.[] | select(.version == $v) | .status] | first // ""' \
                2>/dev/null || true)"
        if [ "$status" = "AVAILABLE" ]; then
            echo "$name $version is available"
        else
            echo "Waiting for $name $version... (${status:-not listed})"
            still="$still $name"
        fi
    done
    pending="${still# }"
    if [ -z "$pending" ]; then
        exit 0
    fi
    sleep 10
done

echo "Not available within ${timeout}s: $pending $version" >&2
exordos repo l >&2 || true
for name in $pending; do
    exordos repo e l --dev -f "name=$name" >&2 || true
done
exit 1
