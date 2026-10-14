#!/usr/bin/env python3
"""Print BASE_ELEMENT_VERSION and TARGET_ELEMENT_VERSION for an update test."""

import json
import re
import subprocess
import sys


def list_releases(name, endpoint, latest=False):
    command = [
        "exordos", "--no-check-updates", "--endpoint", endpoint,
        "repo", "store", "list", "-f", f"name={name}",
        "-f", "stable=true", "-o", "json",
    ]
    if latest:
        command.extend(["-f", "latest=true"])
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
    return json.loads(result.stdout)


def resolve_versions(name, endpoint):
    stable = re.compile(r"^\d+\.\d+\.\d+$")

    def key(version):
        return tuple(map(int, version.split(".")))

    # Query the public store explicitly: the test core is not bootstrapped yet.
    latest_versions = {
        e["version"] for e in list_releases(name, endpoint, latest=True)
        if e.get("name") == name and stable.fullmatch(e.get("version", ""))
    }
    if not latest_versions:
        raise ValueError(f"{name}: no latest stable release in the store")
    latest = max(latest_versions, key=key)
    versions = {
        e["version"] for e in list_releases(name, endpoint)
        if e.get("name") == name and stable.fullmatch(e.get("version", ""))
    }
    if latest not in versions:
        raise ValueError(f"{name}: latest {latest} is missing from the store release list")
    previous = [v for v in versions if stable.fullmatch(v) and key(v) < key(latest)]
    if not previous:
        raise ValueError(f"{name}: no stable release precedes latest {latest}")
    return max(previous, key=key), latest


if __name__ == "__main__":
    try:
        base, target = resolve_versions(
            sys.argv[1],
            sys.argv[2].rstrip("/") if len(sys.argv) > 2
            else "https://exordos.com/api/core",
        )
    except Exception as exc:
        sys.exit(f"Cannot resolve update versions: {exc}")
    print(f"BASE_ELEMENT_VERSION={base}")
    print(f"TARGET_ELEMENT_VERSION={target}")
