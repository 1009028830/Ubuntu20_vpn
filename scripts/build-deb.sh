#!/usr/bin/env bash
# 将 u20vpn 打包为自包含 .deb（适用于 Ubuntu 20.04 / focal）
# 用法: bash scripts/build-deb.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(grep -m1 '^version' "$PROJECT_DIR/pyproject.toml" | cut -d'"' -f2)"
ARCH="$(dpkg --print-architecture)"
VENV="$PROJECT_DIR/.venv"
SITE="$(ls -d "$VENV"/lib/python*/site-packages 2>/dev/null | head -n1 || true)"
BUILD="$PROJECT_DIR/deb-build"
STAGE="$BUILD/stage"
OUT="$PROJECT_DIR/dist"

echo "==> 打包 u20vpn $VERSION ($ARCH)"

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/lib/u20vpn" \
         "$STAGE/usr/share/u20vpn/examples" \
         "$STAGE/usr/share/doc/u20vpn" \
         "$OUT"

# 1. 项目包
cp -a "$PROJECT_DIR/src/u20vpn" "$STAGE/usr/lib/u20vpn/"

# 2. 依赖（从本地 venv 复制，目标机无需 pip 安装）
if [ -n "$SITE" ] && [ -d "$SITE" ]; then
    for dep in cryptography cffi pycparser; do
        if [ -d "$SITE/$dep" ]; then
            cp -a "$SITE/$dep" "$STAGE/usr/lib/u20vpn/"
        else
            echo "缺少依赖 $dep，请先在 .venv 中执行 pip install -e ." >&2
            exit 1
        fi
    done
    cp -a "$SITE"/cryptography-*.dist-info \
          "$SITE"/cffi-*.dist-info \
          "$SITE"/pycparser-*.dist-info \
          "$SITE"/_cffi_backend*.so \
          "$STAGE/usr/lib/u20vpn/" 2>/dev/null || true
else
    echo "未找到 .venv，请先创建虚拟环境并安装依赖" >&2
    exit 1
fi
# 清理字节码缓存
find "$STAGE/usr/lib/u20vpn" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$STAGE/usr/lib/u20vpn" -name '*.pyc' -delete

# 3. 入口脚本
cat > "$STAGE/usr/bin/u20vpn" <<'EOF'
#!/bin/sh
# u20vpn launcher — 使用私有 Python 依赖目录
export PYTHONPATH="/usr/lib/u20vpn${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m u20vpn "$@"
EOF
chmod 755 "$STAGE/usr/bin/u20vpn"

# 4. 示例配置、systemd 服务与辅助脚本（排除打包脚本本身）
cp -a "$PROJECT_DIR/examples/." "$STAGE/usr/share/u20vpn/examples/" 2>/dev/null || true
for f in "$PROJECT_DIR"/scripts/*.sh "$PROJECT_DIR"/scripts/*.py; do
    [ -f "$f" ] || continue
    [ "$(basename "$f")" = "build-deb.sh" ] && continue
    cp -a "$f" "$STAGE/usr/share/u20vpn/examples/"
done

# 5. 使用说明文档
cp -a "$PROJECT_DIR/docs/u20vpn-deb安装使用说明.md" "$STAGE/usr/share/doc/u20vpn/" 2>/dev/null || true

# 5. control
cat > "$STAGE/DEBIAN/control" <<EOF
Package: u20vpn
Version: $VERSION
Section: net
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.8), iproute2, iptables, curl, ca-certificates
Maintainer: xkme <xkme@localhost>
Description: Minimal encrypted TUN/UDP VPN for Ubuntu 20.04
 u20vpn is a minimal layer-3 VPN tunnel using Linux TUN devices,
 UDP transport and ChaCha20-Poly1305 session encryption.
 .
 Self-contained package: private Python dependencies are installed
 under /usr/lib/u20vpn, no system python3-cryptography required.
EOF

# 6. 构建
dpkg-deb --build --root-owner-group "$STAGE" "$OUT/u20vpn_${VERSION}_${ARCH}.deb"

echo "==> 已生成: $OUT/u20vpn_${VERSION}_${ARCH}.deb"
