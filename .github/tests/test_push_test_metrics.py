import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/push-test-metrics.sh'


class MetricsTests(unittest.TestCase):
    def push(self, workflow=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'curl').write_text('#!/bin/sh\nexit 0\n')
            jobs = {'jobs': [
                {'name': f'{element} / install / Test', 'runner_name': runner,
                 'started_at': '2026-10-21T00:00:00Z', 'steps': [
                     {'name': step, 'conclusion': 'success',
                      'started_at': '2026-10-21T00:00:00Z',
                      'completed_at': '2026-10-21T00:00:05Z'}]}
                for element, runner, step in [('world', 'other', 'Wrong step'),
                                               ('s3aas', 'current', 'Install')]
            ]}
            (root / 'jobs.json').write_text(json.dumps(jobs))
            (root / 'gh').write_text('#!/bin/sh\ncat "$JOBS_FIXTURE"\n')
            for name in ('curl', 'gh'):
                (root / name).chmod(0o755)
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}',
                       JOBS_FIXTURE=str(root / 'jobs.json'), VM_IMPORT_URL='http://unused',
                       GH_TOKEN='fake', GITHUB_REPOSITORY='exordos/exordos_tests',
                       GITHUB_WORKFLOW='scheduled_element_tests', GITHUB_JOB='Test',
                       GITHUB_REF_NAME='master', GITHUB_EVENT_NAME='schedule',
                       GITHUB_RUN_ID='1', GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='abc',
                       RUNNER_NAME='current', ELEMENT_NAME='s3aas')
            env.pop('TEST_WORKFLOW', None)
            if workflow:
                env['TEST_WORKFLOW'] = workflow
            return subprocess.run(['bash', str(SCRIPT), 'success'], env=env,
                                  capture_output=True, text=True, check=True).stdout

    def test_reusable_workflow_identity_and_matrix_step_isolation(self):
        output = self.push('element_realm_tests / s3aas / install')
        self.assertIn('workflow="element_realm_tests / s3aas / install"', output)
        self.assertNotIn('workflow="scheduled_element_tests"', output)
        self.assertIn('step="Install"', output)
        self.assertNotIn('Wrong step', output)
        self.assertEqual(output.count('exordos_tests_run_duration_seconds{'), 1)
        self.assertRegex(output, r'exordos_tests_step_duration_seconds\{[^\n]+\} 5')

    def test_workflow_defaults_to_github_workflow(self):
        self.assertIn('workflow="scheduled_element_tests"', self.push())
