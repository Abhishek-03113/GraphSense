"""The graphsense CLI: command discovery and `package lint` / `package ddl`."""

import json

import click
from click.testing import CliRunner

from src.cli.main import cli, discover_commands
from tests.conftest import O2C_DIR, TOY_DATA_DIR, TOY_DIR


def run(*args):
    discover_commands()
    return CliRunner().invoke(cli, list(args))


def test_commands_are_discovered_from_the_commands_package():
    assert "package" in discover_commands()
    assert isinstance(cli.commands["package"], click.Group)


def test_lint_o2c_by_id_passes_and_prints_coverage():
    result = run("package", "lint", "o2c")
    assert result.exit_code == 0, result.output
    assert "Package o2c 2.0.0" in result.output
    assert "0 error(s)" in result.output
    assert "columns with description: 211/211 (100%)" in result.output
    assert result.output.rstrip().endswith("OK")


def test_lint_accepts_a_directory():
    result = run("package", "lint", str(TOY_DIR), "--data-root", str(TOY_DATA_DIR.parent))
    assert result.exit_code == 0, result.output
    assert "unlabelled_code" in result.output  # checks on real values ran


def test_lint_strict_fails_on_warnings():
    assert run("package", "lint", str(TOY_DIR), "--strict").exit_code == 1


def test_lint_json_output():
    result = run("package", "lint", "o2c", "--json")
    payload = json.loads(result.output)
    assert payload["ok"] is True and payload["package"] == "o2c"
    assert payload["coverage"]["tables"] == 19
    assert len(payload["content_hash"]) == 64


def test_lint_reports_errors_and_fails(package_copy):
    path = package_copy(edits={"semantics/examples.yaml": ("FROM authors a\n    JOIN books b", "FROM authors a\n    JOIN shelves b")})
    result = run("package", "lint", str(path))
    assert result.exit_code == 1
    assert "error   [example_sql]" in result.output
    assert "undeclared table 'shelves'" in result.output


def test_lint_reports_unreadable_packages(package_copy):
    path = package_copy(edits={"tables/books.yaml": ("primary_key: [isbn]", "primary_key: [nope]")})
    result = run("package", "lint", str(path))
    assert result.exit_code == 1
    assert "primary key column 'nope'" in result.output


def test_lint_unknown_package():
    result = run("package", "lint", "no_such_package")
    assert result.exit_code == 1
    assert "Unknown dataset" in result.output


def test_ddl_prints_create_statements():
    result = run("package", "ddl", "o2c")
    assert result.exit_code == 0
    assert result.output.count("CREATE TABLE") == 19
    assert 'CREATE SCHEMA IF NOT EXISTS "ds_o2c"' in result.output
    custom = run("package", "ddl", str(O2C_DIR), "--schema", "staging")
    assert 'CREATE TABLE "staging"."sales_order_items"' in custom.output
