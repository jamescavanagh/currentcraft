#!/usr/bin/env bash
# DataMesh host dependencies only. Target: Ubuntu 24.04 LTS.
# Review before running: sudo bash setup-datamesh-ubuntu.sh
set -Eeuo pipefail
trap 'printf "\nSetup stopped at line %s. Review the error above; no cleanup or data deletion was attempted.\n" "$LINENO" >&2' ERR

usage() {
  cat <<'EOF'
Usage: sudo bash setup-datamesh-ubuntu.sh
       bash setup-datamesh-ubuntu.sh --help

Installs host dependencies on Ubuntu 24.04 LTS:
  Python 3, venv, pip, Git, unzip, curl, CA certificates
  Docker Engine, containerd, Buildx, Docker Compose plugin

Uses Ubuntu repositories plus Docker's official signed APT repository.
Starts/enables Docker (including startup after reboot).
Requires internet access. APT may upgrade the named packages.

Does NOT install DataMesh, run pip, start project containers, install host
PostgreSQL/NATS, alter the firewall, add users to the docker group, remove
conflicting packages, or delete data. No full OS upgrade is performed.

Docker access remains via sudo unless you configure it separately.
Docker-group membership grants root-equivalent access; it is not enabled here.
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  '') ;;
  *) usage >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || { usage >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo 'Run with: sudo bash setup-datamesh-ubuntu.sh' >&2; exit 1; }
[[ -f /etc/os-release ]] || { echo 'Cannot identify this OS.' >&2; exit 1; }
# shellcheck disable=SC1091
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || {
  echo 'This installer supports Ubuntu 24.04 LTS only. No changes made.' >&2
  exit 1
}
[[ -d /run/systemd/system ]] && command -v systemctl >/dev/null || {
  echo 'Requires an Ubuntu host booted with systemd. No changes made.' >&2
  exit 1
}
ARCH=$(dpkg --print-architecture)
case "$ARCH" in
  amd64|arm64) ;;
  *) echo "Unsupported architecture for this installer: $ARCH. No changes made." >&2; exit 1 ;;
esac

# Do not silently replace a distro Docker/Podman/containerd installation.
conflicts=()
for pkg in docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc; do
  if [[ $(dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null || true) == 'install ok installed' ]]; then
    conflicts+=("$pkg")
  fi
done
if ((${#conflicts[@]})); then
  printf 'Existing packages require manual review before Docker CE installation: %s\n' "${conflicts[*]}" >&2
  echo 'Nothing was removed or changed. Keep existing workloads safe before choosing a migration.' >&2
  exit 1
fi

SOURCE=/etc/apt/sources.list.d/datamesh-docker.sources
KEY=/etc/apt/keyrings/datamesh-docker.asc
# Leave an existing Docker repository configuration untouched for manual review.
existing_sources=()
while IFS= read -r -d '' path; do
  [[ $path == "$SOURCE" ]] && continue
  if grep -Eq '^[[:space:]]*(deb.*https?://download\.docker\.com/linux/ubuntu|URIs:[[:space:]]*https?://download\.docker\.com/linux/ubuntu)' "$path"; then
    existing_sources+=("$path")
  fi
done < <(find /etc/apt -maxdepth 2 -type f \( -name '*.list' -o -name '*.sources' \) -print0)
if ((${#existing_sources[@]})); then
  printf 'Existing Docker repository configuration found: %s\n' "${existing_sources[*]}" >&2
  echo 'No changes made. Use that configuration or review it before running this installer.' >&2
  exit 1
fi
expected_source=$(cat <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: $ARCH
Signed-By: $KEY
EOF
)
if [[ -e $SOURCE ]] && [[ $(cat "$SOURCE") != "$expected_source" ]]; then
  echo "Existing $SOURCE differs from this installer's configuration. No changes made." >&2
  exit 1
fi
if [[ -e $SOURCE && ! -s $KEY ]]; then
  echo "Existing Docker source has a missing/empty key: $KEY. Repair it before rerunning." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
printf '\nInstalling Ubuntu host prerequisites...\n'
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl python3 python3-venv python3-pip git unzip

# Fetch via HTTPS before replacing any key; APT verifies repository signatures.
tmp_key=$(mktemp)
trap 'rm -f -- "${tmp_key:-}"' EXIT
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  --retry 3 --connect-timeout 20 --max-time 120 \
  https://download.docker.com/linux/ubuntu/gpg -o "$tmp_key"
grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$tmp_key" || {
  echo 'Docker key download was not an armored public key. Stopping.' >&2; exit 1;
}
install -d -m 0755 /etc/apt/keyrings
install -m 0644 "$tmp_key" "$KEY"
printf '%s\n' "$expected_source" > "$SOURCE"
chmod 0644 "$SOURCE"

printf '\nInstalling Docker Engine and Compose...\n'
apt-get update
apt-get install -y --no-install-recommends \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

printf '\nChecking host dependencies...\n'
python3 --version
python3 -m pip --version
python3 -c 'import venv; print("Python venv module available")'
git --version
docker --version
docker compose version
docker buildx version
docker info --format 'Docker daemon: {{.ServerVersion}}'
compose_version=$(docker compose version --short)
compose_version=${compose_version#v}
dpkg --compare-versions "$compose_version" ge 2.20.0 || {
  echo 'Docker Compose 2.20.0 or newer is required.' >&2; exit 1;
}

cat <<'EOF'

Host dependencies ready. No DataMesh containers were launched.

Next:
  1. Extract DataMesh into your regular user's home directory.
  2. Correct the 0.9.9 pyproject.toml package omissions before a Docker build:
       app.application.common*
       app.application.hfgt*
       app.infrastructure.hfgt*
     Add these to the existing setuptools package include list.
  3. From that extracted project directory, run:
       sudo python3 scripts/local_stack.py config
       sudo python3 scripts/local_stack.py up
       sudo python3 scripts/local_stack.py smoke

These sudo commands create root-owned local secrets/intake directories.
Do not mix privileged and unprivileged lifecycle runs without reviewing ownership.
Alternatively, configure Docker access deliberately before the first lifecycle run.
Do not use sudo pip. Use a user-owned virtual environment for Python development.
Keep references/private/ private. Keep generated secrets with the retained volumes.

Success here checks dependencies and daemon access, not image pulls or the
DataMesh end-to-end flow. The project's smoke test is a separate acceptance step.
EOF

