#!/usr/bin/env bash
# Runs only on a NEW postgres volume. Changing secret files does not rotate database credentials.
set +x
set -euo pipefail
pw=$(cat /run/secrets/pg_app)
[[ $pw =~ ^[0-9a-f]{64}$ ]] || { echo 'Invalid application secret' >&2; exit 1; }
{
  printf '\\set pw %s\n' "$pw"
  cat <<'SQL'
CREATE ROLE datamesh_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'pw';
ALTER DATABASE datamesh OWNER TO datamesh_app;
REVOKE ALL ON DATABASE datamesh FROM PUBLIC;
\connect datamesh
ALTER SCHEMA public OWNER TO datamesh_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
} | psql --username "$POSTGRES_USER" --dbname datamesh --no-psqlrc --set ON_ERROR_STOP=1 > /dev/null
