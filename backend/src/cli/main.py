"""``graphsense`` command line entry point.

Commands live in ``src/cli/commands/*.py`` and are discovered at start-up: a
module exposes a module-level ``command`` (a ``click.Command`` or
``click.Group``) and is registered under that command's name.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys

import click

from src.cli import commands as _commands_pkg


@click.group(name="graphsense", help="Operate GraphSense: dataset packages, ingestion, catalog and evaluation.")
def cli() -> None:
    pass


def discover_commands() -> list[str]:
    """Import every command module and register its ``command``.  Returns the registered names."""
    registered = []
    for module_info in sorted(pkgutil.iter_modules(_commands_pkg.__path__), key=lambda m: m.name):
        try:
            module = importlib.import_module(f"{_commands_pkg.__name__}.{module_info.name}")
        except ImportError as exc:
            # One command with a missing optional dependency must not take the CLI down.
            click.echo(f"warning: command module {module_info.name!r} not loaded: {exc}", err=True)
            continue
        command = getattr(module, "command", None)
        if isinstance(command, click.Command):
            cli.add_command(command)
            registered.append(command.name or module_info.name)
    return registered


def main(argv: list[str] | None = None) -> None:
    discover_commands()
    cli.main(args=argv, prog_name="graphsense", standalone_mode=True)


if __name__ == "__main__":
    main(sys.argv[1:])
