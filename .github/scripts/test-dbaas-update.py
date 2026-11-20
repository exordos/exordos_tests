#!/usr/bin/env python3
"""Seed and verify the communal PostgreSQL instance across an update."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import psycopg

PROJECT = '12345678-c625-4fee-81d5-f691897b8142'
STATE = Path(os.environ['RUNNER_TEMP']) / 'dbaas-update-state.json'
USER = 'element_update_test'
DATABASE = 'element_update_test'
ROWS = [(1, ''), (2, 'before update: Привет'), (3, 'x' * 65536)]


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


def find_instance():
    found = cli('dbaas', 'instances', 'list', '-f', 'name=communal-pg-cluster')
    if len(found) != 1:
        raise RuntimeError(f'Expected one communal-pg-cluster, found {len(found)}')
    return found[0]['uuid']


def ready(uuid):
    deadline = time.monotonic() + 840
    while time.monotonic() < deadline:
        try:
            obj = cli('dbaas', 'instances', 'show', uuid)
            ips = obj.get('ipsv4')
            if obj.get('status') == 'ACTIVE' and ips:
                return ips[0]
            if obj.get('status') in ('ERROR', 'CREATE_FAILED'):
                raise RuntimeError(f'PostgreSQL instance failed: {obj["status"]}')
        except RuntimeError as exc:
            if str(exc) != 'Exordos CLI request failed':
                raise
        time.sleep(5)
    raise RuntimeError('PostgreSQL instance did not become ACTIVE with an IP')


def tunnel(ip):
    info = cli('--endpoint', os.environ['ENDPOINT'], '--project-id', os.environ['PROJECT_ID'],
               '--user', os.environ['USERNAME'], '--password', os.environ['USER_PASSWORD'],
               'realms', 'ssh_connection', os.environ['REALM_UUID'])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen(['ssh', '-N', '-o', 'ExitOnForwardFailure=yes',
        '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'BatchMode=yes', '-i', os.environ['SSH_KEY'], '-p', str(info['port']),
        '-L', f'127.0.0.1:{port}:{ip}:5432', f'ubuntu@{info["host"]}'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, port


def check(conn, seed):
    with conn.cursor() as cur:
        if seed:
            cur.execute('CREATE TABLE update_test (id integer PRIMARY KEY, value text NOT NULL)')
            cur.executemany('INSERT INTO update_test (id, value) VALUES (%s, %s)', ROWS)
            conn.commit()
        cur.execute('SELECT id, value FROM update_test ORDER BY id')
        actual = cur.fetchall()
        if actual != ROWS:
            raise AssertionError('PostgreSQL rows do not match the original data')
        if not seed:
            cur.execute('INSERT INTO update_test (id, value) VALUES (4, %s)', ('after update',))
            conn.commit()
            cur.execute('SELECT value FROM update_test WHERE id = 4')
            if cur.fetchone() != ('after update',):
                raise AssertionError('Post-update write was not readable')


def run_check(state, seed):
    ip = ready(state['instance'])
    proc, port = tunnel(ip)
    try:
        deadline = time.monotonic() + 300
        while True:
            if proc.poll() is not None:
                raise RuntimeError('SSH tunnel exited')
            try:
                with psycopg.connect(host='127.0.0.1', port=port, dbname=DATABASE,
                                     user=USER, password=state['password'],
                                     connect_timeout=5) as conn:
                    check(conn, seed)
                return
            except psycopg.OperationalError as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError('PostgreSQL did not become ready') from exc
                time.sleep(5)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def seed():
    uuid = find_instance()
    ready(uuid)
    password = secrets.token_hex(24)
    common = ['-p', PROJECT, '-i', uuid]
    user = cli('dbaas', 'users', 'add', *common, '-n', USER, '--password', password)
    cli('dbaas', 'databases', 'add', *common, '-n', DATABASE, '--owner', user['uuid'])
    state = {'instance': uuid, 'password': password}
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(state, out)
    run_check(state, True)
    print('Seeded and verified communal PostgreSQL data')


if __name__ == '__main__':
    if sys.argv[1:] == ['seed']:
        seed()
    elif sys.argv[1:] == ['verify']:
        run_check(json.loads(STATE.read_text()), False)
        print('Verified communal PostgreSQL data and new writes after update')
    else:
        sys.exit('Usage: test-dbaas-update.py seed|verify')
