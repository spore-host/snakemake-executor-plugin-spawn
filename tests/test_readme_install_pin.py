"""The README's install pin must match the released version (snakemake#13)."""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert m, "pyproject.toml has no version"
    return m.group(1)


def test_readme_does_not_claim_a_pypi_install():
    """`pip install snakemake-executor-plugin-spawn` cannot work — the package is
    not on PyPI, and the install line is the first thing a new user runs. It was
    the first thing that failed for them (snakemake#13), the same shape as
    nf-spawn#90."""
    readme = (ROOT / "README.md").read_text()
    assert not re.search(
        r"(?m)^\s*pip install snakemake-executor-plugin-spawn\s*$", readme
    ), (
        "README advertises a bare PyPI install, which fails: "
        "'No matching distribution found'. Use the git+https form pinned to a release."
    )


def test_readme_install_pin_matches_the_project_version():
    """The git+https pin is reproducible only if it names a tag that exists. Tying
    it to pyproject's version means the release ritual (which already bumps
    pyproject) keeps it true, instead of it silently rotting one release later."""
    readme = (ROOT / "README.md").read_text()
    version = _pyproject_version()

    pins = set(re.findall(r"@v(\d+\.\d+\.\d+)", readme))
    assert pins, "README has no git+https version pin for the install"
    assert pins == {version}, (
        f"README pins {sorted(pins)} but pyproject.toml is {version}. "
        "On release, bump BOTH — the pin names a git tag, so a stale one sends "
        "users to a version that does not exist yet."
    )
