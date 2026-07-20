"""SpawnExecutor: a Snakemake RemoteExecutor that runs each job on a spawn instance.

Implements the three abstract methods of
``snakemake_interface_executor_plugins.executors.remote.RemoteExecutor``:

- ``run_job``          — build a spawn TaskSpec and dispatch ``spawn task run``
                         (detached): spawn sizes (truffle) + launches one ephemeral
                         EC2 instance that runs ``self.format_job_exec(job)`` (a
                         ``python -m snakemake … --mode remote`` re-invocation) with
                         ``on_complete=terminate`` + TTL; record the task id.
- ``check_active_jobs`` — async poll of the durable completion record via
                         ``spawn task status --check-complete``: completed+0 →
                         success, completed+nonzero → error, running → yield.
- ``cancel_jobs``      — ``spawn terminate`` each instance (named after the task id).

Snakemake's native S3 storage plugin handles input/output; this executor never
localizes files. spawn owns sizing, staging (n/a here), the durable completion
record, and the scoped IAM profile (spawn#386). Pure helpers (taskspec/bootstrap)
live alongside.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from typing import TYPE_CHECKING, AsyncGenerator, List

from snakemake_interface_executor_plugins.executors.base import SubmittedJobInfo
from snakemake_interface_executor_plugins.executors.remote import RemoteExecutor

from . import bootstrap, taskspec

if TYPE_CHECKING:
    from snakemake_interface_executor_plugins.jobs import JobExecutorInterface

_NAME_SANITIZE = re.compile(r"[^a-z0-9-]+")

# Where the job runs on the instance. Must be user-writable: spawn runs the
# command as the instance's unprivileged login user (`su - <user>`), which cannot
# create dirs under the root-owned `/mnt`. `/var/tmp` is world-writable (1777) and
# disk-backed (not tmpfs, unlike `/tmp`).
JOB_DIR = "/var/tmp/snakemake_spawn_job"


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

    def _task_id(self, job: "JobExecutorInterface") -> str:
        # Fold the attempt into the id: it names the instance AND keys the
        # completion record (tasks/<id>/completion.json), so a retry must not read
        # the previous attempt's record.
        raw = f"smk-{getattr(job, 'name', None) or job.jobid}"
        attempt = getattr(job, "attempt", 1) or 1
        base = _NAME_SANITIZE.sub("-", raw.lower()).strip("-") or "smk-job"
        return f"{base}-{attempt}"[:60]

    def _instance_hint(self, job: "JobExecutorInterface") -> "str | None":
        res = job.resources
        return getattr(self.settings, "instance_type", None) or res.get("spawn_instance_type")

    def _run_argv(self, argv: list[str], check: bool) -> "subprocess.CompletedProcess":
        return subprocess.run(argv, check=check, capture_output=True, text=True)

    # ---- the three abstract methods --------------------------------------

    def run_job(self, job: "JobExecutorInterface") -> None:
        region = self._region()
        task_id = self._task_id(job)

        # The node re-invokes snakemake for just this target job; the S3 storage
        # provider (forwarded via pass_default_storage_provider_args) does the I/O.
        remote_command = self.format_job_exec(job)
        res = job.resources
        spec = taskspec.build_task_spec(
            task_id=task_id,
            remote_command=remote_command,
            job_dir=JOB_DIR,
            install_preamble=bootstrap.build_install_preamble(),
            cores=getattr(job, "threads", None) or res.get("_cores"),
            mem_mb=res.get("mem_mb"),
            instance_hint=self._instance_hint(job),
            spot=bool(getattr(self.settings, "spot", False)),
            ttl=self._ttl(),
            on_complete="terminate",
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", prefix=f"snakemake-spawn-{task_id}-", delete=False
        ) as fh:
            json.dump(spec, fh)
            spec_file = fh.name

        try:
            self.logger.info(f"spawn: dispatching {task_id} via `spawn task run` for job {job.jobid}")
            # Launch DETACHED (no --wait): spawn sizes, launches, and the instance
            # writes its own completion record. check_active_jobs polls it.
            self._run_argv(
                ["spawn", "task", "run", "--spec", spec_file, "--region", region], check=True
            )
        finally:
            try:
                os.unlink(spec_file)
            except OSError:
                pass

        self.report_job_submission(
            SubmittedJobInfo(job, external_jobid=task_id, aux={"region": region})
        )

    async def check_active_jobs(
        self, active_jobs: List[SubmittedJobInfo]
    ) -> AsyncGenerator[SubmittedJobInfo, None]:
        for j in active_jobs:
            region = j.aux["region"]
            task_id = j.external_jobid
            probe = ["spawn", "task", "status", task_id, "--region", region, "--check-complete"]
            out = self._run_argv(probe, check=False)
            try:
                status = taskspec.check_complete_to_status(out.returncode)
            except RuntimeError as e:
                self.report_job_error(j, msg=str(e))
                continue
            if status is None:
                yield j  # still running
                continue
            code = self._fetch_exit_code(task_id, region)
            if code == 0:
                self.report_job_success(j)
            else:
                self.report_job_error(
                    j, msg=f"spawn job '{task_id}' exited with code {code}"
                )

    def _fetch_exit_code(self, task_id: str, region: str) -> int:
        """Read the exit code from the CompletionRecord (`spawn task status <id>
        -o json`). Defaults to 1 if the record can't be read/parsed."""
        out = self._run_argv(
            ["spawn", "task", "status", task_id, "--region", region, "-o", "json"], check=False
        )
        try:
            return int(taskspec.parse_completion_record(out.stdout).get("exit_code", 1))
        except Exception:
            self.logger.warning(f"spawn: could not parse completion record for {task_id}")
            return 1

    def cancel_jobs(self, active_jobs: List[SubmittedJobInfo]) -> None:
        for j in active_jobs:
            region = j.aux.get("region") if j.aux else None
            argv = ["spawn", "terminate", j.external_jobid, "--yes"]
            if region:
                argv[3:3] = ["--region", region]
            self._run_argv(argv, check=False)
