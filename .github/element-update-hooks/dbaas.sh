#!/usr/bin/env bash
# Run PostgreSQL-specific setup and checks around an element update.
set -euo pipefail

case "$1" in
    prepare)
        python3 -m venv "$RUNNER_TEMP/dbaas-test-venv"
        "$RUNNER_TEMP/dbaas-test-venv/bin/pip" install 'psycopg[binary]'
        .github/scripts/wait-for-repo-version.sh "$BASE_ELEMENT_VERSION" 540 communal_pg_cluster
        .github/scripts/install-element.sh communal_pg_cluster "$BASE_ELEMENT_VERSION" 840
        "$RUNNER_TEMP/dbaas-test-venv/bin/python" .github/scripts/test-dbaas-update.py seed
        ;;
    verify)
        "$RUNNER_TEMP/dbaas-test-venv/bin/python" .github/scripts/test-dbaas-update.py verify
        ;;
    *)
        echo "Unknown update hook phase: $1" >&2
        exit 2
        ;;
esac
