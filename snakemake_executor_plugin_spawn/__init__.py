"""snakemake-executor-plugin-spawn: run each Snakemake job on an ephemeral EC2
instance via spore-host/spawn. The Snakemake analog of nf-spawn (Nextflow),
miniwdl-spawn (WDL), and cwl-spawn (CWL).

Snakemake discovers this by module-name prefix and validates three module-level
names — ``Executor``, ``common_settings``, ``ExecutorSettings``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from snakemake_interface_executor_plugins.settings import (
    CommonSettings,
    ExecutorSettingsBase,
)

from .executor import SpawnExecutor as Executor  # noqa: F401

__version__ = "0.1.0"


@dataclass
class ExecutorSettings(ExecutorSettingsBase):
    """CLI settings, surfaced as ``--spawn-<field>`` (and SNAKEMAKE_SPAWN_<FIELD>)."""

    workdir_s3: Optional[str] = field(
        default=None,
        metadata={
            "help": "S3 prefix (s3://bucket/prefix) for per-job .exitcode completion signals.",
            "env_var": True,
        },
    )
    region: Optional[str] = field(
        default=None, metadata={"help": "AWS region for launched instances.", "env_var": True}
    )
    ttl: Optional[str] = field(
        default=None,
        metadata={"help": "TTL backstop per job instance (e.g. 4h). Default 4h.", "env_var": True},
    )
    instance_type: Optional[str] = field(
        default=None,
        metadata={"help": "Override the auto-sized EC2 instance type for every job."},
    )
    spot: bool = field(
        default=False, metadata={"help": "Launch job instances as spot."}
    )


# One job -> one ephemeral VM, no shared filesystem; Snakemake's S3 storage plugin
# handles I/O (forwarded to the node via pass_default_storage_provider_args), and
# the node auto-installs it (auto_deploy_default_storage_provider). Mirrors the
# googlebatch plugin's cloud/no-shared-FS block.
common_settings = CommonSettings(
    non_local_exec=True,
    implies_no_shared_fs=True,
    job_deploy_sources=True,
    pass_default_storage_provider_args=True,
    pass_default_resources_args=True,
    pass_envvar_declarations_to_cmd=True,
    auto_deploy_default_storage_provider=True,
)
