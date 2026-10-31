# Time-series module. Compression fuzz lives in modules/timeseries/chunk_test.
# This file is sourced from tests/unit/timeseries.tcl so `make test` runs it.

set ::ts_root [file normalize [file join [file dirname [info script]] .. ..]]
exec make -C [file join $::ts_root modules/timeseries]
set ::ts_module [file normalize [file join $::ts_root modules/timeseries/timeseries.so]]
set ::ts_chunk_test [file normalize [file join $::ts_root modules/timeseries/chunk_test]]

test {timeseries compression fuzz, aggregation reference, and 1M budget} {
    exec $::ts_chunk_test
} {*OK}

start_server [list overrides [list loadmodule $::ts_module appendonly yes aof-use-rdb-preamble no]] {
    test {TS.CREATE TS.ADD TS.GET} {
        r ts.create temp RETENTION 0 DUPLICATE_POLICY block LABELS sensor a
        r ts.add temp 10 1
        r ts.add temp 20 2
        r ts.get temp
    } {20 2}

    test {duplicate policy BLOCK rejects the same timestamp} {
        assert_error {*duplicate*} {r ts.add temp 20 9}
    }

    test {duplicate policy LAST overwrites the sample} {
        r ts.create lastp DUPLICATE_POLICY last
        r ts.add lastp 1 1
        r ts.add lastp 1 5
        r ts.get lastp
    } {1 5}

    test {duplicate policy MIN keeps the smaller value} {
        r ts.create minp DUPLICATE_POLICY min
        r ts.add minp 1 4
        r ts.add minp 1 2
        r ts.add minp 1 9
        set pair [r ts.get minp]
        assert_equal [lindex $pair 0] 1
        assert {[expr {abs([lindex $pair 1] - 2)}] < 1e-9}
    }

    test {TS.MADD and TS.RANGE} {
        r ts.create walk CHUNK_SIZE 128
        r ts.madd walk 0 1 walk 10 3 walk 20 5
        set samples [r ts.range walk - +]
        assert_equal [llength $samples] 3
        assert_equal [lindex [lindex $samples 0] 0] 0
        assert_equal [lindex [lindex $samples 2] 0] 20
    }

    test {TS.RANGE aggregation matches a naive bucket average} {
        # Buckets of 100: [0,10,20] -> avg 3, [100] -> 10.
        r ts.add walk 100 10
        set got [r ts.range walk - + AGGREGATION avg 100]
        assert_equal [llength $got] 2
        assert_equal [lindex [lindex $got 0] 0] 0
        assert {[expr {abs([lindex [lindex $got 0] 1] - 3.0)}] < 1e-9}
        assert_equal [lindex [lindex $got 1] 0] 100
        assert {[expr {abs([lindex [lindex $got 1] 1] - 10.0)}] < 1e-9}
        set rev [r ts.revrange walk - + AGGREGATION sum 100]
        assert_equal [lindex [lindex $rev 0] 0] 100
        assert {[expr {abs([lindex [lindex $rev 0] 1] - 10.0)}] < 1e-9}
        assert {[expr {abs([lindex [lindex $rev 1] 1] - 9.0)}] < 1e-9}
    }

    test {TS.RANGE COUNT and FILTER_BY_VALUE} {
        set counted [r ts.range walk 0 20 COUNT 2]
        assert_equal [llength $counted] 2
        set filtered [r ts.range walk - + FILTER_BY_VALUE 3 5]
        assert_equal [llength $filtered] 2
    }

    test {TS.MRANGE label filters} {
        r ts.create kitchen LABELS room kitchen color red
        r ts.create bath LABELS room bath color blue
        r ts.add kitchen 1 7
        r ts.add bath 1 8
        set hit [r ts.mrange - + WITHLABELS FILTER room=kitchen]
        assert_equal [llength $hit] 1
        assert_equal [lindex [lindex $hit 0] 0] kitchen
        set labels [lindex [lindex $hit 0] 1]
        assert_equal [llength $labels] 2
        set samples [lindex [lindex $hit 0] 2]
        assert_equal [lindex [lindex $samples 0] 0] 1
        set miss [r ts.mrange - + FILTER room=kitchen color!=red]
        assert_equal [llength $miss] 0
        set either [r ts.mrange - + FILTER room!=garage]
        assert {[llength $either] >= 2}
    }

    test {TS.DEL removes a closed timestamp range} {
        set removed [r ts.del walk 0 10]
        assert_equal $removed 2
        set left [r ts.range walk - +]
        assert_equal [llength $left] 2
        assert_equal [lindex [lindex $left 0] 0] 20
    }

    test {retention drops samples older than the newest minus the window} {
        r ts.create aged RETENTION 1000
        r ts.add aged 1000 1
        r ts.add aged 5000 2
        set got [r ts.range aged - +]
        assert_equal [llength $got] 1
        assert_equal [lindex [lindex $got 0] 0] 5000
    }

    test {older timestamps are rejected} {
        assert_error {*older*} {r ts.add aged 1000 1}
    }

    test {RDB save and reload keeps samples and labels} {
        r save
        r debug reload
        set got [r ts.range walk - +]
        assert_equal [llength $got] 2
        assert_equal [lindex [lindex $got 0] 0] 20
        set hit [r ts.mrange - + FILTER room=kitchen]
        assert_equal [llength $hit] 1
        assert_equal [lindex [lindex [lindex [lindex $hit 0] 2] 0] 0] 1
    } {} {needs:debug}

    test {AOF rewrite replays the series} {
        r bgrewriteaof
        waitForBgrewriteaof r
        r debug loadaof
        set got [r ts.get lastp]
        assert_equal [lindex $got 0] 1
        assert {[expr {abs([lindex $got 1] - 5)}] < 1e-9}
        set aged [r ts.range aged - +]
        assert_equal [llength $aged] 1
        set hit [r ts.mrange - + WITHLABELS FILTER room=bath]
        assert_equal [llength $hit] 1
    } {} {needs:debug}

    test {a string key is the wrong type} {
        r set plain hello
        assert_error {*WRONGTYPE*} {r ts.add plain 1 1}
        assert_error {*WRONGTYPE*} {r ts.get plain}
    }
}
