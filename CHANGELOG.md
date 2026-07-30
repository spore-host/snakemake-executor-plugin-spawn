# Changelog

All notable changes to **snakemake-executor-plugin-spawn** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Engine-composition CI test** (`tests/composition/`, `.github/workflows/composition-test.yml`):
  a REAL `snakemake --executor spawn` run driven end-to-end against the
  [Substrate](https://github.com/scttfrdmn/substrate) AWS emulator — no real AWS,
  no cost. Asserts the plugin still composes with current Snakemake + spawn:
  dispatch (`spawn task run`) → completion record → exit code → job
  success/failure, for both the happy path (unseeded ⇒ exit 0) and the failure
  path (a seeded nonzero completion, substrate#360, ⇒ Snakemake reports "exited
  with code 7"). Uses a **no-output rule** — Snakemake gates a run on its declared
  `output:` existing in storage (`wait_for_files`), which needs real execution the
  emulator deliberately doesn't do; a rule with no output has no such gate. This
  is a full-engine run (not a seam-level fallback), matching the miniwdl/airflow
  adapters' bar. Part of spore-host#397; closes #3.

## [0.2.0] - 2026-07-19

### Changed
- **snakemake-executor-plugin-spawn now dispatches each job through `spawn task
  run`** instead of orchestrating the launch itself (spawn#386 adapter migration).
  `run_job` builds a spawn **TaskSpec** and runs `spawn task run` (detached);
  `check_active_jobs` polls `spawn task status --check-complete` and reads the exit
  code from the **CompletionRecord**; `cancel_jobs` terminates by task id. spawn now
  owns instance sizing (truffle), the durable completion record, self-termination,
  and a **scoped least-privilege IAM profile** (was `--iam-policy s3:FullAccess`).
  Snakemake's own S3 storage plugin still does all file I/O — the node's
  `python -m snakemake … --mode remote` invocation (plus the py3.11 venv install
  preamble) is carried in the TaskSpec command. The storage bucket(s) from the
  remote command's `--default-storage-prefix` are declared in the TaskSpec's
  `resources.s3_read_write` so spawn's scoped instance profile grants the
  `ListBucket` + object access the storage plugin needs (requires spawn ≥ 0.84.0).
- **The `instance_type` setting now steers the instance _family_** (e.g.
  `c7i.4xlarge` → the `c7i` family) rather than pinning the exact type; spawn's
  sizer picks the cheapest fit within it. (Exact-pin support is tracked as a spawn
  TaskSpec follow-up.)
- **The on-instance job dir moved to `/var/tmp/snakemake_spawn_job`** (was
  `/mnt/snakemake_spawn_job`): spawn runs the command as the instance's unprivileged
  login user, which can't create dirs under the root-owned `/mnt`.
- `truffle` is no longer required on `PATH` (spawn sizes the instance itself);
  `spawn` and AWS credentials are still required.

### Removed
- Bundled launch/completion/sizing machinery (`launch.py`, `completion.py`,
  `sizing.py`) and `bootstrap.build_user_data` — spawn owns launch/completion now;
  `bootstrap` keeps only the snakemake install preamble.

## [0.1.0] - 2026-07-07

### Added
- Initial release: a Snakemake executor plugin (`snakemake --executor spawn`) that
  runs each job on an ephemeral EC2 instance via spore-host/spawn, auto-sized from
  the job's `threads`/`resources.mem_mb` via truffle, with a durable
  `.exitcode`-in-S3 completion signal and `--on-complete terminate` so instances
  self-destruct. Input/output staging is handled by Snakemake's native S3 storage
  plugin. The Snakemake analog of nf-spawn (Nextflow), miniwdl-spawn (WDL), and
  cwl-spawn (CWL). Closes spore-host#405.
- Verified end-to-end on real AWS: a one-rule Snakefile ran on a spawned EC2
  instance (auto-installed Python 3.11 + snakemake + the S3 storage plugin at
  boot), wrote its output to S3, and self-terminated (leak-checked clean).

[Unreleased]: https://github.com/spore-host/snakemake-executor-plugin-spawn/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/spore-host/snakemake-executor-plugin-spawn/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/spore-host/snakemake-executor-plugin-spawn/releases/tag/v0.1.0
