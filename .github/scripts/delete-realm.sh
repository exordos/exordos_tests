#!/usr/bin/env bash
# Delete the realm a run took, whichever way it got it.
#
# Usage: delete-realm.sh
#
# Reads REALM_UUID and REALM_NAME from the environment, as get-realm.sh and
# its caller leave them, and the connection -- ENDPOINT, PROJECT_ID, USERNAME,
# USER_PASSWORD -- as get-realm.sh does.
#
# REALM_UUID is known once a realm was claimed or came up.  An ordered realm
# that never came up leaves only REALM_NAME, and it has no TTL, so it is looked
# up by name.  The lookup comes first: `realms delete` falls back to the local
# libvirt stands for a name the platform does not know, which fails on a
# runner and would turn a run whose claim failed red twice over.
set -uo pipefail

: "${ENDPOINT:?ENDPOINT is not set}"
: "${PROJECT_ID:?PROJECT_ID is not set}"
: "${USERNAME:?USERNAME is not set}"
: "${USER_PASSWORD:?USER_PASSWORD is not set}"

exo=(exordos --endpoint "$ENDPOINT" --project-id "$PROJECT_ID"
     --user "$USERNAME" --password "$USER_PASSWORD")

realm="${REALM_UUID:-}"
if [ -z "$realm" ] && [ -n "${REALM_NAME:-}" ]; then
    realm="$("${exo[@]}" realms show "$REALM_NAME" -o json 2>/dev/null \
        | jq -r '.[] | select(.field == "uuid") | .value' 2>/dev/null || true)"
fi

if [ -z "$realm" ]; then
    echo "No realm was taken, nothing to delete"
    exit 0
fi

"${exo[@]}" realms delete "$realm"
