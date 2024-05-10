black cesnet_openid_remote tests --target-version py310
autoflake --in-place --remove-all-unused-imports --recursive cesnet_openid_remote tests
isort cesnet_openid_remote tests
