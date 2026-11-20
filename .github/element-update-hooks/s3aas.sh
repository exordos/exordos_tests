#!/usr/bin/env bash
# Run S3-specific setup and checks around an element update.
set -euo pipefail

case "$1" in
    prepare)
        python3 -m venv "$RUNNER_TEMP/s3-test-venv"
        "$RUNNER_TEMP/s3-test-venv/bin/pip" install boto3
        .github/scripts/wait-for-repo-version.sh "$BASE_ELEMENT_VERSION" 540 communal_s3
        .github/scripts/install-element.sh communal_s3 "$BASE_ELEMENT_VERSION" 840
        "$RUNNER_TEMP/s3-test-venv/bin/python" .github/scripts/test-s3-update.py seed
        ;;
    verify)
        "$RUNNER_TEMP/s3-test-venv/bin/python" .github/scripts/test-s3-update.py verify
        ;;
    *)
        echo "Unknown update hook phase: $1" >&2
        exit 2
        ;;
esac
