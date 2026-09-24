#!/usr/bin/env bash
# Check that a realm takes an ssh key: log in to it as ubuntu with the key.
#
# Usage: check-realm-ssh.sh <realm-uuid> <private-key> [timeout-seconds]
#
# The connection to the platform comes from the environment -- ENDPOINT,
# PROJECT_ID, USERNAME, USER_PASSWORD -- as it does for get-realm.sh.
#
# A claimed realm booted before the key was supplied: the ecosystem delivers it
# afterwards as an ssh_key secret in the realm's own core, and the realm's agent
# writes it to authorized_keys, so it can take a while to be accepted.  The
# check retries until the timeout and reports how long the key took.
#
# When the key is never accepted and REALM_CORE_URL and ADMIN_PASSWORD are set,
# it prints what the delivery left in the realm's own core -- its nodes and its
# ssh_key secrets -- and one verbose ssh attempt, which tells whether the key
# was never written, written for the wrong node, or written and not applied.
set -uo pipefail

realm="$1"
key="$2"
timeout="${3:-600}"

: "${ENDPOINT:?ENDPOINT is not set}"
: "${PROJECT_ID:?PROJECT_ID is not set}"
: "${USERNAME:?USERNAME is not set}"
: "${USER_PASSWORD:?USER_PASSWORD is not set}"

field() {
    jq -r --arg f "$1" '.[] | select(.field == $f) | .value'
}

ssh_info="$(exordos --endpoint "$ENDPOINT" --project-id "$PROJECT_ID" \
    --user "$USERNAME" --password "$USER_PASSWORD" \
    realms ssh_connection "$realm" -o json)"
ssh_host="$(echo "$ssh_info" | field host)"
ssh_port="$(echo "$ssh_info" | field port)"
if [ -z "$ssh_host" ] || [ -z "$ssh_port" ]; then
    echo "Realm $realm reports no ssh connection" >&2
    exit 1
fi

ssh_opts=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o BatchMode=yes -o ConnectTimeout=10 -i "$key" -p "$ssh_port")

# Stop on a deadline, not a count, so the diagnostics below still run inside a
# caller's step timeout however long each attempt takes.
start=$SECONDS
i=0
while [ $((SECONDS - start)) -lt "$timeout" ]; do
    i=$((i + 1))
    if ssh "${ssh_opts[@]}" "ubuntu@$ssh_host" true; then
        echo "Realm $realm takes the key at $ssh_host:$ssh_port" \
             "after $((SECONDS - start))s"
        exit 0
    fi
    echo "Waiting for ssh to realm $realm... (attempt $i, $((SECONDS - start))s)"
    sleep 10
done

echo "Realm $realm did not take the key within ${timeout}s" >&2

if [ -n "${REALM_CORE_URL:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
    child=(exordos --endpoint "$REALM_CORE_URL" --user admin
           --password "$ADMIN_PASSWORD")
    echo "::group::Nodes of the realm's own core"
    "${child[@]}" compute nodes list || true
    echo "::endgroup::"
    echo "::group::ssh_key secrets in the realm's own core"
    "${child[@]}" secret ssh_keys list || true
    echo "::endgroup::"
fi
echo "::group::Verbose ssh attempt"
ssh -v "${ssh_opts[@]}" "ubuntu@$ssh_host" true 2>&1 | tail -30 || true
echo "::endgroup::"
exit 1
