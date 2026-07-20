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

# Pinned so a node's snakemake matches the submitting host's remote protocol. Kept
# in sync with pyproject's snakemake dependency.
DEFAULT_SNAKEMAKE_SPEC = "snakemake>=9,<10"
DEFAULT_STORAGE_SPEC = "snakemake-storage-plugin-s3"


def _q(s: str) -> str:
    return shlex.quote(s)


# A dedicated venv on the node holds snakemake; its bin goes on PATH so the
# remote ``python -m snakemake`` resolves to it. Kept off the system python.
VENV_DIR = "/opt/snakemake-spawn-venv"


def build_install_preamble(
    snakemake_spec: str = DEFAULT_SNAKEMAKE_SPEC,
    storage_spec: str = DEFAULT_STORAGE_SPEC,
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
    return (
        "# snakemake-executor-plugin-spawn: ensure snakemake (py3.11 venv) + S3 storage.\n"
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
