#!/usr/bin/env bash
# PostgreSQL 18, dedicated DataMesh cluster. Run with sudo on an Ubuntu systemd host.
# Never source an untrusted env file, enable tracing, or put credentials in argv.
set +x
set -euo pipefail
umask 077

usage() {
  cat <<'HELP'
Usage: sudo bash scripts/deploy_postgres_ubuntu.sh [options]
  --port NUMBER   Dedicated cluster port (default: 5433, not distro main's 5432)
  --pgvector      Install postgresql-18-pgvector and enable vector in the database
  --dry-run       Show the plan only; change nothing (no sudo required)
  --help          Show this help

Ubuntu 22.04/24.04/26.04/26.10 with systemd; PostgreSQL 18 from the official PGDG repo.
Creates cluster 18/datamesh, role datamesh_app, database datamesh.
Listens on 127.0.0.1 only. Credentials: /etc/datamesh/postgres.env (root:root, 0600).
Does NOT run DataMesh migrations, open a firewall, expose remote access, or alter existing clusters.
Re-run without --port to retain the saved port and password. No passwords printed.
HELP
}
PORT=5433; PORT_SET=0; VECTOR=0; DRY=0
while (($#)); do
  case "$1" in
    --port) [[ $# -ge 2 ]] || { echo 'Missing --port value' >&2; exit 2; }; PORT=$2; PORT_SET=1; shift 2 ;;
    --pgvector) VECTOR=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ $PORT =~ ^[0-9]{4,5}$ ]] && ((10#$PORT >= 1024 && 10#$PORT <= 65535)) || { echo 'Port must be 1024..65535' >&2; exit 2; }
if ((DRY)); then
  echo "Plan: verify Ubuntu/systemd; configure signed official PGDG APT repository; install PostgreSQL 18."
  echo "Create managed 18/datamesh cluster if absent (port $PORT on first install; saved port on rerun)."
  echo 'Keep unrelated clusters untouched; refuse an unmanaged existing 18/datamesh cluster or conflicting role/database.'
  echo 'Create dedicated database and unprivileged login; retain generated password in /etc/datamesh/postgres.env (0600).'
  echo 'Require SCRAM authentication; bind 127.0.0.1 only; enable/start postgresql@18-datamesh.service; verify password login.'
  ((VECTOR == 0)) || echo 'Also install postgresql-18-pgvector and CREATE EXTENSION vector in datamesh.'
  echo 'No migrations, remote access, firewall changes or application deployment.'
  exit 0
fi
[[ $EUID -eq 0 ]] || { echo 'Run with sudo (or use --dry-run).' >&2; exit 1; }
[[ -f /etc/os-release ]] || { echo 'Cannot identify OS.' >&2; exit 1; }
. /etc/os-release
[[ $ID == ubuntu ]] || { echo 'Only Ubuntu is supported.' >&2; exit 1; }
CODENAME=${VERSION_CODENAME:-}
case "$CODENAME" in jammy|noble|resolute|stonking) ;; *) echo "Unsupported Ubuntu release: $CODENAME" >&2; exit 1 ;; esac
[[ -d /run/systemd/system ]] || { echo 'Requires a running systemd host.' >&2; exit 1; }
[[ ! -L /etc/datamesh ]] || { echo 'Refusing symlink /etc/datamesh.' >&2; exit 1; }
install -d -o root -g root -m 0700 /etc/datamesh
ENV_FILE=/etc/datamesh/postgres.env
MANAGED=0
if [[ -e $ENV_FILE || -L $ENV_FILE ]]; then
  [[ -f $ENV_FILE && ! -L $ENV_FILE && $(stat -c '%u:%a' "$ENV_FILE") == 0:600 ]] || {
    echo 'Credential file must be a regular root-owned 0600 file.' >&2; exit 1;
  }
  # This is a root-owned deployment marker, not a repo-supplied environment file.
  REQUEST_PORT=$PORT
  . "$ENV_FILE"
  [[ ${DATAMESH_DEPLOYMENT:-} == ubuntu-pg18-v1 && ${DB_USER:-} == datamesh_app && ${DB_NAME:-} == datamesh &&
     ${DB_PASSWORD:-} =~ ^[0-9a-f]{64}$ && ${DB_PORT:-} =~ ^[0-9]{4,5}$ ]] || {
    echo 'Invalid managed credential file.' >&2; exit 1;
  }
  if ((PORT_SET)) && [[ $REQUEST_PORT != "$DB_PORT" ]]; then
    echo 'Refusing port change on an existing deployment.' >&2; exit 1
  fi
  PORT=$DB_PORT; MANAGED=1
fi
# Refuse to adopt a pre-existing cluster. This check happens before APT makes changes.
if [[ -e /etc/postgresql/18/datamesh && $MANAGED == 0 ]]; then
  echo '18/datamesh already exists and is not managed by this script; no changes made.' >&2; exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg postgresql-common openssl iproute2
KEY=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
install -d -m 0755 "$(dirname "$KEY")"
TMP_KEY=$(mktemp)
trap 'rm -f "${TMP_KEY:-}"' EXIT
curl --proto '=https' --tlsv1.2 --fail --silent --show-error \
  https://www.postgresql.org/media/keys/ACCC4CF8.asc -o "$TMP_KEY"
FPR=$(gpg --batch --show-keys --with-colons "$TMP_KEY" | awk -F: '$1 == "fpr" {print $10; exit}')
[[ $FPR == B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8 ]] || { echo 'PGDG signing key fingerprint mismatch.' >&2; exit 1; }
install -m 0644 "$TMP_KEY" "$KEY"
# Do not overwrite a different administrator-managed PGDG source definition.
SOURCE=/etc/apt/sources.list.d/datamesh-pgdg.sources
EXPECTED="Types: deb
URIs: https://apt.postgresql.org/pub/repos/apt
Suites: ${CODENAME}-pgdg
Components: main
Signed-By: $KEY"
if [[ -e $SOURCE ]] && [[ $(cat "$SOURCE") != "$EXPECTED" ]]; then
  echo "Refusing to overwrite $SOURCE (different contents)." >&2; exit 1
fi
printf '%s\n' "$EXPECTED" > "$SOURCE"
chmod 0644 "$SOURCE"
apt-get update
apt-get install -y postgresql-18 postgresql-client-18
((VECTOR == 0)) || apt-get install -y postgresql-18-pgvector

if [[ ! -e /etc/postgresql/18/datamesh ]]; then
  if ss -H -ltn "sport = :$PORT" | grep -q .; then
    echo "Port $PORT is already in use; choose --port on first install." >&2; exit 1
  fi
  # Disable TCP passwordless access from the outset; peer is only for local OS identities.
  pg_createcluster 18 datamesh --port "$PORT" --start-conf=auto -- \
    --auth-local=peer --auth-host=scram-sha-256
fi
CONFIG=/etc/postgresql/18/datamesh
pg_conftool 18 datamesh set listen_addresses 127.0.0.1
pg_conftool 18 datamesh set password_encryption scram-sha-256
# Dedicated, script-owned cluster only. Unrelated cluster configurations are never edited.
cat > "$CONFIG/pg_hba.conf" <<'HBA'
# Managed by deploy_postgres_ubuntu.sh. Local administration uses OS peer identity.
local   all           postgres                            peer
local   all           all                                 peer
host    datamesh      datamesh_app     127.0.0.1/32         scram-sha-256
host    all           all              0.0.0.0/0            reject
host    all           all              ::/0                 reject
HBA
chown postgres:postgres "$CONFIG/pg_hba.conf"
chmod 0640 "$CONFIG/pg_hba.conf"
systemctl enable postgresql@18-datamesh.service
systemctl restart postgresql@18-datamesh.service
PSQL=(runuser -u postgres -- psql -X --cluster 18/datamesh --set ON_ERROR_STOP=1 --dbname postgres)
if ((MANAGED == 0)); then
  CONFLICT=$("${PSQL[@]}" -Atc "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='datamesh_app') OR EXISTS(SELECT 1 FROM pg_database WHERE datname='datamesh')")
  [[ $CONFLICT == f ]] || { echo 'Existing role/database conflict; refusing to adopt it.' >&2; exit 1; }
  DB_USER=datamesh_app; DB_NAME=datamesh; DB_PORT=$PORT
  DB_PASSWORD=$(openssl rand -hex 32)
  # Save BEFORE database writes so an interrupted first install is recoverable with the same credentials.
  printf 'DATAMESH_DEPLOYMENT=ubuntu-pg18-v1\nDB_USER=%s\nDB_NAME=%s\nDB_PORT=%s\nDB_PASSWORD=%s\nDATAMESH_PG_DSN=postgresql://%s:%s@127.0.0.1:%s/%s\n' \
    "$DB_USER" "$DB_NAME" "$PORT" "$DB_PASSWORD" "$DB_USER" "$DB_PASSWORD" "$PORT" "$DB_NAME" > "$ENV_FILE"
  chown root:root "$ENV_FILE"; chmod 0600 "$ENV_FILE"
fi
# Generated hex password travels over stdin, never argv. SQL quoting uses psql's literal syntax.
# Role attributes are restricted explicitly. Database ownership permits only this database's DDL.
{
  printf '\\set pw %s\n' "$DB_PASSWORD"
  cat <<'SQL'
SELECT 'CREATE ROLE datamesh_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='datamesh_app') \gexec
ALTER ROLE datamesh_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'pw';
SELECT 'CREATE DATABASE datamesh OWNER datamesh_app'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='datamesh') \gexec
REVOKE ALL ON DATABASE datamesh FROM PUBLIC;
SQL
} | "${PSQL[@]}" > /dev/null
if ((VECTOR)); then
  runuser -u postgres -- psql -X --cluster 18/datamesh --set ON_ERROR_STOP=1 --dbname datamesh \
    -c 'CREATE EXTENSION IF NOT EXISTS vector' > /dev/null
fi
# Exercise TCP/SCRAM as the application role, not just pg_isready as the administrator.
PGPASSWORD=$DB_PASSWORD psql -X --no-password -h 127.0.0.1 -p "$PORT" -U datamesh_app -d datamesh \
  --set ON_ERROR_STOP=1 -c 'SELECT current_user, current_database(), version();'
systemctl is-active --quiet postgresql@18-datamesh.service
printf 'Ready: postgresql@18-datamesh.service, 127.0.0.1:%s. Credentials: %s (root-only).\n' "$PORT" "$ENV_FILE"
echo 'Next: install the Python postgres extra and run application migrations; see docs/architecture/UBUNTU_POSTGRES.md.'
