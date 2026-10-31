// Package cmo is the Cache Me Outside Go SDK. It parses CMO connection URLs
// and keeps keys inside the tenant prefix. It is stdlib-only; plug in any
// client (for example valkey-glide's Go client) through the KV interface.
package cmo

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"
)

// ConnInfo is a parsed connection URL.
type ConnInfo struct {
	Host     string
	Port     int
	TLS      bool
	Username string
	Password string
	HasAuth  bool
	DB       int
}

var schemes = map[string]bool{"redis": false, "rediss": true, "valkey": false, "valkeys": true}

// ParseURL parses redis[s]:// or valkey[s]:// URLs.
func ParseURL(raw string) (ConnInfo, error) {
	u, err := url.Parse(raw)
	if err != nil {
		return ConnInfo{}, fmt.Errorf("invalid url: %w", err)
	}
	tls, ok := schemes[u.Scheme]
	if !ok {
		return ConnInfo{}, fmt.Errorf("unsupported scheme: %q", u.Scheme)
	}
	if u.Hostname() == "" {
		return ConnInfo{}, errors.New("missing host")
	}
	ci := ConnInfo{Host: u.Hostname(), Port: 6379, TLS: tls}
	if p := u.Port(); p != "" {
		n, err := strconv.Atoi(p)
		if err != nil || n < 1 || n > 65535 {
			return ConnInfo{}, errors.New("bad port")
		}
		ci.Port = n
	}
	if path := strings.Trim(u.Path, "/"); path != "" {
		n, err := strconv.Atoi(path)
		if err != nil || n < 0 {
			return ConnInfo{}, errors.New("db must be a number")
		}
		ci.DB = n
	}
	if u.User != nil {
		ci.Username = u.User.Username()
		ci.Password, ci.HasAuth = u.User.Password()
	}
	return ci, nil
}

// KV is the subset of client operations TenantClient forwards.
type KV interface {
	Get(ctx context.Context, key string) (string, error)
	Set(ctx context.Context, key, value string) error
	Del(ctx context.Context, keys ...string) (int64, error)
}

// TenantClient prefixes keys so commands stay within the tenant ACL.
type TenantClient struct {
	Raw    KV
	Prefix string
}

// NewTenant validates the prefix and wraps a client.
func NewTenant(raw KV, prefix string) (*TenantClient, error) {
	if prefix == "" || strings.ContainsAny(prefix, "*?[] ") {
		return nil, errors.New("invalid prefix")
	}
	if !strings.HasSuffix(prefix, ":") {
		prefix += ":"
	}
	return &TenantClient{Raw: raw, Prefix: prefix}, nil
}

// Key returns k with the tenant prefix applied once.
func (t *TenantClient) Key(k string) string {
	if strings.HasPrefix(k, t.Prefix) {
		return k
	}
	return t.Prefix + k
}

func (t *TenantClient) Get(ctx context.Context, k string) (string, error) {
	return t.Raw.Get(ctx, t.Key(k))
}
func (t *TenantClient) Set(ctx context.Context, k, v string) error {
	return t.Raw.Set(ctx, t.Key(k), v)
}
func (t *TenantClient) Del(ctx context.Context, keys ...string) (int64, error) {
	p := make([]string, len(keys))
	for i, k := range keys {
		p[i] = t.Key(k)
	}
	return t.Raw.Del(ctx, p...)
}
