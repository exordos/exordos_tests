#!/usr/bin/env bash
# Run the optional repository-owned hook for this element and update phase.
set -euo pipefail

phase="${1:?Expected prepare or verify}"
case "$phase" in
    prepare|verify) ;;
    *) echo "Unknown update hook phase: $phase" >&2; exit 2 ;;
esac
case "${ELEMENT_NAME:?ELEMENT_NAME is not set}" in
    *[!a-zA-Z0-9_-]*) echo "Invalid element name" >&2; exit 2 ;;
esac
hook=".github/element-update-hooks/$ELEMENT_NAME.sh"
if [[ -f "$hook" ]]; then
    bash "$hook" "$phase"
else
    echo "No update hook for $ELEMENT_NAME; skipping $phase"
fi
