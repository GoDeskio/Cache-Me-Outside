start_server {tags {"cmo" "external:skip"}} {
    test {INFO server reports the Cache-Me-Outside build marker} {
        set version [s valkey_version]
        set marker [s cmo_version]

        # valkey_version stays numeric so version2num() and clients keep working.
        assert_match {[0-9]*.[0-9]*.[0-9]*} $version
        assert_no_match {*-*} $version
        assert_equal $marker ${version}-cmo
    }
}
