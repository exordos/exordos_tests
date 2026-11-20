#!/usr/bin/env python3
"""Seed and verify the communal S3 instance across an element update."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib import error, parse, request

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

PROJECT = '12345678-c625-4fee-81d5-f691897b8142'
STATE = Path(os.environ['RUNNER_TEMP']) / 's3-update-state.json'
BUCKET = 'element-update-test'
OBJECTS = {'empty': b'', 'hello.txt': b'communal S3 update test\n',
           'binary': bytes(range(256)) * 4096}


def cli(*args):
    try:
        result = subprocess.run(['exordos', *args, '-o', 'json'], check=True,
                                capture_output=True, text=True, timeout=120)
    except subprocess.CalledProcessError:
        raise RuntimeError('Exordos CLI request failed') from None
    data = json.loads(result.stdout)
    if isinstance(data, list) and data and 'field' in data[0]:
        return {item['field']: item['value'] for item in data}
    return data


def instance(uuid=None):
    if uuid:
        return cli('metapaas', 's3', 'instances', 'show', uuid)
    matches = cli('metapaas', 's3', 'instances', 'list', '-f', 'name=communal-s3')
    if len(matches) != 1:
        raise RuntimeError(f'Expected one communal-s3 instance, found {len(matches)}')
    return matches[0]


def ready(uuid):
    deadline = time.monotonic() + 840
    while time.monotonic() < deadline:
        try:
            obj = instance(uuid)
            ips = obj.get('ipsv4') or obj.get('IPs')
            if obj.get('status') == 'ACTIVE' and ips:
                if isinstance(ips, str):
                    ips = ips.split(', ')
                return ips[0]
            if obj.get('status') in ('ERROR', 'CREATE_FAILED'):
                raise RuntimeError(f'S3 instance failed: {obj.get("status")}')
        except RuntimeError as exc:
            if str(exc) != 'Exordos CLI request failed':
                raise
            pass
        time.sleep(5)
    raise RuntimeError('S3 instance did not become ACTIVE with an IP')


def tunnel(ip):
    info = cli('--endpoint', os.environ['ENDPOINT'], '--project-id', os.environ['PROJECT_ID'],
               '--user', os.environ['USERNAME'], '--password', os.environ['USER_PASSWORD'],
               'realms', 'ssh_connection', os.environ['REALM_UUID'])
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen(['ssh', '-N', '-o', 'ExitOnForwardFailure=yes',
        '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'BatchMode=yes', '-i', os.environ['SSH_KEY'], '-p', str(info['port']),
        '-L', f'127.0.0.1:{port}:{ip}:9000', f'ubuntu@{info["host"]}'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, port


def client(state, port):
    return boto3.client('s3', endpoint_url=f'http://127.0.0.1:{port}',
        aws_access_key_id=state['access_key'], aws_secret_access_key=state['secret_key'],
        region_name='us-east-1', config=Config(signature_version='s3v4',
        s3={'addressing_style': 'path'}, connect_timeout=3, read_timeout=10,
        retries={'max_attempts': 1}))


def check(s3, write):
    if write:
        for key, body in OBJECTS.items():
            s3.put_object(Bucket=BUCKET, Key=key, Body=body)
    keys = {item['Key'] for item in s3.list_objects_v2(Bucket=BUCKET).get('Contents', [])}
    if not OBJECTS.keys() <= keys:
        raise AssertionError(f'Missing objects: {OBJECTS.keys() - keys}')
    for key, body in OBJECTS.items():
        actual = s3.get_object(Bucket=BUCKET, Key=key)['Body'].read()
        if hashlib.sha256(actual).digest() != hashlib.sha256(body).digest():
            raise AssertionError(f'Object {key} content differs')
    if not write:
        s3.put_object(Bucket=BUCKET, Key='after-update', Body=b'new data')
        assert s3.get_object(Bucket=BUCKET, Key='after-update')['Body'].read() == b'new data'


def run_data_check(state, write):
    ip = ready(state['instance'])
    proc, port = tunnel(ip)
    try:
        deadline = time.monotonic() + 300
        while True:
            if proc.poll() is not None:
                raise RuntimeError('SSH tunnel exited')
            try:
                check(client(state, port), write)
                return
            except (BotoCoreError, ClientError) as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError('S3 did not become ready') from exc
                time.sleep(5)
    finally:
        proc.terminate()
        proc.wait(timeout=10)



def attach_policy(instance_uuid, user_uuid, policy_uuid):
    # The CLI sends a UUID, but this API generates it and marks it read-only.
    core = os.environ['REALM_CORE_URL'].rstrip('/')
    token_request = request.Request(
        core + '/v1/iam/clients/default/actions/get_token/invoke',
        data=parse.urlencode({'grant_type': 'password', 'username': 'admin',
                              'password': os.environ['ADMIN_PASSWORD'],
                              'scope': f'project:{PROJECT}'}).encode(),
    )
    token = ''
    try:
        with request.urlopen(token_request, timeout=30) as response:
            token = json.load(response)['access_token']
        instance = f'/v1/types/s3/instances/{instance_uuid}'
        url = parse.urljoin(core, '/api/metapaas') + f'{instance}/users/{user_uuid}/policies/'
        body = {'project_id': PROJECT, 'instance': instance,
                'user': f'{instance}/users/{user_uuid}',
                'policy': f'{instance}/policies/{policy_uuid}'}
        api_request = request.Request(url, data=json.dumps(body).encode(), method='POST',
                                      headers={'Authorization': f'Bearer {token}',
                                               'Content-Type': 'application/json'})
        with request.urlopen(api_request, timeout=60) as response:
            response.read()
    except error.HTTPError as exc:
        # The error body describes the API validation; do not expose the token.
        detail = exc.read().decode('utf-8', errors='replace')[:4000]
        for secret in (os.environ['ADMIN_PASSWORD'], token):
            if secret:
                detail = detail.replace(secret, '[redacted]')
        raise RuntimeError(f'Policy attachment API failed (HTTP {exc.code}): {detail}') from None


def seed():
    obj = instance()
    uuid = obj['uuid']
    ready(uuid)
    common = ['-p', PROJECT, '-i', uuid]
    cli('metapaas', 's3', 'buckets', 'add', *common, '-n', BUCKET)
    user = cli('metapaas', 's3', 'users', 'add', *common, '-n', 'element-update-test')
    policy = cli('metapaas', 's3', 'policies', 'add', *common, '-n', 'element-update-test',
        '--content', json.dumps({'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow',
        'Action': ['s3:*'], 'Resource': [f'arn:aws:s3:::{BUCKET}', f'arn:aws:s3:::{BUCKET}/*']}]}))
    attach_policy(uuid, user['uuid'], policy['uuid'])
    key = cli('metapaas', 's3', 'keys', 'add', *common, '--user-uuid', user['uuid'])
    state = {'instance': uuid, 'access_key': key['access_key'], 'secret_key': key['secret_key']}
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(state, out)
    run_data_check(state, True)
    print('Seeded and verified communal S3 objects')


if __name__ == '__main__':
    if sys.argv[1:] == ['seed']:
        seed()
    elif sys.argv[1:] == ['verify']:
        run_data_check(json.loads(STATE.read_text()), False)
        print('Verified communal S3 objects and new writes after update')
    else:
        sys.exit('Usage: test-s3-update.py seed|verify')
