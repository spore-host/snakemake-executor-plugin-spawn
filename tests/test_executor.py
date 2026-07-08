"""Unit-test the executor's three methods with a fake spawn/aws (no AWS, no real
Snakemake workflow). We build a SpawnExecutor via object.__new__ to bypass
RemoteExecutor.__init__ and inject the collaborators the methods touch.
"""

import asyncio
import types

from snakemake_executor_plugin_spawn.executor import SpawnExecutor
from snakemake_interface_executor_plugins.executors.base import SubmittedJobInfo


class FakeJob:
    def __init__(self, jobid=1, name="myrule", threads=4, mem_mb=8000, attempt=1):
        self.jobid = jobid
        self.name = name
        self.threads = threads
        self.resources = {"mem_mb": mem_mb, "_cores": threads}
        self.attempt = attempt


class FakeCompleted:
    def __init__(self, rc=0, out=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


def _make_executor(run_calls, settings=None):
    """A SpawnExecutor with __init__ bypassed and collaborators faked."""
    ex = object.__new__(SpawnExecutor)
    ex.settings = settings or types.SimpleNamespace(
        region="us-east-1", ttl="1h", workdir_s3="s3://b/runs", instance_type=None, spot=False
    )
    ex.logger = types.SimpleNamespace(info=lambda *a, **k: None)
    ex.submitted = []
    ex.succeeded = []
    ex.errored = []
    ex.report_job_submission = lambda info: ex.submitted.append(info)
    ex.report_job_success = lambda info: ex.succeeded.append(info)
    ex.report_job_error = lambda info, msg=None, **k: ex.errored.append((info, msg))
    ex.format_job_exec = lambda job: "python -m snakemake --mode remote --target-jobs x"
    ex._run_argv = lambda argv, check: run_calls.append(list(argv)) or FakeCompleted(0, "")
    return ex


def test_run_job_launches_and_reports_submission():
    calls = []
    ex = _make_executor(calls)
    ex.run_job(FakeJob())

    # a `spawn launch` was issued
    assert any(c[:2] == ["spawn", "launch"] for c in calls), calls
    launch_argv = next(c for c in calls if c[:2] == ["spawn", "launch"])
    assert "--on-complete" in launch_argv
    assert launch_argv[launch_argv.index("--on-complete") + 1] == "terminate"
    # submission recorded with instance name + s3 prefix in aux
    assert len(ex.submitted) == 1
    info = ex.submitted[0]
    assert info.external_jobid.startswith("smk-")
    assert info.aux["s3_prefix"].endswith("/try-1")
    assert info.aux["region"] == "us-east-1"


def _drain(agen):
    async def run():
        return [x async for x in agen]
    return asyncio.run(run())


def test_check_active_jobs_success_error_running():
    job = FakeJob()
    infos = {
        "ok": SubmittedJobInfo(job, external_jobid="smk-ok", aux={"s3_prefix": "s3://b/ok", "region": "us-east-1"}),
        "bad": SubmittedJobInfo(job, external_jobid="smk-bad", aux={"s3_prefix": "s3://b/bad", "region": "us-east-1"}),
        "run": SubmittedJobInfo(job, external_jobid="smk-run", aux={"s3_prefix": "s3://b/run", "region": "us-east-1"}),
    }
    ex = _make_executor([])

    def fake_run(argv, check):
        # argv is the exitcode probe: aws s3 cp <prefix>/.exitcode -
        uri = argv[3]
        if "s3://b/ok/" in uri:
            return FakeCompleted(0, "0\n")
        if "s3://b/bad/" in uri:
            return FakeCompleted(0, "137\n")
        return FakeCompleted(1, "")  # not present yet -> still running

    ex._run_argv = fake_run
    still = _drain(ex.check_active_jobs(list(infos.values())))

    assert ex.succeeded and ex.succeeded[0].external_jobid == "smk-ok"
    assert ex.errored and ex.errored[0][0].external_jobid == "smk-bad"
    assert "137" in ex.errored[0][1]
    assert [j.external_jobid for j in still] == ["smk-run"]


def test_cancel_jobs_terminates():
    calls = []
    ex = _make_executor(calls)
    job = FakeJob()
    ex.cancel_jobs([
        SubmittedJobInfo(job, external_jobid="smk-x", aux={"s3_prefix": "s3://b/x", "region": "eu-west-1"})
    ])
    assert calls and calls[0] == ["spawn", "terminate", "smk-x", "--yes"]
