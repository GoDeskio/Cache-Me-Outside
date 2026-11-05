start_server {tags {"cmo" "external:skip"} overrides {save "" appendonly no cmo-warm-enabled yes cmo-warm-file cmo-warm.rdb}} {
    test {A clean restart restores strings, hashes, lists, and TTLs from the warm checkpoint} {
        r set alpha hello
        r set bulk [string repeat z 40]
        r hset user name ada
        r rpush nums 1 2 3
        r psetex short 60000 temp
        restart_server 0 true false
        assert_equal hello [r get alpha]
        assert_equal [string repeat z 40] [r get bulk]
        assert_equal ada [r hget user name]
        assert_equal {1 2 3} [r lrange nums 0 -1]
        assert_equal temp [r get short]
        assert_morethan [r pttl short] 0
    }
}
