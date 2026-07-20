"""Build a spawn TaskSpec for one Snakemake job and parse its CompletionRecord.

snakemake-executor-plugin-spawn no longer builds a user-data script + calls
``spawn launch``; it builds a spawn **TaskSpec** and dispatches ``spawn task run``
(spawn#386). spawn owns instance sizing (truffle), the durable completion record,
the self-termination, and the scoped IAM profile.

Unlike cwl-spawn/miniwdl-spawn, there is **no input/output manifest**: Snakemake's
own S3 storage plugin does the file I/O. The node re-invokes
``python -m snakemake … --mode remote`` (``RealExecutor.format_job_exec``), which
retrieves inputs from S3, runs the one rule, and stores outputs back — all inside
the command. So the TaskSpec's ``command`` carries the whole node program: install
snakemake into a py3.11 venv (stock AL2023 is py3.9), then run the remote command.

Pure (no I/O, no AWS), unit-tested without a cluster.
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Optional

# Family prefix of an instance type, e.g. "c7i" from "c7i.4xlarge".
_FAMILY_RE = re.compile(r"^([a-z][a-z0-9]*?[0-9]+[a-z]*)\.")


def build_command_string(remote_command: str, job_dir: str, install_preamble: str) -> str:
    """Assemble the node program as a single shell string. Pure.

    ``mkdir -p`` + ``cd`` into the (user-writable) job dir, run the snakemake
    install preamble (idempotent py3.11-venv setup that also puts the venv on
    PATH), then run the remote ``python -m snakemake … --mode remote`` command.
    Joined with ``&&`` so a failed install aborts before the remote command; the
    outer spawn wrapper still writes a completion record with the failure.
    """
    jd = job_dir.rstrip("/")
    preamble = install_preamble.strip()
    parts = [f"mkdir -p {shlex.quote(jd)}", f"cd {shlex.quote(jd)}"]
    if preamble:
        # The preamble is a multi-line idempotent installer; run it as its own
        # block, then the remote command. Wrapped in braces so the && chain treats
        # it as one unit.
        parts.append(f"{{ {preamble}\n}}")
    parts.append(remote_command.strip())
    return " && ".join(parts)


def instance_type_family(instance_type: Optional[str]) -> Optional[str]:
    """Extract the family prefix from an instance type ("c7i" from "c7i.4xlarge"),
    or None. Maps the ``instance_type`` setting / ``spawn_instance_type`` resource
    onto TaskSpec ``resources.families`` — spawn has no exact instance-type pin, so
    it steers the family and spawn's sizer picks the cheapest fit within it.
    Lossy: it does NOT pin the exact size."""
    if not instance_type:
        return None
    m = _FAMILY_RE.match(instance_type.strip())
    return m.group(1) if m else None


def mem_mb_to_gib(mem_mb: object) -> Optional[float]:
    """Coerce Snakemake's ``resources.mem_mb`` to GiB, or None if
    missing/unparseable/non-positive."""
    if mem_mb is None:
        return None
    try:
        val = float(mem_mb)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    return val / 1024.0


def build_task_spec(
    *,
    task_id: str,
    remote_command: str,
    job_dir: str,
    install_preamble: str,
    cores: Optional[int] = None,
    mem_mb: object = None,
    instance_hint: Optional[str] = None,
    spot: bool = False,
    ttl: str = "4h",
    on_complete: str = "terminate",
) -> dict:
    """Build the TaskSpec dict for one Snakemake job. Pure.

    No inputs/outputs manifests — Snakemake's S3 storage plugin (invoked by the
    remote command) does all file I/O. The command bundles the install preamble
    and the remote snakemake invocation.
    """
    jd = job_dir.rstrip("/")
    inner = build_command_string(remote_command, jd, install_preamble)
    command = ["/bin/bash", "-lc", inner]

    resources: dict = {}
    if cores and int(cores) > 0:
        resources["cpu"] = int(cores)
    mem_gib = mem_mb_to_gib(mem_mb)
    if mem_gib is not None:
        resources["memory_gib"] = mem_gib
    fam = instance_type_family(instance_hint)
    if fam:
        resources["families"] = [fam]
    if spot:
        resources["purchase"] = "spot"
        resources["fallback"] = "on_demand"

    return {
        "task_id": task_id,
        "command": command,
        "resources": resources,
        "lifecycle": {"ttl": ttl, "on_complete": on_complete},
    }


# ---- completion, from `spawn task status --check-complete` / -o json ----------

def check_complete_to_status(returncode: int) -> Optional[str]:
    """Map ``spawn task status --check-complete`` exit code to a status.

    spawn's contract: 0=completed, 1=failed, 2=running, 3=error. Returns
    "completed"/"failed" on 0/1, None on 2 (not done — poll again), and RAISES on
    3 (spawn couldn't determine status) or any unrecognized code."""
    if returncode == 0:
        return "completed"
    if returncode == 1:
        return "failed"
    if returncode == 2:
        return None
    raise RuntimeError(
        f"`spawn task status --check-complete` returned error/unknown code {returncode}"
    )


def parse_completion_record(stdout: str) -> dict:
    """Parse the CompletionRecord JSON emitted by ``spawn task status <id> -o
    json``. Returns the dict; raises on invalid JSON. Callers read ``exit_code``
    (int) and ``state``."""
    rec = json.loads(stdout)
    if not isinstance(rec, dict):
        raise RuntimeError("completion record is not a JSON object")
    return rec
