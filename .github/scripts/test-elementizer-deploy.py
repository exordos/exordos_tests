# Copyright 2026 Genesis Corporation.
# Licensed under the Apache License, Version 2.0 (the "License").
"""Deploy a generated static fixture through the live Elementizer API."""

import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class Failure(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details


def redact(value, token=None):
    secrets = [token, *(os.environ.get(key) for key in
                       ('ADMIN_PASSWORD', 'USER_PASSWORD', 'TEST_USER_PASSWORD'))]
    if isinstance(value, dict):
        return {redact(key, token): redact(item, token) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, str):
        for secret in sorted(filter(None, secrets), key=len, reverse=True):
            # Also cover JSON quoted values embedded inside plain-text errors.
            for form in (json.dumps(secret)[1:-1], secret):
                value = value.replace(form, '[REDACTED]')
    return value


def http_failure(message, url, token, data=None, status=None, body=None):
    details = {'method': 'GET' if data is None else 'POST', 'url': url}
    if status is not None:
        details['status'] = status
    if body is not None:
        try:
            response = json.loads(body)
        except (ValueError, UnicodeError):
            response = body.decode('utf-8', errors='replace')
        # Redact before serializing or truncating so escaping and cut-off
        # secrets cannot defeat replacement. Keep diagnostics bounded.
        response = redact(response, token)
        encoded = json.dumps(response, ensure_ascii=True)
        details['response'] = response if len(encoded) <= 16384 else encoded[:16384]
        details['response_truncated'] = len(encoded) > 16384
    details = redact(details, token)
    return Failure(message + ': ' + json.dumps(details, ensure_ascii=True), details)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never forward the realm token to a redirect destination or accept a login UI.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, token=None, data=None, content_type='application/json'):
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if data is not None:
        headers['Content-Type'] = content_type
        if not isinstance(data, bytes):
            data = json.dumps(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
            return response.status, response.headers, response.read(2 * 1024 * 1024)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.headers, error.read(2 * 1024 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise http_failure(f'HTTP transport failed ({type(error).__name__})',
                           url, token, data) from None


def api(url, token, data=None):
    status, _, body = request(url, token, data)
    if status not in (200, 201, 202):
        raise http_failure(f'API returned HTTP {status}', url, token, data, status, body)
    try:
        return json.loads(body)
    except ValueError:
        raise http_failure('API did not return JSON', url, token, data, status, body) from None


def repository(records, realm):
    matches = []
    origin = urllib.parse.urlsplit(realm)
    for record in records:
        path = urllib.parse.urlsplit(record.get('driver_spec', {}).get('url', '')).path
        match = re.fullmatch(r'/repo/([0-9a-fA-F-]{36})/exordos-elements/', path)
        if record.get('status') == 'ACTIVE' and match:
            project = str(uuid.UUID(match[1]))
            matches.append({'name': record['name'], 'driver': 'realm',
                            'url': f'{origin.scheme}://{origin.netloc}/repo/{project}'})
    if len(matches) != 1:
        raise Failure(f'Expected one active realm repository, found {len(matches)}')
    return matches[0]


def fixture(marker):
    files = {'index.html': f'<!doctype html><html><head><title>Deployment smoke test</title>'
             f'</head><body><h1>{marker}</h1></body></html>\n',
             'probe.txt': marker + '\n'}
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w:gz') as tar:
        for name, content in files.items():
            payload = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(payload))
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            'filename="site.tar.gz"\r\nContent-Type: application/gzip\r\n\r\n').encode()
    body += archive.getvalue() + f'\r\n--{boundary}--\r\n'.encode()
    return body, f'multipart/form-data; boundary={boundary}'


def issue_token(realm):
    # A private config isolates the child realm from the runner's default
    # project and keeps its password out of process arguments and artifacts.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as config:
        json.dump({'endpoint': realm, 'user': 'admin',
                   'password': os.environ['ADMIN_PASSWORD']}, config)
        config.flush()
        result = subprocess.run(['exordos', '--config', config.name,
                                 '--no-check-updates', 'iam', 'tokens', 'add',
                                 '--days', '1', '-o', 'json'],
                                capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise Failure('Could not issue realm token (CLI output withheld to protect credentials)')
    try:
        token = json.loads(result.stdout)['access_token']
    except (ValueError, KeyError, TypeError):
        raise Failure('Token command returned no access_token') from None
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print(f'::add-mask::{token}', flush=True)
    return token


class Run:
    def __init__(self, endpoint, token, output):
        self.endpoint = endpoint.rstrip('/')
        self.token = token
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.build_url = None

    def save(self, name, value):
        text = json.dumps(redact(value, self.token), indent=2, ensure_ascii=False)
        (self.output / name).write_text(text + '\n')

    def latest_plan(self):
        plans = api(self.build_url + '/plans/', self.token)
        if not plans:
            raise Failure('Build has no plan')
        return max(plans, key=lambda plan: plan['version'])

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        version = None
        phase = None
        phase_deadline = deadline
        while time.monotonic() < deadline:
            progress = api(self.build_url + '/actions/progress', self.token)
            self.save('progress.json', progress)
            print(f"Build: {progress['build_status']}, phase: {progress['phase']}", flush=True)
            if progress['phase'] != phase:
                phase = progress['phase']
                phase_deadline = time.monotonic() + {
                    'PREPARING': 600, 'PLANNING': 600, 'BUILDING': 10800,
                    'DEPLOYING': 3600, 'DIAGNOSING': 1800,
                }.get(phase, timeout)
            if time.monotonic() >= phase_deadline:
                raise Failure(f'Phase deadline exceeded: {phase}')
            if progress['build_status'] in ('BUILD_FAILED', 'ESCALATED'):
                raise Failure(f"Build stopped: {progress['build_status']}")
            if not progress['plan_stale'] and progress['plan_version']:
                if version != progress['plan_version'] or progress['build_status'] == 'DONE':
                    plan = self.latest_plan()
                    self.save(f"plan-{plan['version']}.json", plan)
                    version = plan['version']
                    # Name/version are supplied before uploading. Repeated or new
                    # questions indicate this fixed fixture cannot proceed unattended.
                    if plan.get('missing_info'):
                        raise Failure('Plan requires answers; see saved plan')
                    if progress['build_status'] == 'DONE':
                        return plan
            delay = progress.get('wait_seconds') or 15
            time.sleep(min(max(1, delay), max(0, deadline - time.monotonic())))
        raise Failure('Build deadline exceeded')

    def verify(self, plan, marker, timeout):
        urls = [item['url'] for item in plan.get('endpoints', []) if item.get('url')]
        if len(urls) != 1:
            raise Failure(f'Expected one public site endpoint, found {len(urls)}')
        url = urls[0]
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username:
            raise Failure('Invalid public endpoint')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            results = []
            for target, probe in ((url, False), (url.rstrip('/') + '/probe.txt', True)):
                try:
                    status, headers, body = request(target)
                    valid = (body == (marker + '\n').encode() if probe else
                             marker.encode() in body and
                             headers.get_content_type() == 'text/html')
                    results.append({'url': target, 'status': status,
                                    'matches': status == 200 and valid})
                except Failure as error:
                    results.append({'url': target, 'matches': False, 'error': str(error)})
            self.save('http-checks.json', results)
            if all(item['matches'] for item in results):
                return url
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        raise Failure('Published site did not serve the current fixture before deadline')

    def execute(self, realm, timeout, http_timeout):
        marker = 'elementizer-smoke-' + uuid.uuid4().hex
        repo = repository(api(realm + '/v1/repo/repositories/', self.token), realm)
        inventory_url = repo['url'] + f'/exordos-elements/{marker}/0.1.0/inventory.json'
        status, _, body = request(inventory_url, self.token)
        if status != 404:
            raise http_failure('Repository preflight expected 404', inventory_url,
                               self.token, status=status, body=body)
        build = api(self.endpoint + '/builds/', self.token, {
            'name': marker,
            'description': 'Publish the supplied static site. index.html and probe.txt '
            'are ready to serve from the archive root; preserve their contents exactly. '
            'No compilation, server process, database, external services or secrets are '
            'needed. Provide public access on a dedicated address in the realm domain '
            'zone. Application version is 0.1.0.',
            'minimal': True, 'deploy': True, 'diagnose': False,
            'realm': {'api': {'url': realm}, 'repository': repo},
        })
        build_id = str(uuid.UUID(build['uuid']))
        self.build_url = self.endpoint + '/builds/' + build_id
        self.save('run.json', {'build_id': build_id, 'realm': realm, 'marker': marker})
        print(f'Build ID: {build_id}', flush=True)
        api(self.build_url + '/actions/answers/invoke', self.token,
            {'answers': {'element_name': marker, 'element_version': '0.1.0'}})
        body, content_type = fixture(marker)
        upload_url = self.build_url + '/actions/upload/invoke'
        status, _, response = request(upload_url, self.token, body, content_type)
        if status not in (200, 201, 202):
            raise http_failure('Upload failed', upload_url, self.token, body, status, response)
        plan = self.wait(timeout)
        self.save('wrapping.json', api(self.build_url + '/actions/wrapping', self.token))
        url = self.verify(plan, marker, http_timeout)
        self.save('result.json', {'success': True, 'build_id': build_id, 'url': url})
        print(f'Published HTML verified: {url}', flush=True)

    def diagnostics(self):
        if self.build_url:
            for name, suffix in [('error', '/actions/error'), ('progress', '/actions/progress'),
                                 ('plans', '/plans/')]:
                try:
                    self.save(name + '.json', api(self.build_url + suffix, self.token))
                except Failure:
                    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', default='https://exordos.com/api/elementizer/v1')
    parser.add_argument('--timeout', type=int, default=7200)
    parser.add_argument('--http-timeout', type=int, default=300)
    parser.add_argument('--output', type=Path, default=Path('elementizer-results'))
    args = parser.parse_args()
    run = None
    try:
        realm = os.environ['REALM_CORE_URL'].rstrip('/')
        run = Run(args.endpoint, issue_token(realm), args.output)
        run.execute(realm, args.timeout, args.http_timeout)
    except (Failure, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        # HTTP failures already contain sanitized diagnostics; other exception
        # messages and subprocess output may contain credentials.
        message = str(error) if isinstance(error, Failure) else type(error).__name__
        if run:
            result = {'success': False, 'error': message}
            if isinstance(error, Failure) and error.details is not None:
                result['request'] = error.details
            run.save('result.json', result)
            run.diagnostics()
        print(f'Deployment test failed: {message}', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
