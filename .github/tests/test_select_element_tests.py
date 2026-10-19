import importlib.util
import json
from pathlib import Path
import re
import unittest


GITHUB = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "select_element_tests", GITHUB / "scripts/select-element-tests.py"
)
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)
TESTS = json.loads((GITHUB.parent / "element-tests.json").read_text())


class SelectionTests(unittest.TestCase):
    def test_schedules_preserve_existing_runs(self):
        expected = {
            "0 2 * * *": ("bootstrap", "core", True),
            "0 3 * * *": ("bootstrap", "world", False),
            "0 4 * * *": ("realm", "s3aas", False),
            "0 5 * * *": ("realm", "mailaas", False),
            "0 6 * * *": ("realm", "empty", False),
            "0 7 * * *": ("realm", "s3aas", True),
            "0 8 * * *": ("realm", "dbaas", True),
        }
        for cron, (backend, element, update) in expected.items():
            with self.subTest(cron=cron):
                matrices = selector.select_tests(TESTS, "schedule", {"schedule": cron})
                entry = {"element": element, "update": update}
                if element == "world":
                    entry["free-disk-space"] = True
                self.assertEqual(matrices[backend], [entry])
                self.assertEqual(sum(map(len, matrices.values())), 1)

    def test_workflow_triggers_match_configuration(self):
        workflow = (GITHUB / "workflows/scheduled_element_tests.yml").read_text()
        triggers = re.findall(r'- cron: "([^"]+)"', workflow)
        self.assertEqual(set(triggers), {test["cron"] for test in TESTS})

    def test_manual_all(self):
        matrices = selector.select_tests(TESTS, "workflow_dispatch", {})
        self.assertEqual(len(matrices["realm"]), 5)
        self.assertEqual(matrices["bootstrap"], [
            {"element": "core", "update": True},
            {"element": "world", "update": False, "free-disk-space": True},
        ])

    def test_manual_world_preserves_disk_cleanup(self):
        matrices = selector.select_tests(TESTS, "workflow_dispatch", {
            "inputs": {"element": "world", "mode": "install"},
        })
        self.assertEqual(matrices, {
            "realm": [],
            "bootstrap": [{"element": "world", "update": False, "free-disk-space": True}],
        })

    def test_manual_element_and_mode(self):
        for mode, updates in (("all", [False, True]), ("install", [False]), ("update", [True])):
            with self.subTest(mode=mode):
                matrices = selector.select_tests(TESTS, "workflow_dispatch", {
                    "inputs": {"element": "s3aas", "mode": mode},
                })
                self.assertEqual(matrices["realm"], [
                    {"element": "s3aas", "update": update} for update in updates
                ])
                self.assertEqual(matrices["bootstrap"], [])

    def test_same_schedule_can_select_multiple_elements(self):
        tests = [dict(test, cron="0 2 * * *") for test in TESTS]
        matrices = selector.select_tests(tests, "schedule", {"schedule": "0 2 * * *"})
        self.assertEqual(sum(map(len, matrices.values())), 7)

    def test_unconfigured_selection_fails(self):
        for event_name, event in (
            ("workflow_dispatch", {"inputs": {"element": "core", "mode": "install"}}),
            ("schedule", {"schedule": "0 0 * * *"}),
        ):
            with self.subTest(event=event), self.assertRaisesRegex(ValueError, "No configured tests"):
                selector.select_tests(TESTS, event_name, event)


if __name__ == "__main__":
    unittest.main()
