"""Near cache for Cache Me Outside clients (REA plan item 49).

Keeps recently read values in process memory and drops them when the server
says they changed, using RESP3 CLIENT TRACKING (default mode: the server
remembers which keys this connection read). Stdlib only, single connection.

    nc = NearCache("db.example", 6379, password=os.environ["CMO_PASSWORD"])
    nc.get("user:1")   # network
    nc.get("user:1")   # local, until another client writes user:1
"""
import collections
import socket
import ssl
import threading


class RespError(Exception):
    pass


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        b = a if isinstance(a, bytes) else str(a).encode()
        out.append(b"$%d\r\n%s\r\n" % (len(b), b))
    return b"".join(out)


class Push(list):
    """A RESP3 out-of-band push message."""


def read(f):
    line = f.readline()
    if not line:
        raise ConnectionError("connection closed")
    t, rest = line[:1], line[1:-2]
    if t in (b"+",):
        return rest.decode()
    if t in (b"-", b"!"):
        if t == b"!":
            rest = f.read(int(rest) + 2)[:-2]
        raise RespError(rest.decode(errors="replace"))
    if t == b":":
        return int(rest)
    if t == b",":
        return float(rest)
    if t == b"#":
        return rest == b"t"
    if t == b"_":
        return None
    if t in (b"$", b"="):
        n = int(rest)
        return None if n < 0 else f.read(n + 2)[:-2]
    if t in (b"*", b"~", b">"):
        n = int(rest)
        items = [read(f) for _ in range(max(n, 0))]
        return Push(items) if t == b">" else items
    if t in (b"%", b"|"):
        n = int(rest)
        d = {}
        for _ in range(n):
            k = read(f)
            d[k if not isinstance(k, list) else tuple(k)] = read(f)
        if t == b"|":  # attribute: skip, return the real reply
            return read(f)
        return d
    raise RespError("unknown RESP type %r" % t)


class NearCache:
    def __init__(self, host, port=6379, user="default", password=None,
                 tls=False, max_keys=10000, timeout=5.0, sock=None):
        self.max_keys = max_keys
        self._local = collections.OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = self.invalidations = 0
        if sock is None:
            sock = socket.create_connection((host, port), timeout=timeout)
            if tls:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        self._sock = sock
        self._f = sock.makefile("rb")
        hello = ["HELLO", "3"] + (["AUTH", user, password] if password else [])
        self._call(*hello)
        self._call("CLIENT", "TRACKING", "ON")

    def _handle_push(self, msg):
        kind = msg[0].decode() if isinstance(msg[0], bytes) else msg[0]
        if kind != "invalidate":
            return
        keys = msg[1] if len(msg) > 1 else None
        with self._lock:
            if keys is None:  # server flushed: drop everything
                self._local.clear()
            else:
                for k in keys:
                    self._local.pop(k, None)
            self.invalidations += 1

    def _call(self, *args):
        self._sock.sendall(encode(*args))
        while True:
            r = read(self._f)
            if isinstance(r, Push):
                self._handle_push(r)
                continue
            return r

    def poll(self):
        """Apply invalidations that arrived while idle (non-blocking)."""
        self._sock.setblocking(False)
        try:
            peek = self._sock.recv(1, socket.MSG_PEEK)
        except (BlockingIOError, ssl.SSLWantReadError):
            peek = b""
        finally:
            self._sock.setblocking(True)
        if peek == b">":
            self._handle_push(read(self._f))
            self.poll()

    def get(self, key):
        k = key if isinstance(key, bytes) else str(key).encode()
        self.poll()
        with self._lock:
            if k in self._local:
                self._local.move_to_end(k)
                self.hits += 1
                return self._local[k]
        self.misses += 1
        v = self._call("GET", k)
        with self._lock:
            self._local[k] = v
            while len(self._local) > self.max_keys:
                self._local.popitem(last=False)
        return v

    def set(self, key, value, *opts):
        k = key if isinstance(key, bytes) else str(key).encode()
        with self._lock:
            self._local.pop(k, None)
        return self._call("SET", k, value, *opts)

    def execute(self, *args):
        """Any other command, uncached."""
        return self._call(*args)

    def close(self):
        self._f.close()
        self._sock.close()
