#!/usr/bin/env python3
"""Compliance pack: automated evidence for SOC 2 / HIPAA technical controls (plan item 36).

Checks a valkey.conf (and optional live CONFIG GET output) against the
controls below and writes a JSON evidence record. Process controls (policies,
access reviews, vendor management) are listed as manual and need an owner.
This produces evidence; it is not an audit or a certification.
"""
import datetime
import hashlib
import json
import sys

CHECKS = [
    # id, control refs, description, conf key, predicate
    ("ENC-TRANSIT", "SOC2 CC6.7; HIPAA 164.312(e)(1)", "TLS on and plaintext port off",
     lambda c: c.get("tls-port", "0") != "0" and c.get("port") == "0"),
    ("ENC-REPL", "SOC2 CC6.7", "Replication over TLS", lambda c: c.get("tls-replication") == "yes"),
    ("AUTH-DEFAULT", "SOC2 CC6.1; HIPAA 164.312(d)", "Default user disabled or ACL file used",
     lambda c: "aclfile" in c or c.get("user default", "").startswith("off")),
    ("AUTH-PROTECTED", "SOC2 CC6.6", "Protected mode on", lambda c: c.get("protected-mode", "yes") == "yes"),
    ("AUDIT-LOG", "SOC2 CC7.2; HIPAA 164.312(b)", "Command log / slowlog enabled",
     lambda c: int(c.get("slowlog-max-len", "128")) > 0),
    ("BACKUP", "SOC2 A1.2; HIPAA 164.308(a)(7)", "AOF persistence on", lambda c: c.get("appendonly") == "yes"),
    ("DANGEROUS-CMDS", "SOC2 CC6.8", "Debug/module commands not enabled",
     lambda c: c.get("enable-debug-command", "no") == "no" and c.get("enable-module-command", "no") == "no"),
]
MANUAL = ["Security policies approved (CC1, CC5)", "Quarterly access reviews (CC6.2)",
          "Vendor/BAA register (HIPAA 164.308(b))", "Incident response test (CC7.4)",
          "Risk assessment (CC3; HIPAA 164.308(a)(1))", "Employee security training (CC1.4)"]


def parse_conf(text):
    c = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        k = parts[0].lower()
        v = parts[1].strip().strip('"') if len(parts) > 1 else ""
        if k == "user":
            name, _, rest = v.partition(" ")
            c["user " + name] = rest
        else:
            c[k] = v
    return c


def evaluate(conf_text, now=None):
    c = parse_conf(conf_text)
    res = [{"id": i, "controls": refs, "check": d, "pass": bool(p(c))} for i, refs, d, p in CHECKS]
    return {"generated": (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(),
            "config_sha256": hashlib.sha256(conf_text.encode()).hexdigest(),
            "automated": res, "passed": sum(r["pass"] for r in res), "total": len(res),
            "manual": [{"control": m, "status": "needs owner"} for m in MANUAL]}


if __name__ == "__main__":
    print(json.dumps(evaluate(open(sys.argv[1]).read()), indent=2))
