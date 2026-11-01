package provider

import (
	"errors"
	"strings"
	"testing"
)

type fakeNode struct {
	users map[string]bool
	down  bool
}

type fakeConn struct{ n *fakeNode }

func (f fakeConn) Close() error { return nil }
func (f fakeConn) Do(args ...string) (any, error) {
	switch strings.Join(args[:2], " ") {
	case "ACL SETUSER":
		f.n.users[args[2]] = true
		return "OK", nil
	case "ACL DELUSER":
		delete(f.n.users, args[2])
		return int64(1), nil
	case "ACL GETUSER":
		if f.n.users[args[2]] {
			return []any{"flags"}, nil
		}
		return nil, nil
	}
	return nil, errors.New("ERR unknown")
}

func fakeAdmin(nodes map[string]*fakeNode) *Admin {
	a := &Admin{}
	for k := range nodes {
		a.Nodes = append(a.Nodes, k)
	}
	a.dial = func(addr string) (Doer, error) {
		if nodes[addr].down {
			return nil, errors.New("connection refused")
		}
		return fakeConn{nodes[addr]}, nil
	}
	return a
}

func TestFanOutAndMissing(t *testing.T) {
	n1, n2 := &fakeNode{users: map[string]bool{}}, &fakeNode{users: map[string]bool{}}
	a := fakeAdmin(map[string]*fakeNode{"a:6379": n1, "b:6379": n2})
	if err := a.Each("ACL", "SETUSER", "key-0123456789ab"); err != nil {
		t.Fatal(err)
	}
	if !n1.users["key-0123456789ab"] || !n2.users["key-0123456789ab"] {
		t.Fatal("not on every node")
	}
	delete(n2.users, "key-0123456789ab") // node restarted
	m, err := a.Missing("key-0123456789ab")
	if err != nil || len(m) != 1 || m[0] != "b:6379" {
		t.Fatalf("missing=%v err=%v", m, err)
	}
}

func TestEachReportsDownNode(t *testing.T) {
	a := fakeAdmin(map[string]*fakeNode{"a:6379": {users: map[string]bool{}}, "b:6379": {down: true}})
	err := a.Each("ACL", "SETUSER", "key-0123456789ab")
	if err == nil || !strings.Contains(err.Error(), "1 of 2") || !strings.Contains(err.Error(), "b:6379") {
		t.Fatalf("got %v", err)
	}
}
