# SSD value log. Keys stay in RAM. Large cold strings move to an append-only
# log and come back on read. Default tiering is off, so the rest of the suite
# does not enter this path.

proc tier_p99 {samples} {
    set s [lsort -integer $samples]
    set n [llength $s]
    if {$n == 0} { return 0 }
    set i [expr {($n - 1) * 99 / 100}]
    return [lindex $s $i]
}

start_server {tags {external:skip} overrides {save "" tiering-enabled yes tiering-idle-seconds 0 tiering-min-value 64 tiering-max-ram 0}} {
    test {cold strings spill and promote back to the same bytes} {
        set payload [string repeat x 120000]
        # Spill only after the sample, so a cron tick cannot move the values
        # before used_memory is recorded.
        r config set tiering-enabled no
        r set a $payload
        r set b $payload
        r set c $payload
        set hot {}
        for {set i 0} {$i < 40} {incr i} {
            set t [clock microseconds]
            r get a
            lappend hot [expr {[clock microseconds] - $t}]
        }
        set before_spill [status r used_memory]
        set spills [status r tiering_spills]
        r config set tiering-enabled yes
        wait_for_condition 50 100 {
            [status r tiering_spills] >= $spills + 2
        } else {
            fail "values were not spilled: [r info memory]"
        }
        set after_spill [status r used_memory]
        assert {$after_spill + 100000 < $before_spill}

        set cold {}
        for {set i 0} {$i < 12} {incr i} {
            if {$i > 0} {
                set seen [status r tiering_spills]
                wait_for_condition 40 50 {
                    [status r tiering_spills] > $seen
                } else {
                    fail "value was not spilled again"
                }
            }
            set t [clock microseconds]
            set got [r get b]
            lappend cold [expr {[clock microseconds] - $t}]
            assert_equal $got $payload
        }
        assert_equal [r get c] $payload
        assert {[status r tiering_promotions] >= 1}
        assert {[status r tiering_bytes] > 0}
        assert {[tier_p99 $hot] < 500000}
        assert {[tier_p99 $cold] < 500000}
    }

    test {delete keeps the surviving value} {
        r del a
        assert_equal [string length [r get b]] 120000
        assert_equal [r exists a] 0
    }

    test {expire frees a tiered string} {
        r config set tiering-enabled no
        r set e [string repeat e 90000]
        set spills [status r tiering_spills]
        r config set tiering-enabled yes
        wait_for_condition 40 50 {
            [status r tiering_spills] > $spills
        } else {
            fail "expire key was not spilled"
        }
        r pexpire e 1
        wait_for_condition 50 100 {
            [r exists e] == 0
        } else {
            fail "tiered key did not expire"
        }
        assert_equal [string length [r get b]] 120000
    }

    test {mixed reads writes deletes and expires stay consistent} {
        for {set i 0} {$i < 20} {incr i} {
            set n [expr {$i % 5}]
            if {$n == 0} {
                r set mix$i [string repeat m [expr {2000 + $i * 500}]]
            } elseif {$n == 1} {
                r get mix$i
            } elseif {$n == 2} {
                r del mix$i
            } elseif {$n == 3} {
                r set mix$i short
                r pexpire mix$i 1
            } else {
                r set keep [string repeat k 80000]
                assert_equal [string length [r get keep]] 80000
            }
        }
        r set keep [string repeat k 80000]
        after 200
        assert_equal [string length [r get keep]] 80000
    }

    test {RDB reload round-trips a tiered value} {
        r save
        assert {[r debug reload nosave] eq {OK}}
        assert_equal [string length [r get b]] 120000
    } {} {needs:debug}

    test {a torn tail does not hide earlier records} {
        r config set tiering-debug-crash-after [expr {[status r tiering_spills] + 1}]
        catch {r set d [string repeat y 120000]}
        after 500
        if {[is_alive [srv 0 pid]]} {
            exec kill -9 [srv 0 pid]
        }
        set pid [srv 0 pid]
        set spins 0
        while {[is_alive $pid]} {
            after 20
            incr spins
            if {$spins > 100} break
        }
        restart_server 0 true false
        assert_equal [string length [r get b]] 120000
    } {} {needs:debug}
}

start_server {tags {external:skip needs:debug} overrides {save "" tiering-enabled yes tiering-idle-seconds 0 tiering-min-value 64 tiering-max-ram 0}} {
    test {crash before compaction rename keeps the previous log} {
        # Fresh log: three equal records. Deleting two makes dead space more
        # than half the file, which is when compaction runs. The process exits
        # before rename, so the previous log is the one that remains.
        r config set tiering-enabled no
        r set a [string repeat a 90000]
        r set b [string repeat b 90000]
        r set c [string repeat c 90000]
        r config set tiering-enabled yes
        wait_for_condition 40 50 {
            [status r tiering_spills] >= 3
        } else {
            fail "compaction keys were not spilled"
        }
        r save
        set bytes [status r tiering_bytes]
        r config set tiering-debug-exit-before-rename yes
        r del a
        r del c
        after 300
        if {[is_alive [srv 0 pid]]} {
            catch {r ping}
            after 500
        }
        set pid [srv 0 pid]
        set spins 0
        while {[is_alive $pid]} {
            after 20
            incr spins
            if {$spins > 150} {
                fail "server did not exit during compaction (dead [status r tiering_dead_bytes] bytes [status r tiering_bytes])"
            }
        }
        restart_server 0 true false
        assert_equal [string length [r get b]] 90000
        assert {[status r tiering_bytes] >= $bytes}
    }
}

start_server {tags {external:skip needs:debug} overrides {save "" appendonly yes aof-use-rdb-preamble no tiering-enabled yes tiering-idle-seconds 0 tiering-min-value 64 tiering-max-ram 0}} {
    test {AOF rewrite reloads a tiered string} {
        set payload [string repeat z 80000]
        r config set tiering-enabled no
        r set a $payload
        set spills [status r tiering_spills]
        r config set tiering-enabled yes
        wait_for_condition 40 50 {
            [status r tiering_spills] > $spills
        } else {
            fail "AOF key was not spilled"
        }
        r bgrewriteaof
        waitForBgrewriteaof r
        r debug loadaof
        assert_equal [r get a] $payload
    }
}

start_server {tags {external:skip} overrides {save "" tiering-enabled no tiering-idle-seconds 0 tiering-min-value 1000 tiering-max-ram 0}} {
    test {a dataset several times the RAM cap spills until under the cap} {
        set base [status r used_memory]
        set cap [expr {$base + 250000}]
        set payload_len 200000
        set n [expr {int(double($cap) * 5 / $payload_len) + 1}]
        set blob [string repeat q $payload_len]
        r config set tiering-max-ram $cap
        for {set i 0} {$i < $n} {incr i} {
            r set k$i $blob
        }
        assert {[expr {$n * $payload_len}] > [expr {$cap * 5}]}
        r config set tiering-enabled yes
        wait_for_condition 100 100 {
            [status r used_memory] <= $cap
        } else {
            fail "used_memory [status r used_memory] stayed above cap $cap (spills [status r tiering_spills])"
        }
        assert_equal [string length [r get k0]] $payload_len
    }
}
