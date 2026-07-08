# CLAUDE.md — snakemake-executor-plugin-spawn

A **Snakemake executor plugin** that runs each job on an ephemeral EC2 instance
via [spore-host/spawn](https://github.com/spore-host/spawn). The Snakemake analog
of `nf-spawn` (Nextflow), `miniwdl-spawn` (WDL), and `cwl-spawn` (CWL). Part of
the spore.host suite (spore-host#405).

## Versioning & changelog (required)

Follows **[Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)** and keeps a
**[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)**-format `CHANGELOG.md`
(spore.host-wide policy).

**Every user-facing change updates `CHANGELOG.md`** in the same PR under
`## [Unreleased]` (Added/Changed/Deprecated/Removed/Fixed/Security).

**On release:**
1. Rename `## [Unreleased]` → `## [X.Y.Z] - YYYY-MM-DD`; open a fresh Unreleased; update links.
2. SemVer: MAJOR breaking / MINOR feature / PATCH fix (pre-1.0 breaking → MINOR).
3. **Bump `version` in `pyproject.toml` to match** — the release workflow fails if the tag
   and `pyproject.toml` version drift.
4. Tag `vX.Y.Z` → the Release workflow builds + publishes.

## Build & test

Python package (3.11+). Needs the `spawn` and `truffle` CLIs on PATH at runtime,
plus AWS credentials, for real runs.

- `pip install -e ".[dev]"` — install with dev deps
- `pytest` — pure-function unit tests (no AWS; the bulk of coverage)
- `ruff check .` && `mypy snakemake_executor_plugin_spawn` — lint + type-check

Discovery: Snakemake finds this by **module-name prefix** (`snakemake_executor_plugin_*`),
NOT entry points. Editable installs are NOT discovered — CI installs the built
wheel to exercise `snakemake --executor spawn`.

## Architecture

- `executor.py` — `Executor(RemoteExecutor)`; implements `run_job`,
  `check_active_jobs`, `cancel_jobs`. The Snakemake-facing adapter.
- `__init__.py` — exposes `Executor`, `common_settings` (`CommonSettings`),
  `ExecutorSettings` (the three names Snakemake's registry validates).
- `launch.py` / `completion.py` / `sizing.py` / `bootstrap.py` — **pure** helpers
  (no I/O), unit-tested. Keep new logic here, not in executor.py.

## Interface coupling — pin + drift-guard

Subclasses `snakemake_interface_executor_plugins.executors.remote.RemoteExecutor`
(abstract set: `run_job`, `check_active_jobs`, `cancel_jobs`) and calls
`RealExecutor.format_job_exec(job)`. Pin `snakemake-interface-executor-plugins
>=9.4.0,<10`; a drift-guard test asserts the abstract seam is unchanged and fails
loudly on a bump.

## Storage — native, not hand-rolled

Unlike cwl-spawn/miniwdl-spawn, we do NOT manually bridge input/output files.
Snakemake's own S3 storage plugin (`snakemake-storage-plugin-s3`) does it: with
`--default-storage-provider s3` (forwarded automatically via
`pass_default_storage_provider_args`), each node's `python -m snakemake --mode
remote` invocation retrieves inputs from S3 and stores outputs back itself. The
node auto-installs snakemake + the storage plugin at boot (`bootstrap.py`).

## Cost safety

Real runs launch billable EC2 instances. Any real-AWS test MUST set a TTL,
terminate explicitly, and leak-check afterward (no orphaned instances). Jobs
always launch with `--on-complete terminate` and a TTL.

## Reuse / lineage

Mirrors cwl-spawn/miniwdl-spawn/nf-spawn (same `spawn` CLI contract, same
`.exitcode`-in-S3 completion, same truffle auto-sizing). `launch.py`,
`completion.py`, `sizing.py` ported ~verbatim (sizing reads Snakemake `mem_mb`).
Reference plugin: `snakemake-executor-plugin-googlebatch` (one ephemeral VM per job).
