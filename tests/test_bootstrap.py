from snakemake_executor_plugin_spawn.bootstrap import build_install_preamble


def test_install_preamble_uses_py311_venv_and_guards():
    p = build_install_preamble()
    # Snakemake 9 needs py>=3.11; AL2023 system python is 3.9, so install 3.11.
    assert "python3.11" in p
    assert "venv" in p
    assert "pip install" in p
    assert "snakemake-storage-plugin-s3" in p
    # idempotent: skips if the venv's snakemake already exists
    assert "/bin/snakemake ]" in p
    # puts the venv on PATH so the remote `python -m snakemake` resolves to it
    assert "export PATH=" in p
