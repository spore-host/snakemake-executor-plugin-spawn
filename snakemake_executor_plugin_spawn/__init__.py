"""snakemake-executor-plugin-spawn: run each Snakemake job on an ephemeral EC2
instance via spore-host/spawn. The Snakemake analog of nf-spawn (Nextflow),
miniwdl-spawn (WDL), and cwl-spawn (CWL).

Snakemake discovers this by module-name prefix and validates three module-level
names — ``Executor``, ``common_settings``, ``ExecutorSettings``.

NOTE: do NOT add ``from __future__ import annotations`` here. Snakemake's plugin
interface reads each ExecutorSettings field's real type object (``Optional[str]``,
``bool``) to build argparse; stringized annotations break it with
``'Optional[str]' is not callable``.
"""

from dataclasses import dataclass, field
from typing import Optional

from snakemake_interface_executor_plugins.settings import (
    CommonSettings,
    ExecutorSettingsBase,
)

from .executor import SpawnExecutor as Executor  # noqa: F401

__version__ = "0.2.0"


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
    cost_limit: Optional[float] = field(
        default=None,
        metadata={
            "help": (
                "Hard spend cap per job instance in USD (e.g. 0.05). spored terminates "
                "the instance when accumulated cost reaches it, independently of the TTL "
                "— first limit to fire wins. Without this, TTL is the only ceiling, so a "
                "fan-out of N jobs has a worst case of N x TTL x the instance rate."
            ),
            "env_var": True,
        },
    )
    snakemake_spec: Optional[str] = field(
        default=None,
        metadata={
            "help": (
                "pip spec for snakemake on each job instance. Defaults to "
                "snakemake==<the submitting environment's version>, so the nodes match "
                "the host that submitted the workflow. Set a range to loosen it."
            ),
            "env_var": True,
        },
    )
    storage_spec: Optional[str] = field(
        default=None,
        metadata={
            "help": (
                "pip spec for snakemake-storage-plugin-s3 on each job instance. Defaults "
                "to the submitting environment's version, as with --spawn-snakemake-spec."
            ),
            "env_var": True,
        },
    )
    container: Optional[str] = field(
        default=None,
        metadata={
            "help": (
                "Container image to run every job in (e.g. quay.io/biocontainers/bwa:0.7.18). "
                "Overridden per-rule by Snakemake's own `container:` directive, which is "
                "passed through automatically. spawn installs Docker on demand, pulls the "
                "image (authenticating to a private ECR registry if needed) and runs the "
                "job inside it."
            ),
            "env_var": True,
        },
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
