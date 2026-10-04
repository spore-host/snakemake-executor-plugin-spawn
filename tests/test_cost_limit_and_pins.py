"""Tests for snakemake#12 (cost_limit) and #13 (pinned specs).

The container half of #12 was removed in #16: routing a rule's `container:` to
`spec.container` cannot work here, because `spec.command` is a Snakemake
re-invocation rather than the rule's shell — so it put `python -m snakemake
--mode remote` inside a single-tool science image. See #16 for the shape that
can work (apptainer on the node, with Snakemake owning containerisation).
"""

from __future__ import annotations

from importlib import metadata

from snakemake_executor_plugin_spawn import bootstrap, taskspec


def _spec(**kw) -> dict:
    base = dict(
        task_id="smk-align-1",
        remote_command="snakemake --target align",
        job_dir="/tmp/job",
        install_preamble="# preamble",
    )
    base.update(kw)
    return taskspec.build_task_spec(**base)


# ---- #12: lifecycle.cost_limit ----------------------------------------------


def test_cost_limit_is_emitted_into_lifecycle():
    """The second belt. TTL bounds a job in TIME, not money; spored enforces the
    two independently and the first to fire wins, so without this the only
    ceiling is the TTL — and a job that HANGS produces no error for Snakemake to
    retry or abort on, so it bills the full TTL."""
    spec = _spec(cost_limit=0.05)
    assert spec["lifecycle"]["cost_limit"] == 0.05


def test_cost_limit_omitted_when_unset():
    """Absent rather than null, so spawn's own default applies and the spec stays
    minimal."""
    assert "cost_limit" not in _spec()["lifecycle"]
    assert "cost_limit" not in _spec(cost_limit=None)["lifecycle"]


def test_cost_limit_zero_or_negative_is_not_emitted():
    """A zero cap would mean "terminate immediately", which is never what someone
    typing --spawn-cost-limit 0 intends. Treated as unset instead."""
    assert "cost_limit" not in _spec(cost_limit=0)["lifecycle"]
    assert "cost_limit" not in _spec(cost_limit=-1)["lifecycle"]


def test_cost_limit_coerced_to_float():
    """Settings arrive as strings from env vars; the spec is JSON so the type has
    to be a number, not "0.05"."""
    spec = _spec(cost_limit="0.25")
    assert spec["lifecycle"]["cost_limit"] == 0.25
    assert isinstance(spec["lifecycle"]["cost_limit"], float)


def test_ttl_and_on_complete_survive_the_cost_limit_addition():
    spec = _spec(ttl="30m", on_complete="terminate", cost_limit=1.0)
    assert spec["lifecycle"] == {
        "ttl": "30m",
        "on_complete": "terminate",
        "cost_limit": 1.0,
    }


# ---- #13: pinned install specs ----------------------------------------------


def test_default_specs_pin_to_the_submitting_environment():
    """Resolving an unpinned RANGE on each node meant the Snakemake that executed
    a job was whatever PyPI served that instance at that moment — so two jobs in
    one workflow could run different versions, since the fan-out launches
    instances minutes apart. Pinning to the submitter makes them agree by
    construction."""
    spec = bootstrap.default_snakemake_spec()
    assert spec.startswith("snakemake==")
    # It must match THIS environment, which is the whole point.
    assert spec == f"snakemake=={metadata.version('snakemake')}"

    # The storage plugin is NOT a hard dependency of this package (pyproject
    # declares only snakemake-interface-executor-plugins + snakemake), so its
    # fallback is reachable in normal use: pin it when the submitter has it,
    # degrade to the range when they don't. Assert whichever is actually true
    # here rather than assuming one, so this passes in CI either way.
    storage = bootstrap.default_storage_spec()
    try:
        want = f"snakemake-storage-plugin-s3=={metadata.version('snakemake-storage-plugin-s3')}"
    except metadata.PackageNotFoundError:
        want = bootstrap.FALLBACK_STORAGE_SPEC
    assert storage == want


def test_unresolvable_distribution_falls_back_rather_than_raising():
    """A submitting environment that somehow lacks the dist must still produce a
    working preamble — degraded to the old range, not a crash at submit time."""
    assert bootstrap._pinned_spec("definitely-not-installed-xyz", "fallback>=1") == (
        "fallback>=1"
    )


def test_preamble_installs_the_pinned_specs_and_echoes_them():
    pre = bootstrap.build_install_preamble()
    pinned = bootstrap.default_snakemake_spec()
    assert pinned in pre
    # Echoed so the software that ran is recoverable from the job's log even if a
    # caller loosened the pin.
    assert "snakemake-spawn: installing" in pre


def test_explicit_specs_override_the_pins():
    """A caller who wants a range, or a pre-release, must be able to say so."""
    pre = bootstrap.build_install_preamble(
        snakemake_spec="snakemake==9.1.0", storage_spec="snakemake-storage-plugin-s3==1.2.3"
    )
    assert "snakemake==9.1.0" in pre
    assert "snakemake-storage-plugin-s3==1.2.3" in pre
    assert "snakemake>=9,<10" not in pre


def test_defaults_resolve_at_call_time_not_import_time():
    """build_install_preamble takes None and resolves inside, so a metadata lookup
    happens at submit time. Binding it as a parameter default would freeze it at
    import, which is both wrong and untestable."""
    import inspect

    sig = inspect.signature(bootstrap.build_install_preamble)
    assert sig.parameters["snakemake_spec"].default is None
    assert sig.parameters["storage_spec"].default is None
