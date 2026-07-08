"""Drift guard: this plugin subclasses Snakemake's executor-plugin interface,
which is versioned independently. These tests fail loudly if a bump moves the
seam — bump the pin deliberately, re-verify, update here. See CLAUDE.md.
"""

import inspect

from snakemake_interface_executor_plugins.executors.base import (
    AbstractExecutor,
    SubmittedJobInfo,
)
from snakemake_interface_executor_plugins.executors.real import RealExecutor
from snakemake_interface_executor_plugins.executors.remote import RemoteExecutor


def test_remote_executor_abstract_seam():
    # We implement exactly these three. If cwltool^H^Hsnakemake adds/renames an
    # abstract method, our Executor would fail to instantiate — catch it here.
    assert RemoteExecutor.__abstractmethods__ == frozenset(
        {"run_job", "check_active_jobs", "cancel_jobs"}
    )


def test_run_job_and_check_active_jobs_signatures():
    assert "job" in inspect.signature(AbstractExecutor.run_job).parameters
    ca = inspect.signature(RemoteExecutor.check_active_jobs)
    assert "active_jobs" in ca.parameters


def test_format_job_exec_exists():
    # run_job builds the node command from this.
    assert hasattr(RealExecutor, "format_job_exec")
    assert "job" in inspect.signature(RealExecutor.format_job_exec).parameters


def test_submitted_job_info_fields():
    import dataclasses

    fields = {f.name for f in dataclasses.fields(SubmittedJobInfo)}
    assert {"job", "external_jobid", "aux"} <= fields


def test_report_helpers_exist():
    for name in ("report_job_submission", "report_job_success", "report_job_error"):
        assert hasattr(RemoteExecutor, name), name
