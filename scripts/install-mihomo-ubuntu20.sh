#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "please run as root: sudo bash scripts/install-mihomo-ubuntu20.sh" >&2
  exit 1
fi

REPO_API="https://api.github.com/repos/MetaCubeX/mihomo/releases?per_page=10"
INSTALL_PATH="${INSTALL_PATH:-/usr/local/bin/mihomo}"
MIRROR_PREFIX="${MIRROR_PREFIX:-https://gh-proxy.com/}"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

apt-get update
apt-get install -y ca-certificates curl gzip python3

case "$(uname -m)" in
  x86_64|amd64)
    ARCH="amd64"
    PREFERRED_PATTERN='mihomo-linux-amd64-compatible-.*\.gz$'
    FALLBACK_PATTERN='mihomo-linux-amd64-v[0-9.]+\.gz$'
    ;;
  aarch64|arm64)
    ARCH="arm64"
    PREFERRED_PATTERN='mihomo-linux-arm64-v[0-9.]+\.gz$'
    FALLBACK_PATTERN="${PREFERRED_PATTERN}"
    ;;
  armv7l|armhf)
    ARCH="armv7"
    PREFERRED_PATTERN='mihomo-linux-armv7-.*\.gz$'
    FALLBACK_PATTERN="${PREFERRED_PATTERN}"
    ;;
  i386|i686)
    ARCH="386"
    PREFERRED_PATTERN='mihomo-linux-386-.*\.gz$'
    FALLBACK_PATTERN="${PREFERRED_PATTERN}"
    ;;
  *)
    echo "unsupported architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

RELEASE_JSON="${TMP_DIR}/release.json"
curl -fsSL -H "User-Agent: u20vpn-installer" "${REPO_API}" -o "${RELEASE_JSON}"

ASSET_URL="$(
  python3 - "${RELEASE_JSON}" "${PREFERRED_PATTERN}" "${FALLBACK_PATTERN}" <<'PY'
import json
import re
import sys

release_path, preferred_pattern, fallback_pattern = sys.argv[1:4]
releases = json.load(open(release_path, "r", encoding="utf-8"))
stable_tag_rx = re.compile(r"^v\d+(\.\d+)+$")

# 只从最新的稳定版 (vX.Y.Z) 中选择资产，
# 跳过 draft、prerelease 和 Prerelease-Alpha 之类的标签。
for release in releases:
    if release.get("draft") or release.get("prerelease"):
        continue
    tag = release.get("tag_name", "")
    if not stable_tag_rx.match(tag):
        continue
    for pattern in (preferred_pattern, fallback_pattern):
        rx = re.compile(pattern)
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if rx.search(name):
                print(asset["browser_download_url"])
                raise SystemExit(0)

raise SystemExit("no stable mihomo linux asset found")
PY
)"

ARCHIVE="${TMP_DIR}/mihomo.gz"
BINARY="${TMP_DIR}/mihomo"

echo "downloading mihomo for linux/${ARCH}"
if ! curl -fL --retry 3 --retry-delay 2 "${ASSET_URL}" -o "${ARCHIVE}"; then
  echo "direct download failed, retrying via mirror ${MIRROR_PREFIX}"
  curl -fL --retry 3 --retry-delay 2 "${MIRROR_PREFIX}${ASSET_URL}" -o "${ARCHIVE}"
fi
gzip -dc "${ARCHIVE}" > "${BINARY}"
install -m 0755 "${BINARY}" "${INSTALL_PATH}"

mkdir -p /etc/mihomo/providers
chmod 700 /etc/mihomo

"${INSTALL_PATH}" -v
echo "installed: ${INSTALL_PATH}"

