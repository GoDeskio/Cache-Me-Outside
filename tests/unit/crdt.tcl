# Active-active CRDT. The merge laws, clock skew, and tombstone GC predicate
# are checked by src/crdt/merge_test. This file checks that peers converge.

set ::crdt_root [file normalize [file join [file dirname [info script]] .. ..]]
exec cc -std=gnu11 -O2 -Wall -I [file join $::crdt_root src/crdt] \
    -o [file join $::crdt_root src/crdt/merge_test] \
    [file join $::crdt_root src/crdt/merge_test.c] \
    [file join $::crdt_root src/crdt/merge.c] \
    [file join $::crdt_root src/crdt/hlc.c]

test {CRDT merge is commutative, associative, idempotent; clock skew and GC} {
    exec [file join $::crdt_root src/crdt/merge_test]
} {OK}

proc crdt_wait_connected {level n} {
    wait_for_condition 50 100 {
        [string match "*peers_connected:$n*" [r $level crdt.info]]
    } else {
        fail "peer links did not connect: [r $level crdt.info]"
    }
}

proc crdt_wait_same_digest {} {
    wait_for_condition 50 100 {
        [r -2 debug digest] eq [r -1 debug digest] && [r -1 debug digest] eq [r debug digest]
    } else {
        fail "digests diverged: [r -2 debug digest] [r -1 debug digest] [r debug digest]"
    }
}

start_server {tags {external:skip} overrides {crdt-enabled yes crdt-region-id 1 save ""}} {
start_server {overrides {crdt-enabled yes crdt-region-id 2 save ""}} {
start_server {overrides {crdt-enabled yes crdt-region-id 3 save ""}} {
    set p0 [srv -2 port]
    set p1 [srv -1 port]
    set p2 [srv 0 port]
    r -2 config set crdt-peers "127.0.0.1:$p1,127.0.0.1:$p2"
    r -1 config set crdt-peers "127.0.0.1:$p0,127.0.0.1:$p2"
    r config set crdt-peers "127.0.0.1:$p0,127.0.0.1:$p1"
    crdt_wait_connected -2 2
    crdt_wait_connected -1 2
    crdt_wait_connected 0 2

    test {string LWW and counter PN-merge converge} {
        r -2 set user alice
        r -1 incr views
        r incr views
        crdt_wait_same_digest
        assert_equal [r -2 get user] alice
        assert_equal [r get user] alice
        assert_equal [r -2 get views] 2
        assert_equal [r -1 get views] 2
    }

    test {OR-set add and remove converge} {
        r -2 sadd rooms kitchen
        crdt_wait_same_digest
        r -1 srem rooms kitchen
        r sadd rooms bath
        crdt_wait_same_digest
        assert_equal [r -2 scard rooms] 1
        assert_equal [r sismember rooms bath] 1
        assert_equal [r -1 sismember rooms kitchen] 0
    }

    test {hash field LWW converges} {
        r -2 hset profile name ada
        r -1 hset profile city paris
        crdt_wait_same_digest
        assert_equal [r hget profile name] ada
        assert_equal [r -2 hget profile city] paris
    }

    test {delete tombstones converge and can be collected} {
        r -2 del user
        crdt_wait_same_digest
        assert_equal [r exists user] 0
        assert_equal [r -1 exists user] 0
        r -2 config set crdt-tombstone-gc-ms 0
        r -1 config set crdt-tombstone-gc-ms 0
        r config set crdt-tombstone-gc-ms 0
        assert {[r -2 crdt.gc] >= 0}
        assert {[r -1 crdt.gc] >= 0}
        assert {[r crdt.gc] >= 0}
        set info [r -2 crdt.info]
        assert {[string match *tombstones:0* $info]}
    }

    test {lists are rejected on a CRDT database} {
        assert_error {*CRDT*} {r lpush nums 1}
    }

    test {partition then heal converges the digest} {
        r -2 config set crdt-peers ""
        r -1 config set crdt-peers ""
        r config set crdt-peers ""
        r -2 set isolated a
        r -1 incr isolatedc
        r set isolated b
        r -2 config set crdt-peers "127.0.0.1:$p1,127.0.0.1:$p2"
        r -1 config set crdt-peers "127.0.0.1:$p0,127.0.0.1:$p2"
        r config set crdt-peers "127.0.0.1:$p0,127.0.0.1:$p1"
        crdt_wait_connected 0 2
        crdt_wait_same_digest
        # Last writer among the two SETs is region-ordered by the clock.
        # Both sides must agree, whichever value won.
        assert_equal [r -2 get isolated] [r get isolated]
        assert_equal [r -1 get isolatedc] 1
    }
}
}
}

start_server {tags {external:skip} overrides {save ""}} {
    test {baseline memory for 2000 small keys} {
        set plain [status r used_memory]
        set payload [string repeat x 1024]
        for {set i 0} {$i < 2000} {incr i} {
            r set k$i $payload
        }
        set ::crdt_plain_bytes [expr {[status r used_memory] - $plain}]
        assert {$::crdt_plain_bytes > 0}
    }
}
start_server {overrides {crdt-enabled yes crdt-region-id 1 save ""}} {
    test {CRDT metadata stays under 30 percent for small keys} {
        set plain [status r used_memory]
        set payload [string repeat x 1024]
        for {set i 0} {$i < 2000} {incr i} {
            r set k$i $payload
        }
        set crdt_bytes [expr {[status r used_memory] - $plain}]
        set overhead [expr {$crdt_bytes - $::crdt_plain_bytes}]
        if {$overhead < 0} {set overhead 0}
        assert {$overhead * 100 < $::crdt_plain_bytes * 30}
    }
}
