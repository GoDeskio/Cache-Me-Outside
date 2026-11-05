#!/usr/bin/env python3
"""Custom server-side procedures (plan item 9).

Tenants upload Lua function libraries; we load them with FUNCTION LOAD under a
per-tenant library name. Valkey already sandboxes Lua (no io/os/require/debug);
this adds a second check before load: a size limit, no dynamic code loading,
tenant-prefixed function names, and every registered function must be declared
so the tenant ACL (namespaces, #37) can allow FCALL on its own functions only.
Native C modules are not offered to tenants.
"""
import re

MAX_BYTES = 64 * 1024
NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
BANNED = re.compile(r"\b(loadstring|load|dofile|loadfile|require|setfenv|getfenv|rawset|rawget|"
                    r"setmetatable|getmetatable|debug|os|io|collectgarbage|package|_G)\b")
REG = re.compile(r"""server\.register_function\s*(?:\(\s*['"]|\{[^}]*?function_name\s*=\s*['"])([^'"]+)""")


def _strip_lua(src):
    src = re.sub(r"--\[\[.*?\]\]", " ", src, flags=re.S)
    src = re.sub(r"--[^\n]*", " ", src)
    return re.sub(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", '""', src)


def prepare(tenant, lib, src):
    """Validate and return (FUNCTION LOAD argv, [function names])."""
    if not NAME.match(tenant) or not NAME.match(lib):
        raise ValueError("bad tenant or library name")
    if len(src.encode()) > MAX_BYTES:
        raise ValueError("library over 64 KB")
    code = _strip_lua(src)
    m = BANNED.search(code)
    if m:
        raise ValueError("not allowed in procedures: %s" % m.group(1))
    if "[[" in code or "#!" in src.split("\n", 1)[0]:
        raise ValueError("use plain Lua without a shebang or long strings")
    fns = REG.findall(src)
    if not fns:
        raise ValueError("library registers no functions")
    pre = tenant + "_"
    for f in fns:
        if not f.startswith(pre) or not NAME.match(f):
            raise ValueError("function %r must start with %r" % (f, pre))
    body = "#!lua name=%s_%s\n%s" % (tenant, lib, src)
    return ["FUNCTION", "LOAD", "REPLACE", body], fns


def acl_rules(fns):
    """ACL additions so the tenant user may FCALL only its own functions."""
    return ["+fcall", "+fcall_ro"]  # key access stays limited to the tenant prefix


def call(fn, keys, args, tenant):
    if not fn.startswith(tenant + "_"):
        raise PermissionError("not your function")
    if any(not k.startswith(tenant + ":") for k in keys):
        raise PermissionError("keys must be in your namespace")
    return ["FCALL", fn, str(len(keys))] + list(keys) + list(args)
