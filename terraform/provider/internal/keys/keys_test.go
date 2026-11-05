package keys

import (
	"strings"
	"testing"
)

func TestSetUserArgsMatchesRenderer(t *testing.T) {
	h := Hash("s3cret")
	args, err := SetUserArgs("key-0123456789ab", h, "ro", "app:")
	if err != nil {
		t.Fatal(err)
	}
	// Same rule text docker-entrypoint.sh --render-keys prints after "user <id>".
	want := "on #" + h + " resetchannels resetkeys ~app:* -@all +@read +ping +auth +hello -@dangerous -@admin"
	if got := strings.Join(args[4:], " "); got != want {
		t.Fatalf("\n got %s\nwant %s", got, want)
	}
	if args[3] != "reset" {
		t.Fatal("must reset first so updates drop old rules")
	}
}

func TestValidation(t *testing.T) {
	h := Hash("x")
	for _, c := range []struct{ id, scope, prefix string }{
		{"key-XYZ", "ro", ""}, {"key-0123456789ab", "admin", ""}, {"key-0123456789ab", "rw", "a b"},
		{"key-0123456789ab", "rw", strings.Repeat("a", 65)},
	} {
		if _, err := SetUserArgs(c.id, h, c.scope, c.prefix); err == nil {
			t.Fatalf("accepted %+v", c)
		}
	}
}

func TestNew(t *testing.T) {
	id, secret, err := New()
	if err != nil || !ValidID(id) || len(secret) != 48 {
		t.Fatalf("%s %d %v", id, len(secret), err)
	}
}
