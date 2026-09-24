#!/usr/bin/env bash
# Install an element and wait until it is ACTIVE on the version asked for.
#
# Usage: install-element.sh <name> [version] [timeout-seconds]
#
# Talks to whichever realm the CLI is pointed at.  Without a version the
# repository's latest is installed and any version passes.
set -uo pipefail

name="$1"
version="${2:-}"
timeout="${3:-540}"

here="$(dirname "$0")"

if [ -n "$version" ]; then
    install=(exordos e e install "$name" -v "$version")
else
    install=(exordos e e install "$name")
fi
if ! "${install[@]}"; then
    # The CLI retries an install whose answer timed out, and when the first
    # attempt went through the retry is refused with "Element must be
    # uninstalled".  So an element the realm lists after a failed install is
    # the one asked for, still being set up: wait for it, and let the version
    # check below catch an element that was there before.
    if [ -z "$(exordos ee l -o json -f "name=$name" 2>/dev/null \
            | jq -r '.[0].name // ""' 2>/dev/null)" ]; then
        exit 1
    fi
    echo "The install failed, but the realm has $name: waiting for it"
fi

"$here/wait-for-element.sh" "$name" "$timeout" || exit 1

if [ -n "$version" ]; then
    installed="$(exordos ee l -o json -f "name=$name" | jq -r '.[0].version')"
    if [ "$installed" != "$version" ]; then
        echo "Installed $name $installed instead of $version" >&2
        exit 1
    fi
fi

exordos e e show "$name"
