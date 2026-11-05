# Main-thread forkless snapshots. The snapshot must match the dataset at
# BGSAVE start, stay under 1.2x memory, and leave the previous dump in place
# if the process dies before the atomic rename.

start_server [list tags {external:skip} overrides [list save "" snapshot-mode forkless snapshot-forkless-slice-keys 8]] {
    test {forkless snapshot matches the dataset at start under concurrent writes} {
        for {set i 0} {$i < 200} {incr i} {
            r set k$i v0
        }
        set before [r debug digest]
        r bgsave
        for {set i 0} {$i < 200} {incr i} {
            r set k$i v1
        }
        wait_for_condition 100 50 {
            [string match {*forkless_snapshot_in_progress:0*} [r info persistence]]
        } else {
            fail "forkless snapshot did not finish"
        }
        assert {[r debug reload nosave] eq {OK}}
        assert_equal [r debug digest] $before
    } {} {needs:debug}

    test {forkless snapshot memory stays under 1.2x the dataset} {
        r flushall
        set payload [string repeat x 100000]
        for {set i 0} {$i < 20} {incr i} {
            r set big$i $payload
        }
        set base [status r used_memory]
        r config set snapshot-forkless-slice-keys 1
        r bgsave
        set peak $base
        for {set i 0} {$i < 30} {incr i} {
            set m [status r used_memory]
            if {$m > $peak} {set peak $m}
            after 10
        }
        wait_for_condition 100 50 {
            [string match {*forkless_snapshot_in_progress:0*} [r info persistence]]
        } else {
            fail "forkless snapshot did not finish"
        }
        set m [status r used_memory]
        if {$m > $peak} {set peak $m}
        assert {$peak < $base * 1.2}
    }

    test {forkless snapshot keeps command latency bounded} {
        r config set snapshot-forkless-slice-keys 1
        for {set i 0} {$i < 400} {incr i} {
            r set lat$i [string repeat y 64]
        }
        r bgsave
        set lats {}
        for {set i 0} {$i < 100} {incr i} {
            set t [clock microseconds]
            r ping
            lappend lats [expr {[clock microseconds] - $t}]
        }
        set ordered [lsort -integer $lats]
        set p99 [lindex $ordered [expr {int(([llength $ordered] - 1) * 0.99)}]]
        # Drain the rest of the snapshot in one cron tick.
        r config set snapshot-forkless-slice-keys 100000
        wait_for_condition 100 50 {
            [string match {*forkless_snapshot_in_progress:0*} [r info persistence]]
        } else {
            fail "forkless snapshot did not finish"
        }
        # The cron slice is 1ms plus one key. A 50ms client p99 leaves room
        # for a loaded CI host without hiding a stalled event loop.
        assert {$p99 < 50000}
    }

    test {crash mid-snapshot leaves the previous dump valid} {
        r flushall
        r config set snapshot-forkless-slice-keys 64
        for {set i 0} {$i < 50} {incr i} {
            r set old$i before
        }
        r bgsave
        wait_for_condition 100 50 {
            [string match {*forkless_snapshot_in_progress:0*} [r info persistence]]
        } else {
            fail "initial snapshot did not finish"
        }
        set digest [r debug digest]
        for {set i 0} {$i < 50} {incr i} {
            r set old$i after
        }
        for {set i 0} {$i < 2000} {incr i} {
            r set extra$i extra
        }
        r config set snapshot-forkless-slice-keys 1
        r bgsave
        assert {[string match {*forkless_snapshot_in_progress:1*} [r info persistence]]}
        exec kill -9 [srv 0 pid]
        set pid [srv 0 pid]
        set spins 0
        while {[is_alive $pid]} {
            after 20
            incr spins
            if {$spins > 250} {fail "server did not die"}
        }
        restart_server 0 true false
        assert_equal [r debug digest] $digest
        assert_equal [r get old0] before
    } {} {needs:debug}
}

start_cluster 1 0 {tags {external:skip cluster}} {
    test {forkless snapshot runs on a cluster primary} {
        R 0 config set save {}
        R 0 config set snapshot-mode forkless
        R 0 config set snapshot-forkless-slice-keys 4
        R 0 set clusterkey v0
        set before [R 0 debug digest]
        R 0 bgsave
        R 0 set clusterkey v1
        wait_for_condition 100 50 {
            [string match {*forkless_snapshot_in_progress:0*} [R 0 info persistence]]
        } else {
            fail "cluster forkless snapshot did not finish"
        }
        assert {[R 0 debug reload nosave] eq {OK}}
        assert_equal [R 0 debug digest] $before
        assert_equal [R 0 get clusterkey] v0
    } {} {needs:debug}
}
