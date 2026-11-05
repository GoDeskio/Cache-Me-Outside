package provider

import (
	"fmt"
	"strings"
	"time"

	"github.com/GoDeskio/Cache-Me-Outside/terraform/provider/internal/resp"
)

// Admin talks to every data node so a key works wherever a client lands
// (same fan-out rule as deploy/api-key.sh).
type Admin struct {
	Nodes    []string
	TLS      bool
	User     string
	Password string
	Timeout  time.Duration
	dial     func(addr string) (Doer, error)
}

// Doer is one node connection.
type Doer interface {
	Do(args ...string) (any, error)
	Close() error
}

func (a *Admin) conn(addr string) (Doer, error) {
	if a.dial != nil {
		return a.dial(addr)
	}
	t := a.Timeout
	if t == 0 {
		t = 10 * time.Second
	}
	return resp.Dial(addr, a.TLS, a.User, a.Password, t)
}

// Each runs args on every node and returns per-node errors joined.
func (a *Admin) Each(args ...string) error {
	var failed []string
	for _, n := range a.Nodes {
		c, err := a.conn(n)
		if err != nil {
			failed = append(failed, fmt.Sprintf("%s: %v", n, err))
			continue
		}
		if _, err := c.Do(args...); err != nil {
			failed = append(failed, fmt.Sprintf("%s: %v", n, err))
		}
		c.Close()
	}
	if len(failed) > 0 {
		return fmt.Errorf("%s failed on %d of %d nodes: %s", strings.Join(args[:2], " "), len(failed), len(a.Nodes), strings.Join(failed, "; "))
	}
	return nil
}

// Missing returns nodes where the ACL user does not exist.
func (a *Admin) Missing(id string) ([]string, error) {
	var missing []string
	for _, n := range a.Nodes {
		c, err := a.conn(n)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", n, err)
		}
		v, err := c.Do("ACL", "GETUSER", id)
		c.Close()
		if err != nil {
			return nil, fmt.Errorf("%s: %w", n, err)
		}
		if v == nil {
			missing = append(missing, n)
		}
	}
	return missing, nil
}
