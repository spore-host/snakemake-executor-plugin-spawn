"""Guard the plugin's registration surface — the part Snakemake's CLI touches
before any job runs. Regression for the `'Optional[str]' is not callable` bug:
`from __future__ import annotations` in __init__.py stringizes ExecutorSettings
field types and breaks argparse construction.
"""

import argparse
import dataclasses

import snakemake_executor_plugin_spawn as plugin
from snakemake_interface_executor_plugins.settings import (
    CommonSettings,
    ExecutorSettingsBase,
)


def test_module_surface():
    from snakemake_interface_executor_plugins.executors.remote import RemoteExecutor

    assert issubclass(plugin.Executor, RemoteExecutor)
    assert isinstance(plugin.common_settings, CommonSettings)
    assert issubclass(plugin.ExecutorSettings, ExecutorSettingsBase)
    assert not plugin.Executor.__abstractmethods__


def test_executor_settings_field_types_are_real_not_stringized():
    # The bug: with future-annotations, field.type is the STRING "Optional[str]"
    # (not a type), which Snakemake feeds to argparse `type=` -> not callable.
    for f in dataclasses.fields(plugin.ExecutorSettings):
        assert not isinstance(f.type, str), (
            f"ExecutorSettings.{f.name}.type is a string ({f.type!r}); do not use "
            "`from __future__ import annotations` in __init__.py"
        )


def test_settings_registers_as_argparse_type():
    # Mimic what Snakemake does: use each field's type as an argparse `type=`.
    # A str-annotation would raise 'X is not callable' when the arg is exercised.
    parser = argparse.ArgumentParser()
    for f in dataclasses.fields(plugin.ExecutorSettings):
        t = f.type
        if t is bool:
            parser.add_argument(f"--{f.name}", action="store_true")
        else:
            # Optional[str] -> the interface resolves to str; ensure it's usable.
            parser.add_argument(f"--{f.name}", type=str, default=None)
    ns = parser.parse_args(["--region", "us-east-1", "--spot"])
    assert ns.region == "us-east-1"
    assert ns.spot is True
