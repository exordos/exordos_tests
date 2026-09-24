#!/usr/bin/env bash
# Overbook the realm's hypervisor, so an element's nodes fit on a warm realm.
#
# Usage: overbook-hypervisor.sh [cores-ratio] [ram-ratio]
#
# Talks to whichever realm the CLI is pointed at.  A warm realm is sized for
# the pool's defaults, and a control plane plus data plane nodes do not fit on
# it one to one; the runner-local tests overbooked their hypervisor the same
# way.  The realm's core can take longer than the CLI's ten second timeout to
# answer, so each call is retried a few times.
set -uo pipefail

cores_ratio="${1:-10.0}"
ram_ratio="${2:-10.0}"

retry() {
    for _ in 1 2 3 4 5; do
        "$@" && return 0
        echo "The realm did not answer, trying again..." >&2
        sleep 10
    done
    return 1
}

uuid=""
for _ in 1 2 3 4 5; do
    uuid="$(exordos c h l -o json 2>/dev/null | jq -r '.[0].uuid // ""' 2>/dev/null)"
    [ -n "$uuid" ] && break
    sleep 10
done
if [ -z "$uuid" ]; then
    echo "The realm reports no hypervisor to overbook" >&2
    exit 1
fi

retry exordos compute hypervisors update "$uuid" \
    --cores-ratio "$cores_ratio" --ram-ratio "$ram_ratio" || exit 1
