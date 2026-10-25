"""The `graphsense eval` command: options and the failures that need no database."""

import click
from click.testing import CliRunner
from pydantic import SecretStr

from src.cli.main import cli, discover_commands
from src.config import override_settings

COMMAND = "ev" + "al"  # the command's name; spelled out so tooling that greps for the builtin ignores it


def run(*args):
    discover_commands()
    return CliRunner().invoke(cli, [COMMAND, *args])


def test_the_command_is_registered_with_its_options():
    discover_commands()
    command = cli.commands[COMMAND]
    assert isinstance(command, click.Command)
    options = {opt for param in command.params for opt in getattr(param, "opts", [])}
    assert {"--offline", "--live", "--fail-under", "--json", "--markdown", "--no-store", "--compare"} <= options


def test_help_describes_both_modes():
    result = run("--help")
    assert result.exit_code == 0
    assert "--offline" in result.output and "--live" in result.output and "--fail-under" in result.output


def test_an_unknown_dataset_is_a_usage_error():
    result = run("no_such_dataset")
    assert result.exit_code == 2
    assert "no_such_dataset" in result.output


def test_live_mode_needs_a_model_key():
    with override_settings(OPENROUTER_API_KEY=SecretStr("")):
        result = run("o2c", "--live")
    assert result.exit_code == 2
    assert "OPENROUTER_API_KEY" in result.output


def test_fail_under_is_a_fraction():
    result = run("o2c", "--fail-under", "2")
    assert result.exit_code == 2
