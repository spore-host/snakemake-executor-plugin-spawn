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

A job's EC2 instance type is chosen by, in order:
1. an explicit instance-type override (`--spawn-instance-type`),
2. the cheapest instance that fits the job's `threads` + `resources.mem_mb` via
   `truffle search --pick-first`,
3. a default (`t3.medium`).

## How it works

Each job runs a fresh `python -m snakemake … --mode remote` invocation on its
instance; the node auto-installs snakemake + the S3 storage plugin at boot (no
prebuilt AMI needed), runs the one rule, and writes a final `.exitcode` object to
S3 — the durable completion signal the plugin polls (the instance self-terminates,
so it can't be probed directly).

## License

Apache-2.0
