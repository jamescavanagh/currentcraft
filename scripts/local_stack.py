"""Manage the local NATS + PostgreSQL Compose stack. Requires Docker Engine and Compose v2.

Secrets are generated locally, never printed or bundled. `down` retains named volumes; no delete-volumes command.
"""
import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / 'deploy/local/compose.json'
SECRET_DIR = ROOT / 'local/compose-secrets'


def initialize(root=ROOT):
    directory = root / 'local/compose-secrets'
    if (root / 'local').is_symlink() or directory.is_symlink():
        raise ValueError('refusing symlink secret directory')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    (root / 'local/intake').mkdir(exist_ok=True, mode=0o755)
    values = {}
    for name in ('pg_admin', 'pg_app', 'nats_token', 'pseudonym_salt'):
        path = directory / name
        if path.is_symlink():
            raise ValueError('refusing symlink secret file')
        if not path.exists():
            # Exclusive create; never rotate an existing volume's password or pseudonym salt on reruns.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
            with os.fdopen(fd, 'w') as stream:
                stream.write(secrets.token_hex(32) + '\n')
        value = path.read_text().strip()
        if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('invalid existing generated secret; restore it, do not silently rotate')
        path.chmod(0o444)
        values[name] = value
    # Compose file-backed secrets retain host ownership/mode. Nonroot application containers need read access;
    # the enclosing host directory is 0700. These are local development secrets, not a secret-manager substitute.
    config = ('server_name: datamesh-local\nport: 4222\n'
              'authorization { token: "' + values['nats_token'] + '" }\n'
              'jetstream {\n  store_dir: "/data"\n  max_memory_store: 64MB\n  max_file_store: 2GB\n}\n')
    target = directory / 'nats.conf'
    if target.is_symlink():
        raise ValueError('refusing symlink NATS configuration')
    if target.exists() and target.read_text() != config:
        raise ValueError('existing NATS configuration differs; review manually')
    if not target.exists():
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(fd, 'w') as stream:
            stream.write(config)
    target.chmod(0o444)
    return directory


def compose(*args):
    subprocess.run(['docker', 'compose', '-f', str(COMPOSE), *args], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'config', 'up', 'smoke', 'status', 'logs', 'down'))
    args = parser.parse_args()
    if args.action in ('init', 'config', 'up', 'smoke'):
        initialize()
    if args.action == 'init':
        print('Local secrets ready under git-ignored local/compose-secrets. Values not printed. Existing secrets retained.')
    elif args.action == 'config':
        compose('config', '--quiet')
    elif args.action == 'up':
        compose('up', '-d', '--build', 'worker')
        compose('ps', '-a')
    elif args.action == 'smoke':
        compose('up', '-d', '--build', 'worker')
        compose('--profile', 'tools', 'run', '--rm', 'smoke')
    elif args.action == 'status':
        compose('ps', '-a')
    elif args.action == 'logs':
        compose('logs', '--tail', '100', 'bootstrap', 'worker', 'postgres', 'nats')
    elif args.action == 'down':
        compose('down')
        print('Named volumes and local secrets retained. Do not remove or regenerate secrets while reusing these volumes.')


if __name__ == '__main__':
    main()
