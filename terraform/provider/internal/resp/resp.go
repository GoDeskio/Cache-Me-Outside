// Package resp is a minimal RESP2 client: enough for AUTH, ACL SETUSER,
// ACL GETUSER and ACL DELUSER against Cache Me Outside data nodes.
package resp

import (
	"bufio"
	"crypto/tls"
	"errors"
	"fmt"
	"io"
	"net"
	"strconv"
	"strings"
	"time"
)

// ServerError is an error reply (-ERR ...).
type ServerError string

func (e ServerError) Error() string { return string(e) }

// Conn is one connection to one node.
type Conn struct {
	c  net.Conn
	rd *bufio.Reader
}

// Dial connects and, when user/password are set, authenticates.
func Dial(addr string, useTLS bool, user, password string, timeout time.Duration) (*Conn, error) {
	d := &net.Dialer{Timeout: timeout}
	var c net.Conn
	var err error
	if useTLS {
		c, err = tls.DialWithDialer(d, "tcp", addr, &tls.Config{MinVersion: tls.VersionTLS12})
	} else {
		c, err = d.Dial("tcp", addr)
	}
	if err != nil {
		return nil, err
	}
	conn := New(c)
	if password != "" {
		args := []string{"AUTH", password}
		if user != "" {
			args = []string{"AUTH", user, password}
		}
		if _, err := conn.Do(args...); err != nil {
			c.Close()
			return nil, fmt.Errorf("auth: %w", err)
		}
	}
	return conn, nil
}

// New wraps an existing connection (used by tests with net.Pipe).
func New(c net.Conn) *Conn { return &Conn{c: c, rd: bufio.NewReader(c)} }

func (c *Conn) Close() error { return c.c.Close() }

// Encode renders a command as a RESP array of bulk strings.
func Encode(args ...string) []byte {
	var b strings.Builder
	fmt.Fprintf(&b, "*%d\r\n", len(args))
	for _, a := range args {
		fmt.Fprintf(&b, "$%d\r\n%s\r\n", len(a), a)
	}
	return []byte(b.String())
}

// Do sends one command and reads one reply.
func (c *Conn) Do(args ...string) (any, error) {
	if _, err := c.c.Write(Encode(args...)); err != nil {
		return nil, err
	}
	return Read(c.rd)
}

// Read parses one reply: string, int64, nil, []any or ServerError.
func Read(rd *bufio.Reader) (any, error) {
	line, err := rd.ReadString('\n')
	if err != nil {
		return nil, err
	}
	if len(line) < 3 || !strings.HasSuffix(line, "\r\n") {
		return nil, errors.New("resp: malformed line")
	}
	kind, body := line[0], line[1:len(line)-2]
	switch kind {
	case '+':
		return body, nil
	case '-':
		return nil, ServerError(body)
	case ':':
		return strconv.ParseInt(body, 10, 64)
	case '$':
		n, err := strconv.Atoi(body)
		if err != nil {
			return nil, err
		}
		if n < 0 {
			return nil, nil
		}
		buf := make([]byte, n+2)
		if _, err := io.ReadFull(rd, buf); err != nil {
			return nil, err
		}
		return string(buf[:n]), nil
	case '*':
		n, err := strconv.Atoi(body)
		if err != nil {
			return nil, err
		}
		if n < 0 {
			return nil, nil
		}
		out := make([]any, n)
		for i := range out {
			if out[i], err = Read(rd); err != nil {
				return nil, err
			}
		}
		return out, nil
	}
	return nil, fmt.Errorf("resp: unknown type %q", kind)
}
