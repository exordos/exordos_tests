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
    exordos e e install "$name" -v "$version" || exit 1
else
    exordos e e install "$name" || exit 1
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
