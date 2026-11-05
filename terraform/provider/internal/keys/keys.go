// Package keys mirrors deploy/docker-entrypoint.sh's key renderer so keys made
// by Terraform get exactly the same ACL as keys made by deploy/api-key.sh.
package keys

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"regexp"
)

var (
	idRe     = regexp.MustCompile(`^key-[0-9a-f]{12}$`)
	prefixRe = regexp.MustCompile(`^[A-Za-z0-9:_.-]{0,64}$`)
)

// Rules returns the ACL category rules for a scope.
func Rules(scope string) ([]string, error) {
	switch scope {
	case "ro":
		return []string{"-@all", "+@read", "+ping", "+auth", "+hello", "-@dangerous", "-@admin"}, nil
	case "rw":
		return []string{"-@all", "+@read", "+@write", "+ping", "+auth", "+hello", "-@dangerous", "-@admin"}, nil
	}
	return nil, errors.New(`scope must be "ro" or "rw"`)
}

// ValidPrefix reports whether a key-name prefix is allowed ("" = whole keyspace).
func ValidPrefix(p string) bool { return prefixRe.MatchString(p) }

// ValidID reports whether id looks like key-<12hex>.
func ValidID(id string) bool { return idRe.MatchString(id) }

// Hash is the hex SHA-256 Valkey stores (#hash) for a password.
func Hash(secret string) string {
	s := sha256.Sum256([]byte(secret))
	return hex.EncodeToString(s[:])
}

// New makes a fresh id and secret using the same sizes as api-key.sh.
func New() (id, secret string, err error) {
	b := make([]byte, 30)
	if _, err = rand.Read(b); err != nil {
		return "", "", err
	}
	return "key-" + hex.EncodeToString(b[:6]), hex.EncodeToString(b[6:]), nil
}

// SetUserArgs builds the full ACL SETUSER command.
func SetUserArgs(id, hash, scope, prefix string) ([]string, error) {
	if !ValidID(id) {
		return nil, errors.New("bad key id")
	}
	if !prefixRe.MatchString(prefix) {
		return nil, errors.New("prefix must be 0-64 of A-Z a-z 0-9 : _ . -")
	}
	if len(hash) != 64 {
		return nil, errors.New("bad hash")
	}
	rules, err := Rules(scope)
	if err != nil {
		return nil, err
	}
	args := []string{"ACL", "SETUSER", id, "reset", "on", "#" + hash, "resetchannels", "resetkeys", "~" + prefix + "*"}
	return append(args, rules...), nil
}
