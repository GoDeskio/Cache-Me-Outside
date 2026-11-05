#!/usr/bin/env python3
"""Team roles for the console and management API (plan item 35).

Roles (each includes the ones below it):
  owner    billing, delete team, manage members, everything else
  admin    create/delete databases, manage API keys and members (not owners)
  developer  read/write data, rotate own keys, view metrics
  viewer   metrics, config and audit log, read-only

SSO: `map_sso_groups` turns IdP group claims (OIDC `groups` or a SAML
attribute) into a role, using a per-team mapping. Plugging a SAML/OIDC IdP into
the console login itself is a follow-up, and needs Dustin to pick the IdP.
"""
ROLES = ["viewer", "developer", "admin", "owner"]
PERMS = {
    "viewer": {"metrics.read", "config.read", "audit.read", "db.list"},
    "developer": {"data.read", "data.write", "keys.rotate_own"},
    "admin": {"db.create", "db.delete", "db.scale", "keys.manage", "members.manage", "backups.restore"},
    "owner": {"billing.manage", "team.delete", "owners.manage"},
}


def rank(role):
    if role not in ROLES:
        raise ValueError("unknown role %r" % role)
    return ROLES.index(role)


def perms(role):
    out = set()
    for r in ROLES[: rank(role) + 1]:
        out |= PERMS[r]
    return out


def can(role, perm):
    return perm in perms(role)


def can_assign(actor, target_current, target_new, owners_left):
    """May `actor` change a member from target_current to target_new (None = remove)?"""
    top = max(rank(target_current), rank(target_new) if target_new else -1)
    if top >= rank("owner") and actor != "owner":
        return False, "Only an owner can add or remove owners."
    if actor not in ("owner", "admin"):
        return False, "Only admins and owners manage members."
    if target_current == "owner" and target_new != "owner" and owners_left <= 1:
        return False, "A team must keep at least one owner."
    return True, ""


def map_sso_groups(groups, mapping, default=None):
    """Highest role any of the user's groups maps to; `default` if none match."""
    best = None
    for g in groups or []:
        r = mapping.get(g)
        if r and (best is None or rank(r) > rank(best)):
            best = r
    if best == "owner":
        best = "admin"  # owners are granted by hand, never by an IdP group
    return best or default
