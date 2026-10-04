"""The container passthrough must stay removed (snakemake#16).

v0.3.0 routed a rule's `container:` to `spec.container`. It could not work, and
the reason is architectural rather than a detail: `spec.command` here is a
**Snakemake re-invocation** (`format_job_exec` → `python -m snakemake --mode
remote …`), not the rule's shell. So putting the science image in
`spec.container` ran Snakemake inside a single-tool bioconda image — which has
no Snakemake, no storage plugin, no `dnf`, no `sudo`, and no root.

Observed on a real run against a pinned arm64 image:

    spawn: [...] image pull done; command start
    snakemake-spawn: installing snakemake==9.27.0 …
    snakemake-spawn: python3.11 install failed
    spawn: [...] command exit rc=1

and before that, with the scheme left on, `docker: invalid reference format`
(rc=125), because Snakemake's `container:` conventionally carries `docker://`.

Snakemake already forwards `--software-deployment-method` to the node, so it
intends to own containerisation itself; the node only lacks a runtime. That is
the shape tracked in #16. This test exists so the wrong shape does not come back
as an apparently-obvious one-field fix.
"""

from __future__ import annotations

import inspect

from snakemake_executor_plugin_spawn import ExecutorSettings, taskspec


def test_build_task_spec_takes_no_container_argument():
    params = inspect.signature(taskspec.build_task_spec).parameters
    assert "container" not in params, (
        "build_task_spec must not accept a container: spec.command is a Snakemake "
        "re-invocation, so spec.container puts the wrong program in the container (#16)"
    )


def test_spec_never_emits_container():
    spec = taskspec.build_task_spec(
        task_id="t1",
        remote_command="python -m snakemake --mode remote --target-jobs x",
        job_dir="/tmp/job",
        install_preamble="# preamble",
    )
    assert "container" not in spec, (
        "a spec with container set would run the install preamble and the Snakemake "
        "re-invocation inside the science image (#16)"
    )


def test_no_container_setting_is_advertised():
    """v0.3.0 exposed --spawn-container. Advertising a setting that cannot work is
    worse than not having it — it reads as a supported feature."""
    fields = {f for f in ExecutorSettings.__dataclass_fields__}
    assert "container" not in fields, (
        "--spawn-container must not be offered while the mechanism cannot work (#16)"
    )
    # The cost cap half of #12 is correct and must stay.
    assert "cost_limit" in fields, "--spawn-cost-limit is the half that works and is wanted"
