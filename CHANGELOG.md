# Changelog

All notable changes to **snakemake-executor-plugin-spawn** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial release: a Snakemake executor plugin (`snakemake --executor spawn`) that
  runs each job on an ephemeral EC2 instance via spore-host/spawn, auto-sized from
  the job's `threads`/`resources.mem_mb` via truffle, with a durable
  `.exitcode`-in-S3 completion signal and `--on-complete terminate` so instances
  self-destruct. Input/output staging is handled by Snakemake's native S3 storage
  plugin. The Snakemake analog of nf-spawn (Nextflow), miniwdl-spawn (WDL), and
  cwl-spawn (CWL). Closes spore-host#405.

[Unreleased]: https://github.com/spore-host/snakemake-executor-plugin-spawn/commits/main
