package provider

import (
	"os"
	"testing"
	"time"

	"github.com/GoDeskio/Cache-Me-Outside/terraform/provider/internal/keys"
	"github.com/GoDeskio/Cache-Me-Outside/terraform/provider/internal/resp"
)

// TestLiveACL runs against a real server when CMO_TEST_ADDR is set (CI starts
// src/valkey-server). It checks the exact SETUSER args are accepted and enforced.
func TestLiveACL(t *testing.T) {
	addr := os.Getenv("CMO_TEST_ADDR")
	if addr == "" {
		t.Skip("CMO_TEST_ADDR not set")
	}
	a := &Admin{Nodes: []string{addr}, Timeout: 5 * time.Second}
	id, secret, err := keys.New()
	if err != nil {
		t.Fatal(err)
	}
	args, err := keys.SetUserArgs(id, keys.Hash(secret), "ro", "app:")
	if err != nil {
		t.Fatal(err)
	}
	if err := a.Each(args...); err != nil {
		t.Fatal(err)
	}
	defer a.Each("ACL", "DELUSER", id)

	c, err := resp.Dial(addr, false, id, secret, 5*time.Second)
	if err != nil {
		t.Fatalf("key cannot log in: %v", err)
	}
	defer c.Close()
	if _, err := c.Do("GET", "app:x"); err != nil {
		t.Fatalf("ro key cannot read its prefix: %v", err)
	}
	if _, err := c.Do("SET", "app:x", "1"); err == nil {
		t.Fatal("ro key could write")
	}
	if _, err := c.Do("GET", "other:x"); err == nil {
		t.Fatal("key escaped its prefix")
	}
	if m, err := a.Missing(id); err != nil || len(m) != 0 {
		t.Fatalf("missing=%v err=%v", m, err)
	}
}
