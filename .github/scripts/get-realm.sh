#!/usr/bin/env bash
# Get a realm to test in: claim a warm one, or order one when the pool is out.
#
# Usage: get-realm.sh <name> [ttl-hours] [cold-timeout-seconds]
#
# The connection comes from the environment -- ENDPOINT, PROJECT_ID, USERNAME,
# USER_PASSWORD -- as it does for wait-for-realm.sh, which this calls.
#
# SSH_PUBLIC_KEY, when set, is the path to a public key to put on the realm,
# claimed or ordered alike, so the realm can be reached over ssh.
#
# Results are printed to stdout as KEY=value lines, ready to append to
# $GITHUB_ENV, and everything else goes to stderr so stdout stays readable by
# machine:
#
#   REALM_UUID, REALM_DOMAIN, ADMIN_PASSWORD, REALM_SOURCE (pool|ordered)
#
# ADMIN_PASSWORD is on stdout either way, so a caller masks it once and does
# not care which path produced the realm.  A claim answers with a generated
# password and that answer is the only time it can be read; an order is given
# one, because `realms add` cannot report what it made.
set -uo pipefail

name="$1"
ttl_hours="${2:-2}"
cold_timeout="${3:-660}"

: "${ENDPOINT:?ENDPOINT is not set}"
: "${PROJECT_ID:?PROJECT_ID is not set}"
: "${USERNAME:?USERNAME is not set}"
: "${USER_PASSWORD:?USER_PASSWORD is not set}"

exo=(exordos --endpoint "$ENDPOINT" --project-id "$PROJECT_ID"
     --user "$USERNAME" --password "$USER_PASSWORD")

# Passed on explicitly even though the CLI reads SSH_PUBLIC_KEY too, so a
# missing file fails here, before a realm is taken, and not inside the CLI.
ssh_key=()
if [ -n "${SSH_PUBLIC_KEY:-}" ]; then
    if [ ! -f "$SSH_PUBLIC_KEY" ]; then
        echo "SSH_PUBLIC_KEY is not a file: $SSH_PUBLIC_KEY" >&2
        exit 1
    fi
    ssh_key=(--ssh-public-key "$SSH_PUBLIC_KEY")
fi

# The exit code `realms claim` keeps for an empty pool, as opposed to a
# failure: see POOL_EMPTY_EXIT_CODE in the CLI.
POOL_EMPTY_EXIT_CODE=3

field() {
    jq -r --arg f "$1" '.[] | select(.field == $f) | .value'
}

claimed="$("${exo[@]}" realms claim --name "$name" --ttl-hours "$ttl_hours" \
    "${ssh_key[@]}" -o json 2>/dev/null)"
rc=$?

if [ "$rc" -eq 0 ]; then
    echo "Claimed a warm realm" >&2
    printf 'REALM_UUID=%s\n' "$(echo "$claimed" | field uuid)"
    printf 'REALM_DOMAIN=%s\n' "$(echo "$claimed" | field domain)"
    printf 'ADMIN_PASSWORD=%s\n' "$(echo "$claimed" | field admin_password)"
    printf 'REALM_SOURCE=pool\n'
    exit 0
fi

if [ "$rc" -ne "$POOL_EMPTY_EXIT_CODE" ]; then
    echo "Claim failed with exit code $rc" >&2
    "${exo[@]}" realms claim --name "$name" --ttl-hours "$ttl_hours" \
        "${ssh_key[@]}" >&2
    exit "$rc"
fi

echo "The pool was empty, ordering a realm instead" >&2

# `realms add` reports nothing a machine can read and cannot set a deadline,
# so the uuid and the password are chosen here and the realm is read back once
# it is up.  Hex so that nothing in it has to survive a shell.
uuid="$(uuidgen)"
admin_password="$(openssl rand -hex 16)"

# Sizing is left out on purpose: the defaults are what the pool is warmed
# from, so an ordered realm matches a claimed one.
#
# The output is scrubbed rather than passed through: some of the CLI's errors
# quote the whole request back, the password with it, and the caller cannot
# have masked it yet -- it was generated here, moments ago.
add_log="$(mktemp)"
trap 'rm -f "$add_log"' EXIT
if ! "${exo[@]}" realms add --uuid "$uuid" --name "$name" \
        --admin-password "$admin_password" "${ssh_key[@]}" \
        > "$add_log" 2>&1; then
    sed "s/$admin_password/***/g" "$add_log" >&2
    echo "Could not order a realm" >&2
    exit 1
fi
sed "s/$admin_password/***/g" "$add_log" >&2

if ! .github/scripts/wait-for-realm.sh "$uuid" "$cold_timeout" >&2; then
    echo "The ordered realm never became ACTIVE" >&2
    exit 1
fi

domain="$("${exo[@]}" realms show "$uuid" -o json 2>/dev/null | field domain)"
if [ -z "$domain" ]; then
    echo "The ordered realm reports no domain" >&2
    exit 1
fi

echo "Ordered a realm and waited for it" >&2
printf 'REALM_UUID=%s\n' "$uuid"
printf 'REALM_DOMAIN=%s\n' "$domain"
printf 'ADMIN_PASSWORD=%s\n' "$admin_password"
printf 'REALM_SOURCE=ordered\n'
