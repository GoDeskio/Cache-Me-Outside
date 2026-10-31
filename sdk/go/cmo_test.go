package cmo

import (
	"context"
	"reflect"
	"testing"
)

func TestParse(t *testing.T) {
	ci, err := ParseURL("rediss://acme:p%40ss@cache.example:6380/2")
	want := ConnInfo{"cache.example", 6380, true, "acme", "p@ss", true, 2}
	if err != nil || ci != want {
		t.Fatalf("got %+v %v", ci, err)
	}
	ci, _ = ParseURL("redis://h")
	if ci.TLS || ci.HasAuth || ci.Port != 6379 {
		t.Fatalf("got %+v", ci)
	}
	for _, bad := range []string{"http://h", "redis://", "redis://h/x", "redis://h:99999"} {
		if _, err := ParseURL(bad); err == nil {
			t.Errorf("%s: expected error", bad)
		}
	}
}

type fake struct{ log [][]string }

func (f *fake) Get(_ context.Context, k string) (string, error) {
	f.log = append(f.log, []string{"get", k})
	return "", nil
}
func (f *fake) Set(_ context.Context, k, v string) error {
	f.log = append(f.log, []string{"set", k, v})
	return nil
}
func (f *fake) Del(_ context.Context, ks ...string) (int64, error) {
	f.log = append(f.log, append([]string{"del"}, ks...))
	return int64(len(ks)), nil
}

func TestTenant(t *testing.T) {
	f := &fake{}
	c, err := NewTenant(f, "acme")
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	_ = c.Set(ctx, "a", "1")
	_, _ = c.Get(ctx, "acme:a")
	_, _ = c.Del(ctx, "b", "acme:c")
	want := [][]string{{"set", "acme:a", "1"}, {"get", "acme:a"}, {"del", "acme:b", "acme:c"}}
	if !reflect.DeepEqual(f.log, want) {
		t.Fatalf("got %v", f.log)
	}
	for _, p := range []string{"", "a*", "a b"} {
		if _, err := NewTenant(f, p); err == nil {
			t.Errorf("%q: expected error", p)
		}
	}
}
