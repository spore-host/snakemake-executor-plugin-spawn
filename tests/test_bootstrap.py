from snakemake_executor_plugin_spawn.bootstrap import (
    JOB_DIR,
    build_install_preamble,
    build_user_data,
)


def test_install_preamble_uses_py311_venv_and_guards():
    p = build_install_preamble()
    # Snakemake 9 needs py>=3.11; AL2023 system python is 3.9, so install 3.11.
    assert "python3.11" in p
    assert "venv" in p
    assert "pip install" in p
    assert "snakemake-storage-plugin-s3" in p
    # idempotent: skips if the venv's snakemake already exists
    assert "/bin/snakemake ]" in p
    # puts the venv on PATH so the remote `python -m snakemake` resolves to it
    assert "export PATH=" in p


def test_user_data_runs_command_then_exitcode_last():
    ud = build_user_data(
        workdir_s3="s3://b/runs/j",
        region="us-east-1",
        remote_command="python -m snakemake --mode remote --target-jobs x",
    )
    assert ud.startswith("#!/bin/bash\n")
    assert JOB_DIR in ud
    # install preamble present by default
    assert "python3.11" in ud
    # the remote command runs, then TASK_RC captured, then .exitcode uploaded last
    i_cmd = ud.index("python -m snakemake --mode remote")
    i_rc = ud.index("TASK_RC=$?")
    i_exit_up = ud.index('cp "${JD}/.exitcode" "${WORKDIR_S3}/.exitcode"')
    assert i_cmd < i_rc < i_exit_up
    # completion signal at the very end
    assert "spored complete" in ud or "SPAWN_COMPLETE" in ud
    assert ud.rindex("SPAWN_COMPLETE") > i_exit_up or ud.rindex("spored complete") > i_exit_up


def test_user_data_custom_preamble_passthrough():
    ud = build_user_data(
        workdir_s3="s3://b/j", region="us-east-1",
        remote_command="echo hi", install_preamble="# custom\ntrue\n",
    )
    assert "# custom" in ud
    # default preamble suppressed when a custom one is given
    assert "python3.11" not in ud
