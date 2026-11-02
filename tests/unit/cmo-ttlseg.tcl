start_server {tags {"cmo" "external:skip"} overrides {save "" appendonly no cmo-ttl-segments yes cmo-ttl-segment-ms 200}} {
    proc ttl_field {name} {
        set info [r info cmo_ttl]
        return [getInfoProperty $info $name]
    }

    test {A finished TTL segment deletes untouched keys in one pass} {
        r debug set-active-expire 0
        r set stay 1
        r psetex a 80 va
        r psetex b 80 vb
        assert_equal 2 [ttl_field cmo_ttl_tracked_keys]
        after 600
        wait_for_condition 50 20 {
            [r dbsize] == 1
        } else {
            fail "segment reaper left keys: dbsize [r dbsize] reaped [ttl_field cmo_ttl_reaped_keys]"
        }
        assert_equal 1 [r get stay]
        assert_equal {} [r get a]
        assert_equal {} [r get b]
        assert_morethan [ttl_field cmo_ttl_reaped_keys] 0
    }

    test {PERSIST takes a key out of its segment} {
        r debug set-active-expire 0
        r psetex kept 80 v
        r persist kept
        assert_equal 0 [ttl_field cmo_ttl_tracked_keys]
        after 600
        assert_equal v [r get kept]
    }
}
