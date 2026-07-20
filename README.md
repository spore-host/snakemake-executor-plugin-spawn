# snakemake-executor-plugin-spawn

A [Snakemake](https://snakemake.github.io) **executor plugin** that runs each job
on a purpose-sized, ephemeral EC2 instance via
[spore-host/spawn](https://github.com/spore-host/spawn) — the Snakemake analog of
[nf-spawn](https://github.com/spore-host/nf-spawn) (Nextflow),
[miniwdl-spawn](https://github.com/spore-host/miniwdl-spawn) (WDL), and
[cwl-spawn](https://github.com/spore-host/cwl-spawn) (CWL). Part of the spore.host
suite.

Each job is auto-sized from its `threads`/`resources` (via `truffle`), launched
with a TTL and `--on-complete terminate`, and torn down when it finishes — so a
workflow costs only the compute each job actually uses, with no cluster to run and
no forgotten instances.

## Install

```bash
pip install snakemake-executor-plugin-spawn
```

Requires the `spawn` and `truffle` CLIs on `PATH` and AWS credentials for real
runs.

## Use

```bash
snakemake \
  --executor spawn \
  --default-storage-provider s3 \
  --default-storage-prefix s3://my-bucket/snakemake-runs \
  --spawn-region us-east-1 \
  --spawn-ttl 4h \
  --jobs 8 \
  <target>
```

Snakemake retrieves inputs from S3, dispatches each job to its own spawn instance
(which retrieves/stores its files via the same S3 storage provider and
self-terminates on completion), and collects results — no shared filesystem, no
standing infrastructure.

### Sizing

A job's EC2 instance is sized by spawn (via truffle), from, in order:
1. an explicit instance-type override (`--spawn-instance-type`), which steers the
   instance _family_ (e.g. `c7i.4xlarge` → the `c7i` family),
2. the cheapest instance that fits the job's `threads` + `resources.mem_mb`,
3. a default.

## How it works

The plugin builds a spawn **TaskSpec** and dispatches `spawn task run` (detached)
per job (spawn#386); spawn sizes and launches the instance, writes a durable
completion record, and self-terminates. `check_active_jobs` polls
`spawn task status` for completion. On the instance, a fresh
`python -m snakemake … --mode remote` invocation runs the one rule — the node
auto-installs snakemake + the S3 storage plugin at boot (no prebuilt AMI needed),
and Snakemake's S3 storage plugin does all file I/O (spawn stages nothing here).

## License

Apache-2.0
