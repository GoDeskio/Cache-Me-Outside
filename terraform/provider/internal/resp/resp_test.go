package resp

import (
	"bufio"
	"net"
	"strings"
	"testing"
)

func TestEncode(t *testing.T) {
	if got := string(Encode("ACL", "GETUSER", "k")); got != "*3\r\n$3\r\nACL\r\n$7\r\nGETUSER\r\n$1\r\nk\r\n" {
		t.Fatalf("got %q", got)
	}
}

func TestRead(t *testing.T) {
	rd := bufio.NewReader(strings.NewReader("*3\r\n+OK\r\n:7\r\n*2\r\n$5\r\nflags\r\n$-1\r\n-ERR nope\r\n"))
	v, err := Read(rd)
	if err != nil {
		t.Fatal(err)
	}
	arr := v.([]any)
	if arr[0] != "OK" || arr[1] != int64(7) || arr[2].([]any)[0] != "flags" || arr[2].([]any)[1] != nil {
		t.Fatalf("got %#v", arr)
	}
	if _, err := Read(rd); err == nil || err.Error() != "ERR nope" {
		t.Fatalf("want server error, got %v", err)
	}
}

func TestDoOverPipe(t *testing.T) {
	a, b := net.Pipe()
	go func() {
		r := bufio.NewReader(b)
		if _, err := Read(r); err == nil {
			b.Write([]byte("+PONG\r\n"))
		}
	}()
	v, err := New(a).Do("PING")
	if err != nil || v != "PONG" {
		t.Fatalf("got %v %v", v, err)
	}
}
