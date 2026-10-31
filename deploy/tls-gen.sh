#!/bin/sh
# Make a private CA plus server and client certs for home-lab TLS (plan item 27).
# Usage: deploy/tls-gen.sh <out-dir> [server-dns-name ...]
# Keys are written 0600. Use a real CA for anything reachable from the internet.
set -eu
out="${1:?usage: tls-gen.sh <out-dir> [dns ...]}"; shift
[ $# -gt 0 ] || set -- localhost
mkdir -p "$out"; umask 077
san=""; for n in "$@"; do san="${san}${san:+,}DNS:${n}"; done
san="${san},IP:127.0.0.1"
[ -f "$out/ca.key" ] || {
  openssl genrsa -out "$out/ca.key" 4096 2>/dev/null
  openssl req -x509 -new -key "$out/ca.key" -sha256 -days 3650 -subj "/CN=Cache-Me-Outside CA" -out "$out/ca.crt"
}
mk() {
  openssl genrsa -out "$out/$1.key" 2048 2>/dev/null
  openssl req -new -key "$out/$1.key" -subj "/CN=$2" -out "$out/$1.csr"
  printf 'subjectAltName=%s\nextendedKeyUsage=%s\n' "$3" "$4" > "$out/$1.ext"
  openssl x509 -req -in "$out/$1.csr" -CA "$out/ca.crt" -CAkey "$out/ca.key" -CAcreateserial \
    -days 825 -sha256 -extfile "$out/$1.ext" -out "$out/$1.crt" 2>/dev/null
  rm -f "$out/$1.csr" "$out/$1.ext"
}
mk server "$1" "$san" serverAuth,clientAuth
mk client cmo-client "DNS:cmo-client" clientAuth
chmod 644 "$out"/*.crt
echo "Wrote $out/{ca,server,client}.{crt,key}"
