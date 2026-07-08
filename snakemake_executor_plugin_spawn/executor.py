"""SpawnExecutor: a Snakemake RemoteExecutor that runs each job on a spawn instance.

Implements the three abstract methods of
``snakemake_interface_executor_plugins.executors.remote.RemoteExecutor``:

- ``run_job``          — size (truffle) + launch one ephemeral EC2 instance that
                         runs ``self.format_job_exec(job)`` (a ``python -m snakemake
                         … --mode remote`` re-invocation) with ``--on-complete
                         terminate`` + TTL; record instance id + S3 prefix.
- ``check_active_jobs`` — async poll of the durable ``.exitcode`` in S3:
                         present+0 → success, present+nonzero → error, absent →
                         still running (yield).
- ``cancel_jobs``      — ``spawn terminate`` each instance.

Snakemake's native S3 storage plugin handles input/output; this executor never
localizes files. Pure helpers (launch/completion/sizing/bootstrap) live alongside.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import TYPE_CHECKING, AsyncGenerator, List

from snakemake_interface_executor_plugins.executors.base import SubmittedJobInfo
from snakemake_interface_executor_plugins.executors.remote import RemoteExecutor

from . import bootstrap, completion, launch, sizing

if TYPE_CHECKING:
    from snakemake_interface_executor_plugins.jobs import JobExecutorInterface

_NAME_SANITIZE = re.compile(r"[^a-z0-9-]+")


class SpawnExecutor(RemoteExecutor):
    """Run each Snakemake job on an ephemeral EC2 instance via spore-host/spawn."""

    def __post_init__(self) -> None:
        # ExecutorSettings instance (region/workdir_s3/ttl/instance_type/spot/...).
        self.settings = self.workflow.executor_settings

    # ---- helpers ---------------------------------------------------------

    def _region(self) -> str:
        return getattr(self.settings, "region", None) or os.environ.get(
            "SPAWN_REGION", "us-east-1"
        )

    def _ttl(self) -> str:
        return getattr(self.settings, "ttl", None) or os.environ.get("SPAWN_TTL", "4h")

    def _workdir_s3(self) -> str:
        base = getattr(self.settings, "workdir_s3", None) or os.environ.get(
            "SPAWN_WORKDIR_S3", ""
        )
        if not base:
            raise RuntimeError(
                "snakemake-executor-plugin-spawn: set --spawn-workdir-s3 (or "
                "SPAWN_WORKDIR_S3) to an s3:// prefix for the .exitcode completion "
                "signals."
            )
        return base

    def _job_name(self, job: "JobExecutorInterface") -> str:
        raw = f"smk-{getattr(job, 'name', None) or job.jobid}"
        return _NAME_SANITIZE.sub("-", raw.lower()).strip("-")[:60] or "smk-job"

    def _job_prefix(self, job: "JobExecutorInterface") -> str:
        base = self._workdir_s3().rstrip("/")
        attempt = getattr(job, "attempt", 1) or 1
        return f"{base}/{self._job_name(job)}/try-{attempt}"

    def _instance_type(self, job: "JobExecutorInterface") -> str:
        res = job.resources
        override = getattr(self.settings, "instance_type", None) or res.get(
            "spawn_instance_type"
        )
        return sizing.pick_instance_type(
            override=override,
            cores=getattr(job, "threads", None) or res.get("_cores"),
            mem_mb=res.get("mem_mb"),
        )

    def _run_argv(self, argv: list[str], check: bool) -> "subprocess.CompletedProcess":
        return subprocess.run(argv, check=check, capture_output=True, text=True)

    # ---- the three abstract methods --------------------------------------

    def run_job(self, job: "JobExecutorInterface") -> None:
        region = self._region()
        prefix = self._job_prefix(job)
        name = self._job_name(job)

        # The node re-invokes snakemake for just this target job; the S3 storage
        # provider (forwarded via pass_default_storage_provider_args) does the I/O.
        remote_command = self.format_job_exec(job)
        user_data = bootstrap.build_user_data(
            workdir_s3=prefix, region=region, remote_command=remote_command
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".sh", prefix=f"snakemake-spawn-{name}-", delete=False
        ) as fh:
            fh.write(user_data)
            user_data_file = fh.name

        spec = launch.LaunchSpec(
            name=name,
            instance_type=self._instance_type(job),
            region=region,
            user_data_file=user_data_file,
            ttl=self._ttl(),
            spot=bool(getattr(self.settings, "spot", False)),
        )
        try:
            self.logger.info(
                f"spawn: launching {name} ({spec.instance_type}) for job {job.jobid}"
            )
            self._run_argv(launch.build_launch_argv(spec), check=True)
        finally:
            try:
                os.unlink(user_data_file)
            except OSError:
                pass

        self.report_job_submission(
            SubmittedJobInfo(job, external_jobid=name, aux={"s3_prefix": prefix, "region": region})
        )

    async def check_active_jobs(
        self, active_jobs: List[SubmittedJobInfo]
    ) -> AsyncGenerator[SubmittedJobInfo, None]:
        for j in active_jobs:
            prefix = j.aux["s3_prefix"]
            region = j.aux["region"]
            probe = completion.build_exitcode_probe_argv(prefix, region)
            out = self._run_argv(probe, check=False)
            if out.returncode != 0:
                # .exitcode not present yet -> still running.
                yield j
                continue
            code = completion.parse_exit_code(out.stdout)
            if code is None:
                yield j
            elif code == 0:
                self.report_job_success(j)
            else:
                self.report_job_error(
                    j, msg=f"spawn job '{j.external_jobid}' exited with code {code}"
                )

    def cancel_jobs(self, active_jobs: List[SubmittedJobInfo]) -> None:
        for j in active_jobs:
            region = j.aux.get("region") if j.aux else None
            self._run_argv(launch.build_cancel_argv(j.external_jobid, region), check=False)
