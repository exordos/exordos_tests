#!/usr/bin/env python3
"""Select configured tests by the triggering cron or manual inputs."""

import json
import os
from pathlib import Path


def select_tests(tests, event_name, event):
    if event_name == "schedule":
        selected = [test for test in tests if test["cron"] == event["schedule"]]
    elif event_name == "workflow_dispatch":
        inputs = event.get("inputs", {})
        element = inputs.get("element", "all")
        mode = inputs.get("mode", "all")
        selected = [
            test for test in tests
            if element in ("all", test["element"])
            and mode in ("all", "update" if test["update"] else "install")
        ]
    else:
        raise ValueError(f"Unsupported event: {event_name}")
    if not selected:
        raise ValueError("No configured tests match the selected element, mode or schedule")
    return {
        backend: [
            {
                "element": test["element"], "update": test["update"],
                **({"free-disk-space": test["free-disk-space"]}
                   if "free-disk-space" in test else {}),
            }
            for test in selected if test["backend"] == backend
        ]
        for backend in ("realm", "bootstrap")
    }


def main():
    config = Path(__file__).resolve().parents[2] / "element-tests.json"
    tests = json.loads(config.read_text())
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    matrices = select_tests(tests, os.environ["GITHUB_EVENT_NAME"], event)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for backend, entries in matrices.items():
            print(f"{backend}={json.dumps({'include': entries})}", file=output)
            print(f"has-{backend}={str(bool(entries)).lower()}", file=output)


if __name__ == "__main__":
    main()
