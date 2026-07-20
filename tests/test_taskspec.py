"""Unit tests for the pure TaskSpec builder + CompletionRecord parsing."""

import pytest

from snakemake_executor_plugin_spawn import taskspec

JD = "/var/tmp/snakemake_spawn_job"
REMOTE = "python -m snakemake --mode remote --target-jobs x"


def _spec(**over):
    base = dict(
        task_id="smk-myrule-1",
        remote_command=REMOTE,
        job_dir=JD,
        install_preamble="# install\ntrue\n",
    )
    base.update(over)
    return taskspec.build_task_spec(**base)


def test_command_bundles_mkdir_preamble_and_remote():
    spec = _spec()
    cmd = spec["command"]
    assert cmd[0] == "/bin/bash" and cmd[1] == "-lc"
    inner = cmd[2]
    assert f"mkdir -p {JD}" in inner
    assert f"cd {JD}" in inner
    assert "# install" in inner  # preamble bundled
    assert REMOTE in inner
    # remote command runs after the preamble
    assert inner.index("# install") < inner.index(REMOTE)


def test_no_manifests():
    # Snakemake's S3 storage plugin owns file I/O — no inputs/outputs manifests.
    spec = _spec()
    assert "inputs" not in spec
    assert "outputs" not in spec


def test_resources_from_cores_and_mem_mb():
    spec = _spec(cores=8, mem_mb=16384)
    assert spec["resources"]["cpu"] == 8
    assert spec["resources"]["memory_gib"] == pytest.approx(16.0)


def test_resources_omitted_when_absent():
    assert _spec()["resources"] == {}


def test_spot_maps_to_purchase_with_fallback():
    r = _spec(spot=True)["resources"]
    assert r["purchase"] == "spot" and r["fallback"] == "on_demand"


def test_instance_hint_maps_to_family():
    assert _spec(instance_hint="c7i.4xlarge")["resources"]["families"] == ["c7i"]


def test_lifecycle_defaults_terminate():
    assert _spec(ttl="2h")["lifecycle"] == {"ttl": "2h", "on_complete": "terminate"}


def test_empty_preamble_still_runs_remote():
    inner = _spec(install_preamble="")["command"][2]
    assert REMOTE in inner
    assert f"mkdir -p {JD}" in inner


def test_mem_mb_to_gib_edges():
    assert taskspec.mem_mb_to_gib(None) is None
    assert taskspec.mem_mb_to_gib(0) is None
    assert taskspec.mem_mb_to_gib("junk") is None
    assert taskspec.mem_mb_to_gib(1024) == pytest.approx(1.0)


def test_instance_type_family_edges():
    assert taskspec.instance_type_family(None) is None
    assert taskspec.instance_type_family("junk") is None
    assert taskspec.instance_type_family("m7i.large") == "m7i"


def test_check_complete_to_status_contract():
    assert taskspec.check_complete_to_status(0) == "completed"
    assert taskspec.check_complete_to_status(1) == "failed"
    assert taskspec.check_complete_to_status(2) is None
    with pytest.raises(RuntimeError):
        taskspec.check_complete_to_status(3)


def test_parse_completion_record():
    rec = taskspec.parse_completion_record('{"exit_code":5,"state":"failed"}')
    assert rec["exit_code"] == 5
    with pytest.raises(Exception):
        taskspec.parse_completion_record("nope")
