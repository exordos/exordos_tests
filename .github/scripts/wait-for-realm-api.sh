#!/usr/bin/env bash
# Wait until a realm's own core answers, and find how it is reached.
#
# Usage: wait-for-realm-api.sh <realm-domain> [timeout-seconds]
#
# ADMIN_PASSWORD comes from the environment, as get-realm.sh leaves it, so it
# stays out of the command line.
#
# The per-realm ingress forwards 80 and 443 to the nested core, and a realm
# may be served on either, so both are tried.  The one that answers is printed
# to stdout as REALM_CORE_URL=<url>, ready to append to $GITHUB_ENV.
set -uo pipefail

domain="$1"
timeout="${2:-300}"

: "${ADMIN_PASSWORD:?ADMIN_PASSWORD is not set}"

deadline=$((SECONDS + timeout))
while [ "$SECONDS" -lt "$deadline" ]; do
    for scheme in https http; do
        url="$scheme://$domain/api/core"
        if exordos --endpoint "$url" --user admin --password "$ADMIN_PASSWORD" \
                ready_api > /dev/null 2>&1; then
            echo "The realm's core answered at $url" >&2
            echo "REALM_CORE_URL=$url"
            exit 0
        fi
    done
    echo "Waiting for the realm's core api at $domain..." >&2
    sleep 5
done

echo "The realm's core answered on neither https nor http at $domain within" \
     "${timeout}s. The per-realm ingress forwards 80 and 443 to the nested" \
     "core, so check the realm's border and the shared load balancer." >&2
exit 1
