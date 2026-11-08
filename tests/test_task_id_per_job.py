"""#19: the spawn task id (which keys the completion record) must be one per
(job, attempt), not one per (rule, attempt). A wildcard fan-out runs N jobs of
one rule; with a rule-keyed id they shared one completion record, so a failed
shard could be reported as succeeded (and the reverse)."""

from snakemake_interface_executor_plugins.executors.base import SubmittedJobInfo

from test_executor import FakeCompleted, FakeJob, _drain, _make_executor


def _ids(ex, jobs):
    return [ex._task_id(j) for j in jobs]


def test_fanout_jobs_of_one_rule_get_distinct_task_ids():
    ex = _make_executor([])
    jobs = [FakeJob(jobid=i, name="stats") for i in (2, 3, 4, 5)]
    ids = _ids(ex, jobs)
    assert len(set(ids)) == 4, ids
    assert ids == ["smk-stats-2-1", "smk-stats-3-1", "smk-stats-4-1", "smk-stats-5-1"]


def test_task_id_is_stable_across_calls_and_changes_per_attempt():
    ex = _make_executor([])
    job = FakeJob(jobid=4, name="stats", attempt=1)
    assert ex._task_id(job) == ex._task_id(job)  # deterministic for the same job
    retry = FakeJob(jobid=4, name="stats", attempt=2)  # Snakemake retries the SAME job: same jobid
    assert ex._task_id(retry) == "smk-stats-4-2"
    assert ex._task_id(retry) != ex._task_id(job)


def test_truncation_never_drops_the_jobid_or_attempt():
    ex = _make_executor([])
    long_rule = "a_very_long_rule_name_that_goes_on_and_on_for_quite_a_while_indeed"
    a = ex._task_id(FakeJob(jobid=11, name=long_rule))
    b = ex._task_id(FakeJob(jobid=12, name=long_rule))
    assert len(a) <= 60 and len(b) <= 60
    assert a.endswith("-11-1") and b.endswith("-12-1")
    assert a != b
    assert "--" not in a and not a.startswith("-")


def test_group_job_uuid_jobid_is_sanitized():
    ex = _make_executor([])
    tid = ex._task_id(FakeJob(jobid="5A0e1c2b-UUID_x", name="grp"))
    assert tid == "smk-grp-5a0e1c2b-uuid-x-1"


def test_fanout_reports_each_shard_from_its_own_completion_record():
    """The measured failure: 4 shards of one rule, one fails. Each must be
    attributed from its OWN record, so exactly the failed shard errors."""
    ex = _make_executor([])
    runs = []
    ex._run_argv = lambda argv, check: runs.append(list(argv)) or FakeCompleted(0, "")
    jobs = [FakeJob(jobid=i, name="stats") for i in (2, 3, 4, 5)]
    for j in jobs:
        ex.run_job(j)
    submitted = list(ex.submitted)
    assert len({i.external_jobid for i in submitted}) == 4

    failed = ex._task_id(jobs[1])  # jobid 3 fails; the rest succeed

    def fake_run(argv, check):
        tid = argv[3]
        if "--check-complete" in argv:
            return FakeCompleted(1 if tid == failed else 0)
        code = 1 if tid == failed else 0
        return FakeCompleted(code, f'{{"exit_code":{code},"state":"completed"}}')

    ex._run_argv = fake_run
    still = _drain(ex.check_active_jobs(submitted))

    assert still == []
    assert [i.job.jobid for i in ex.succeeded] == [2, 4, 5]
    assert [i.job.jobid for i, _ in ex.errored] == [3]


def test_submitted_info_carries_the_per_job_id():
    ex = _make_executor([])
    ex.run_job(FakeJob(jobid=7, name="align"))
    info = ex.submitted[0]
    assert isinstance(info, SubmittedJobInfo)
    assert info.external_jobid == "smk-align-7-1"
