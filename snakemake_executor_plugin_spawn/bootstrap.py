"""Build the snakemake install preamble that runs on the ephemeral instance.

Unlike cwl-spawn/miniwdl-spawn (which stage a working tree via S3 by hand),
Snakemake's remote model does the I/O itself: the node runs a fresh
``python -m snakemake … --mode remote`` invocation that retrieves inputs from the
S3 storage provider, runs the one rule, and stores outputs back to S3. spawn now
owns the launch, the durable completion record, and self-termination (spawn#386),
so this module only builds the **install preamble** that goes into the TaskSpec
command: ensure snakemake + the S3 storage plugin are present (auto-install at
boot on stock AL2023 — no prebaked AMI needed; idempotent).

All functions are pure string builders (no I/O), unit-tested without AWS.
"""

from __future__ import annotations

import shlex
from importlib import metadata

# Fallbacks, used only when the submitting environment's own versions cannot be
# read. Kept in sync with pyproject's snakemake dependency.
FALLBACK_SNAKEMAKE_SPEC = "snakemake>=9,<10"
FALLBACK_STORAGE_SPEC = "snakemake-storage-plugin-s3"


def _pinned_spec(dist: str, fallback: str) -> str:
    """``<dist>==<version installed here>``, or ``fallback`` if unreadable.

    Resolving an unpinned RANGE on each node meant the version of Snakemake that
    executed a job was whatever PyPI served that instance at that moment
    (snakemake#13). Two jobs in one workflow could therefore run different
    Snakemake versions — the fan-out launches instances minutes apart, and a
    release landing mid-workflow is enough — and nothing recorded what either
    resolved. The storage plugin was wholly unpinned, making it the likelier of
    the two to move.

    Pinning to the SUBMITTER's versions makes the nodes agree with the host that
    submitted the workflow by construction, which is the property the spore.host
    model depends on: a run is reproducible because the thing that ran is
    identified. A caller who wants something else sets --spawn-snakemake-spec /
    --spawn-storage-spec explicitly.
    """
    try:
        return f"{dist}=={metadata.version(dist)}"
    except metadata.PackageNotFoundError:
        return fallback


def default_snakemake_spec() -> str:
    """Pin to this environment's snakemake. Called at submit time, not import."""
    return _pinned_spec("snakemake", FALLBACK_SNAKEMAKE_SPEC)


def default_storage_spec() -> str:
    """Pin to this environment's S3 storage plugin.

    Unlike snakemake, this is NOT a hard dependency of this package, so the
    fallback is reachable in normal use. A working setup has it (the submitter
    needs it for --default-storage-provider s3), but we cannot assume it.
    """
    return _pinned_spec("snakemake-storage-plugin-s3", FALLBACK_STORAGE_SPEC)


def _q(s: str) -> str:
    return shlex.quote(s)


# A dedicated venv on the node holds snakemake; its bin goes on PATH so the
# remote ``python -m snakemake`` resolves to it. Kept off the system python.
VENV_DIR = "/opt/snakemake-spawn-venv"


def build_install_preamble(
    snakemake_spec: str | None = None,
    storage_spec: str | None = None,
    venv_dir: str = VENV_DIR,
) -> str:
    """Idempotent install of snakemake + the S3 storage plugin into a venv on the
    node, and put its bin on PATH.

    Stock AL2023's *system* python is 3.9, but Snakemake 9 needs >=3.11 — so we
    install ``python3.11`` from AL2023's repos and build a venv with it, rather
    than using the system interpreter (the cause of the first e2e failure: pip
    couldn't find a snakemake>=9 for py3.9). Guarded on the venv's snakemake so a
    prebuilt AMI is a near no-op. The final ``export PATH`` makes the venv's
    ``python``/``snakemake`` win for the remote command.
    """
    # Resolved here rather than as parameter defaults, which bind at import time —
    # metadata lookups belong at submit time (snakemake#13).
    if snakemake_spec is None:
        snakemake_spec = default_snakemake_spec()
    if storage_spec is None:
        storage_spec = default_storage_spec()

    return (
        "# snakemake-executor-plugin-spawn: ensure snakemake (py3.11 venv) + S3 storage.\n"
        # Echo the specs into the job's log so the software that ran is recoverable
        # from the record even when a caller has loosened the pin (snakemake#13).
        f'echo "snakemake-spawn: installing {snakemake_spec} {storage_spec}" >&2\n'
        f"if [ ! -x {_q(venv_dir)}/bin/snakemake ]; then\n"
        '  echo "snakemake-spawn: installing python3.11 + snakemake..." >&2\n'
        "  sudo dnf install -y python3.11 python3.11-pip >/dev/null 2>&1 "
        '|| { echo "snakemake-spawn: python3.11 install failed" >&2; exit 1; }\n'
        f"  sudo python3.11 -m venv {_q(venv_dir)} "
        '|| { echo "snakemake-spawn: venv create failed" >&2; exit 1; }\n'
        f"  sudo {_q(venv_dir)}/bin/pip install --quiet --upgrade pip >/dev/null 2>&1 || true\n"
        f"  sudo {_q(venv_dir)}/bin/pip install --quiet {_q(snakemake_spec)} {_q(storage_spec)} "
        '|| { echo "snakemake-spawn: snakemake install failed" >&2; exit 1; }\n'
        "fi\n"
        f'export PATH={_q(venv_dir)}/bin:"$PATH"\n'
    )
