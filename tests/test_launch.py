from snakemake_executor_plugin_spawn.launch import (
    LaunchSpec,
    build_cancel_argv,
    build_launch_argv,
)


def test_launch_argv_core_flags():
    argv = build_launch_argv(
        LaunchSpec(name="smk-x", instance_type="c7g.4xlarge", region="us-east-1",
                   user_data_file="/tmp/s.sh", ttl="2h")
    )
    assert argv[:3] == ["spawn", "launch", "smk-x"]
    assert "--user-data-file" in argv and "--user-data" not in argv
    assert argv[argv.index("--on-complete") + 1] == "terminate"
    assert "--wait-for-running=false" in argv and "--wait-for-ssh=false" in argv
    assert "-y" in argv
    assert argv[argv.index("--instance-type") + 1] == "c7g.4xlarge"
    assert argv[argv.index("--ttl") + 1] == "2h"
    assert argv[argv.index("--iam-policy") + 1] == "s3:FullAccess"


def test_launch_argv_spot_and_omits_unset():
    argv = build_launch_argv(
        LaunchSpec(name="n", instance_type="t3.medium", region="us-west-2",
                   user_data_file="/tmp/s.sh", spot=True)
    )
    assert "--spot" in argv
    for absent in ("--ami", "--volume-size", "--az", "--fsx-id"):
        assert absent not in argv


def test_cancel_uses_terminate():
    assert build_cancel_argv("smk-x", "eu-west-1") == [
        "spawn", "terminate", "smk-x", "--region", "eu-west-1", "--yes"
    ]
