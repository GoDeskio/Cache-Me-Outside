#!/usr/bin/env python3
"""Console sign-in defaults: self-hosted Authentik over OIDC.

Roles are the four from PR #45 (viewer, developer, admin, owner). An IdP
group never grants owner. That grant stays manual, which is the same rule
as map_sso_groups in that change.
"""

ROLES = ("viewer", "developer", "admin", "owner")

DEFAULTS = {
    "provider": "authentik",
    "protocol": "oidc",
    "hosted": "self",
    "issuer": "https://authentik.internal/application/o/cache-me-outside/",
    "groups_claim": "groups",
    "roles": list(ROLES),
}

# Authentik group name -> console role. No group maps to owner.
DEFAULT_GROUP_MAP = {
    "cache-viewers": "viewer",
    "cache-developers": "developer",
    "cache-admins": "admin",
}


def role_for_groups(groups, mapping=None):
    """Highest role any group maps to, or None. Owner from a group is ignored."""
    mapping = DEFAULT_GROUP_MAP if mapping is None else mapping
    best = None
    for g in groups or []:
        role = mapping.get(g)
        if role not in ROLES or role == "owner":
            continue
        if best is None or ROLES.index(role) > ROLES.index(best):
            best = role
    return best
