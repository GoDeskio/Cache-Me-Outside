# Multi-shard TPC prototype. Single-shard mode is the stock server; the type
# suites cover that path. This file checks message passing across two shards.

set ::tpc_port 46222
set ::tpc_root [file normalize [file join [file dirname [info script]] .. ..]]
set ::tpc_srv [file join $::tpc_root src valkey-server]
set ::tpc_cli [file join $::tpc_root src valkey-cli]

proc tpc_cli {args} {
    return [exec $::tpc_cli -p $::tpc_port {*}$args]
}

test {TPC two shards GET SET MGET MULTI} {
    catch {exec pkill -9 -f "valkey-server --engine=tpc --tpc-shards 2 --port $::tpc_port"}
    after 200
    set pid [exec $::tpc_srv --engine=tpc --tpc-shards 2 --port $::tpc_port --dir /tmp > /tmp/tpc-test.log 2>@1 &]
    after 400
    set boot [exec cat /tmp/tpc-test.log]
    if {![string match *listening* $boot]} {
        catch {exec kill -9 $pid}
        error "tpc server did not listen: $boot"
    }
    if {[catch {
        assert_equal [tpc_cli ping] PONG
        assert_equal [tpc_cli set alpha 1] OK
        assert_equal [tpc_cli set beta 2] OK
        assert_equal [tpc_cli mget alpha beta] "1\n2"
        # The prototype speaks RESP arrays, not the inline protocol.
        set fd [socket 127.0.0.1 $::tpc_port]
        fconfigure $fd -translation binary -blocking 0
        puts -nonewline $fd "*1\r\n\$5\r\nMULTI\r\n*2\r\n\$3\r\nGET\r\n\$5\r\nalpha\r\n*3\r\n\$3\r\nSET\r\n\$5\r\nalpha\r\n\$1\r\n9\r\n*1\r\n\$4\r\nEXEC\r\n"
        flush $fd
        set reply ""
        set spins 0
        while {$spins < 40} {
            append reply [read $fd]
            if {[string match *QUEUED* $reply]} break
            after 50
            incr spins
        }
        close $fd
        assert {[string match *QUEUED* $reply]}
        assert_equal [tpc_cli get alpha] 9
        assert_equal [tpc_cli dbsize] 2
        assert {[string match *shards:2* [tpc_cli info]]}
    } err]} {
        catch {exec kill -9 $pid}
        error $err
    }
    catch {exec kill -9 $pid}
    set _ OK
} {OK}
