# PostgreSQL 18 service on Ubuntu

`scripts/deploy_postgres_ubuntu.sh` provisions a **dedicated** PostgreSQL 18 cluster on an Ubuntu host with systemd. It does not deploy the Python application or run migrations.

## Run

```bash
bash scripts/deploy_postgres_ubuntu.sh --dry-run
sudo bash scripts/deploy_postgres_ubuntu.sh
# Optional, instead of the command above:
sudo bash scripts/deploy_postgres_ubuntu.sh --pgvector
```

Supported release codenames: jammy (22.04), noble (24.04), resolute (26.04), stonking (26.10). Requires network access to Ubuntu and the official PostgreSQL PGDG APT repositories. The script checks the PGDG signing-key fingerprint and installs the latest available PostgreSQL **18** patch packages, not a frozen patch build. Upgrades therefore follow APT. Review the plan and take backups before rerunning on a populated host.

- Cluster: `18/datamesh`; systemd unit: `postgresql@18-datamesh.service`.
- Address: `127.0.0.1:5433` (first install can use `--port 5543`). No remote access or firewall changes.
- Database `datamesh`, login `datamesh_app`. Login has no superuser, role-creation, database-creation, replication or RLS-bypass powers; owns only its application database.
- TCP uses SCRAM; local PostgreSQL administration uses OS peer identity.
- Generated credentials and `DATAMESH_PG_DSN`: `/etc/datamesh/postgres.env`, root-owned 0600 in a 0700 directory, **outside the repository**. No password printed or put in command-line arguments.
- Reruns reuse the password/port. The dedicated cluster's configuration is script-managed and the service is restarted. Unmanaged existing `18/datamesh` clusters and initial role/database conflicts are refused.
- Installing Ubuntu packages may also create/start the distro's default `main` cluster, and package maintenance may restart services. The script does not explicitly configure/delete an existing `main` cluster. Inspect `pg_lsclusters` after installation.
- The optional extension is installed by the administrator, not by granting the application superuser rights.

## Python migrations and acceptance

Create a Python environment and install the repo's PostgreSQL extra:

```bash
python3 -m venv .venv
.venv/bin/pip install '.[postgres]'
```

On the same host, load the protected credentials only for the process that needs them:

```bash
sudo bash -c 'set -a; . /etc/datamesh/postgres.env; set +a; exec "$@"' bash \
  "$PWD/.venv/bin/python" -c \
  'import os; from app.infrastructure.persistence import build_postgres; build_postgres(os.environ["DATAMESH_PG_DSN"]); print("Migrations applied")'
```

If provisioned with `--pgvector`, pass `pgvector=True` to `build_postgres`. Test the repository in an isolated database before use. `PostgresContract` creates and drops throwaway schemas:

```bash
sudo bash -c 'set -a; . /etc/datamesh/postgres.env; set +a; exec "$@"' bash \
  "$PWD/.venv/bin/python" -m unittest tests.test_persistence.PostgresContract -v
```

Do not grant root to a production worker just to read this file. Provision the runtime secret through the service's restricted environment/credential configuration; do not copy it into private references, Git, shell history or a zip. The commands above are for initial administrator setup only.

## Operations

```bash
sudo systemctl status postgresql@18-datamesh.service
sudo journalctl -u postgresql@18-datamesh.service --since today
pg_lsclusters
sudo -u postgres psql --cluster 18/datamesh -d datamesh -c 'SELECT version();'
```

Configure tested backups and restore drills, monitoring, storage capacity, patch policy and host access before production. This is a single-host development/integration service, **not HA or a complete production hardening solution**. No teardown or automatic cluster deletion is provided.

## Validation in this release

Bash syntax, help/dry-run and invalid-argument checks are automated. The Ubuntu APT/systemd installation itself has **not** been executed in the sandbox; it has no internet access or PostgreSQL service. Passing these checks is not proof of successful host deployment.

Install reference: https://postgresql.org/download/linux/ubuntu/
