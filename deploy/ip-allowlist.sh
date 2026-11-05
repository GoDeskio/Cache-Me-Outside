#!/usr/bin/env bash
# IP allow-list for the published Valkey port (plan item 33).
# Valkey has no per-IP ACL, so this renders iptables rules for Docker's
# DOCKER-USER chain (the chain Docker leaves for operators).
#
#   ./ip-allowlist.sh                     show the saved list
#   ./ip-allowlist.sh set CIDR [CIDR...]  validate and save CMO_ALLOWED_CIDRS
#   ./ip-allowlist.sh clear               remove the saved list (open again)
#   ./ip-allowlist.sh rules               print the iptables commands
#   ./ip-allowlist.sh apply               run them (root; nothing runs otherwise)
# Rules live in their own chain CMO-ALLOW, so re-applying replaces them cleanly.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

cmo_valid_cidr() {
    local c="$1" ip bits o
    [[ "$c" == */* ]] || c="$c/32"
    ip="${c%/*}"; bits="${c#*/}"
    [[ "$bits" =~ ^[0-9]{1,2}$ ]] && (( bits <= 32 )) || return 1
    [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
    IFS=. read -ra o <<<"$ip"
    for x in "${o[@]}"; do (( 10#$x <= 255 )) || return 1; done
    [[ "$c" != 0.0.0.0/0 ]] || return 1
    printf '%s\n' "$c"
}

cmo_allow_save() {
    local file="$1" value="$2"
    touch "$file"
    if grep -q '^CMO_ALLOWED_CIDRS=' "$file"; then
        sed -i "s|^CMO_ALLOWED_CIDRS=.*|CMO_ALLOWED_CIDRS=${value}|" "$file"
    else
        printf 'CMO_ALLOWED_CIDRS=%s\n' "$value" >>"$file"
    fi
}

cmo_allow_rules() {
    local port="$1" list="$2" c
    echo "iptables -N CMO-ALLOW 2>/dev/null || iptables -F CMO-ALLOW"
    echo "iptables -C DOCKER-USER -p tcp --dport ${port} -j CMO-ALLOW 2>/dev/null || iptables -I DOCKER-USER -p tcp --dport ${port} -j CMO-ALLOW"
    echo "iptables -A CMO-ALLOW -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN"
    for c in ${list//,/ }; do echo "iptables -A CMO-ALLOW -s ${c} -j RETURN"; done
    echo "iptables -A CMO-ALLOW -j DROP"
}

if [[ "${CMO_ALLOW_LIB:-}" == 1 ]]; then return 0 2>/dev/null || exit 0; fi

file="$(cmo_env_path)"
saved="$( (grep '^CMO_ALLOWED_CIDRS=' "$file" 2>/dev/null || true) | tail -1 | cut -d= -f2-)"
port="$( (grep '^CMO_HOST_PORT=' "$file" 2>/dev/null || true) | tail -1 | cut -d= -f2-)"
port="${port:-6379}"

case "${1:-show}" in
    show) echo "${saved:-(empty: port ${port} is not restricted)}" ;;
    set)
        shift; [[ $# -gt 0 ]] || { echo "give at least one CIDR" >&2; exit 1; }
        out=()
        for c in "$@"; do v="$(cmo_valid_cidr "$c")" || { echo "bad CIDR: $c" >&2; exit 1; }; out+=("$v"); done
        joined="$(IFS=,; echo "${out[*]}")"
        cmo_allow_save "$file" "$joined"
        echo "saved: $joined (run '$0 apply' as root to enforce)" ;;
    clear) cmo_allow_save "$file" ""; echo "cleared (run 'iptables -F CMO-ALLOW' as root to open the port)" ;;
    rules) [[ -n "$saved" ]] || { echo "no list saved" >&2; exit 1; }; cmo_allow_rules "$port" "$saved" ;;
    apply)
        [[ -n "$saved" ]] || { echo "no list saved" >&2; exit 1; }
        [[ $EUID -eq 0 ]] || { echo "apply needs root" >&2; exit 1; }
        cmo_allow_rules "$port" "$saved" | bash -e
        echo "enforced on port ${port}: ${saved}" ;;
    *) sed -n 2,11p "$0"; exit 1 ;;
esac
