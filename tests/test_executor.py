"""Unit-test the executor's three methods with a fake spawn CLI (no AWS, no real
Snakemake workflow). We build a SpawnExecutor via object.__new__ to bypass
RemoteExecutor.__init__ and inject the collaborators the methods touch.
"""

import asyncio
import json
import types
from pathlib import Path

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
        region="us-east-1",
        ttl="1h",
        workdir_s3="s3://b/runs",
        instance_type=None,
        spot=False,
        cost_limit=None,
    )
    ex.logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
    ex.submitted = []
    ex.succeeded = []
    ex.errored = []
    ex.report_job_submission = lambda info: ex.submitted.append(info)
    ex.report_job_success = lambda info: ex.succeeded.append(info)
    ex.report_job_error = lambda info, msg=None, **k: ex.errored.append((info, msg))
    ex.format_job_exec = lambda job: "python -m snakemake --mode remote --target-jobs x"
    ex._run_argv = lambda argv, check: run_calls.append(list(argv)) or FakeCompleted(0, "")
    return ex


def _spec_capturing_executor(settings=None):
    """An executor whose fake spawn CLI reads the TaskSpec while it still exists.

    run_job unlinks the temp spec file once dispatch returns, so the assertion has
    to happen inside the call, not after it.
    """
    seen: dict = {}
    calls: list = []

    def runner(argv, check):
        calls.append(list(argv))
        if argv[:3] == ["spawn", "task", "run"] and "--spec" in argv:
            seen["spec"] = json.loads(
                Path(argv[argv.index("--spec") + 1]).read_text()
            )
        return FakeCompleted(0, "")

    ex = _make_executor(calls, settings=settings)
    ex._run_argv = runner
    return ex, seen


def _settings(**over):
    base = dict(
        region="us-east-1", ttl="1h", workdir_s3="s3://b/runs",
        instance_type=None, spot=False, cost_limit=None,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def test_cost_limit_absent_from_spec_by_default():
    ex, seen = _spec_capturing_executor()
    ex.run_job(FakeJob())
    assert "cost_limit" not in seen["spec"]["lifecycle"]


def test_cost_limit_from_settings_reaches_the_spec():
    ex, seen = _spec_capturing_executor(_settings(cost_limit=0.25))
    ex.run_job(FakeJob())
    assert seen["spec"]["lifecycle"]["cost_limit"] == 0.25


def test_per_rule_resource_overrides_the_workflow_setting():
    # A single workflow-wide cap has to be sized for the most expensive rule, which
    # leaves every cheaper rule effectively uncapped — so the per-rule resource wins,
    # the same precedence spawn_instance_type already has over --spawn-instance-type.
    ex, seen = _spec_capturing_executor(_settings(cost_limit=0.25))
    job = FakeJob()
    job.resources["spawn_cost_limit"] = 2.0
    ex.run_job(job)
    assert seen["spec"]["lifecycle"]["cost_limit"] == 2.0


def test_run_job_dispatches_detached_and_reports_submission():
    calls = []
    ex = _make_executor(calls)
    ex.run_job(FakeJob())

    # a detached `spawn task run` was issued (no --wait)
    run_argv = next((c for c in calls if c[:3] == ["spawn", "task", "run"]), None)
    assert run_argv is not None, calls
    assert "--spec" in run_argv
    assert "--wait" not in run_argv
    # submission recorded with task id + region in aux
    assert len(ex.submitted) == 1
    info = ex.submitted[0]
    assert info.external_jobid.startswith("smk-")
    assert info.external_jobid.endswith("-1")  # attempt folded in
    assert info.aux["region"] == "us-east-1"


def _drain(agen):
    async def run():
        return [x async for x in agen]
    return asyncio.run(run())


def test_check_active_jobs_success_error_running():
    job = FakeJob()
    infos = {
        "ok": SubmittedJobInfo(job, external_jobid="smk-ok-1", aux={"region": "us-east-1"}),
        "bad": SubmittedJobInfo(job, external_jobid="smk-bad-1", aux={"region": "us-east-1"}),
        "run": SubmittedJobInfo(job, external_jobid="smk-run-1", aux={"region": "us-east-1"}),
    }
    ex = _make_executor([])

    def fake_run(argv, check):
        task_id = argv[3]  # spawn task status <task_id> ...
        if "--check-complete" in argv:
            if task_id == "smk-ok-1":
                return FakeCompleted(0)  # completed
            if task_id == "smk-bad-1":
                return FakeCompleted(1)  # failed
            return FakeCompleted(2)  # running
        # -o json fetch
        if task_id == "smk-ok-1":
            return FakeCompleted(0, '{"exit_code":0,"state":"completed"}')
        if task_id == "smk-bad-1":
            return FakeCompleted(1, '{"exit_code":137,"state":"failed"}')
        return FakeCompleted(0, "")

    ex._run_argv = fake_run
    still = _drain(ex.check_active_jobs(list(infos.values())))

    assert ex.succeeded and ex.succeeded[0].external_jobid == "smk-ok-1"
    assert ex.errored and ex.errored[0][0].external_jobid == "smk-bad-1"
    assert "137" in ex.errored[0][1]
    assert [j.external_jobid for j in still] == ["smk-run-1"]


def test_cancel_jobs_terminates_by_task_id():
    calls = []
    ex = _make_executor(calls)
    job = FakeJob()
    ex.cancel_jobs([
        SubmittedJobInfo(job, external_jobid="smk-x-1", aux={"region": "eu-west-1"})
    ])
    assert calls and calls[0] == ["spawn", "terminate", "smk-x-1", "--region", "eu-west-1", "--yes"]
