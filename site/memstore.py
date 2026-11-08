"""In-memory RESP stand-in so the local demo can browse keys without a server."""
import fnmatch
import socket
import threading


def enc(v):
    if v is None:
        return b"$-1\r\n"
    if isinstance(v, bool) or not isinstance(v, (int, str, bytes, list)):
        raise TypeError("unsupported reply")
    if isinstance(v, int):
        return b":%d\r\n" % v
    if isinstance(v, str):
        raw = v.encode()
        return b"+%s\r\n" % raw if b"\r" not in raw and b"\n" not in raw else b"$%d\r\n%s\r\n" % (len(raw), raw)
    if isinstance(v, bytes):
        return b"$%d\r\n%s\r\n" % (len(v), v)
    return b"*%d\r\n" % len(v) + b"".join(enc(x) for x in v)


class MemStore:
    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()

    def conn(self):
        import cmo_browse as browse
        left, right = socket.socketpair()
        threading.Thread(target=self._loop, args=(right, browse), daemon=True).start()
        return browse.Conn(None, None, None, None, sock=left)

    def _loop(self, sock, browse):
        stream = sock.makefile("rb")
        while True:
            try:
                cmd = browse._read(stream)
            except Exception:
                return
            if not isinstance(cmd, list) or not cmd:
                sock.sendall(b"-ERR empty\r\n")
                continue
            words = [x.decode() if isinstance(x, bytes) else str(x) for x in cmd]
            try:
                sock.sendall(enc(self._op(words)))
            except Exception:
                sock.sendall(b"-ERR failed\r\n")

    def _op(self, c):
        op = c[0].upper()
        with self.lock:
            if op == "SCAN":
                pat = c[3] if len(c) > 3 else "*"
                keys = [k.encode() for k in sorted(self.data) if fnmatch.fnmatch(k, pat)]
                return [b"0", keys]
            key = c[1] if len(c) > 1 else ""
            value = self.data.get(key)
            if op == "TYPE":
                if isinstance(value, bytes):
                    return "string"
                return "none"
            if op == "TTL":
                return -1
            if value is None:
                return None
            if op == "STRLEN":
                return len(value)
            if op == "GET":
                return value
        raise ValueError("unsupported")
