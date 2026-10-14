#!/usr/bin/env python3
"""Print BASE_ELEMENT_VERSION and TARGET_ELEMENT_VERSION for an update test."""

import json
import re
import subprocess
import sys


def list_releases(name, repo_url):
    command = [
        "exordos", "--silent", "--no-check-updates", "repo", "versions", name,
        "--repo-url", repo_url, "--stable", "-o", "json",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
    return json.loads(result.stdout)


def resolve_versions(name, repo_url):
    stable = re.compile(r"^\d+\.\d+\.\d+$")

    def key(version):
        return tuple(map(int, version.split(".")))

    releases = list_releases(name, repo_url)
    latest_versions = {
        e["version"] for e in releases
        if e.get("latest") is True and stable.fullmatch(e.get("version", ""))
    }
    if not latest_versions:
        raise ValueError(f"{name}: no latest stable release in the repository")
    latest = max(latest_versions, key=key)
    versions = {
        e["version"] for e in releases
        if stable.fullmatch(e.get("version", ""))
    }
    if latest not in versions:
        raise ValueError(f"{name}: latest {latest} is missing from the repository release list")
    previous = [v for v in versions if stable.fullmatch(v) and key(v) < key(latest)]
    if not previous:
        raise ValueError(f"{name}: no stable release precedes latest {latest}")
    return max(previous, key=key), latest


if __name__ == "__main__":
    try:
        base, target = resolve_versions(
            sys.argv[1],
            sys.argv[2].rstrip("/") if len(sys.argv) > 2
            else "https://repo.exordos.com/exordos-elements",
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(f"Cannot resolve update versions: {exc.stderr.strip() or exc}")
    except Exception as exc:
        sys.exit(f"Cannot resolve update versions: {exc}")
    print(f"BASE_ELEMENT_VERSION={base}")
    print(f"TARGET_ELEMENT_VERSION={target}")
