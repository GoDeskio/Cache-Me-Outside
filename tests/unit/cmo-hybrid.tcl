start_server {tags {"cmo" "external:skip"} overrides {save "" appendonly no cmo-hybrid-enabled yes cmo-hybrid-file cmo-hybrid.dat cmo-hybrid-min-value 64}} {
    proc hybrid_field {name} {
        set info [r info cmo_hybrid]
        return [getInfoProperty $info $name]
    }

    test {Small strings stay in DRAM} {
        r set small hello
        assert_equal hello [r get small]
        assert_equal 0 [hybrid_field cmo_hybrid_spilled_keys]
    }

    test {Large strings spill to flash and promote on read} {
        set payload [string repeat a 80]
        r set big $payload
        assert_equal 1 [hybrid_field cmo_hybrid_spilled_keys]
        assert_equal 1 [hybrid_field cmo_hybrid_spills]
        assert_equal $payload [r get big]
        assert_equal 0 [hybrid_field cmo_hybrid_spilled_keys]
        assert_equal 1 [hybrid_field cmo_hybrid_promotions]
    }

    test {Deleting a spilled key drops the flash record} {
        r set big [string repeat b 80]
        assert_equal 1 [hybrid_field cmo_hybrid_spilled_keys]
        r del big
        assert_equal 0 [hybrid_field cmo_hybrid_spilled_keys]
        assert_equal {} [r get big]
    }

    test {A snapshot stores the real value, not the flash locator} {
        set payload [string repeat c 96]
        r set snap $payload
        assert_equal 1 [hybrid_field cmo_hybrid_spilled_keys]
        r save
        restart_server 0 true false
        assert_equal $payload [r get snap]
    }
}
