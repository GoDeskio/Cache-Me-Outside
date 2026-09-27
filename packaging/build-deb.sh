#!/usr/bin/env bash
# Build a Debian package from a built tree. Run `make -j` first, or let this
# script build. Output is dist/cache-me-outside_<version>_<arch>.deb.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if [[ ! -x src/valkey-server ]]; then
    make -j"$(nproc)"
fi

version="$(awk '/^#define VALKEY_VERSION / { gsub(/"/, "", $3); print $3; exit }' src/version.h)"
arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
deb_version="${version}-1"
name="cache-me-outside_${deb_version}_${arch}"

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

make -C src install PREFIX="${stage}/usr"

lib="${stage}/usr/lib/cache-me-outside"
share="${stage}/usr/share/cache-me-outside"
install -d -m 0755 "$lib" "$share" \
    "${stage}/lib/systemd/system" \
    "${stage}/etc/cache-me-outside" \
    "${stage}/DEBIAN"

install -m 0755 packaging/cmo-run.sh "${lib}/cmo-run"
install -m 0755 packaging/cmo-shutdown.sh "${lib}/cmo-shutdown"
install -m 0755 packaging/smoke-native.sh "${lib}/smoke-native.sh"
install -m 0755 deploy/docker-entrypoint.sh "${lib}/docker-entrypoint.sh"
install -m 0755 deploy/healthcheck.sh "${lib}/healthcheck.sh"
install -m 0644 deploy/valkey.conf "${stage}/etc/cache-me-outside/valkey.conf"
install -m 0644 packaging/environment.example "${share}/environment.example"
install -m 0644 packaging/systemd/cache-me-outside.service \
    "${stage}/lib/systemd/system/cache-me-outside.service"
install -m 0644 packaging/systemd/cache-me-outside-sentinel.service \
    "${stage}/lib/systemd/system/cache-me-outside-sentinel.service"
install -m 0755 packaging/debian/postinst "${stage}/DEBIAN/postinst"
install -m 0755 packaging/debian/prerm "${stage}/DEBIAN/prerm"

cat > "${stage}/DEBIAN/control" <<EOF
Package: cache-me-outside
Version: ${deb_version}
Section: database
Priority: optional
Architecture: ${arch}
Maintainer: GoDesk Cache-Me-Outside <cache-me-outside@users.noreply.github.com>
Depends: adduser
Description: Cache-Me-Outside cache server
 Valkey fork packaged for Debian and Ubuntu virtual machines.
 The default process bind is 127.0.0.1. Passwords are not included.
EOF

cat > "${stage}/DEBIAN/conffiles" <<EOF
/etc/cache-me-outside/valkey.conf
EOF

mkdir -p "${root}/dist"
dpkg-deb --root-owner-group --build "$stage" "${root}/dist/${name}.deb"
echo "built dist/${name}.deb"
