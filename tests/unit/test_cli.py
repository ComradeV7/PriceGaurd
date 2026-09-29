"""Tests for CLI commands."""

from typer.testing import CliRunner

from priceguard.cli import app

runner = CliRunner()


def test_cli_help():
    """CLI help shows all commands."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "ingest" in result.stdout
    assert "generate" in result.stdout
    assert "validate" in result.stdout
    assert "backtest" in result.stdout
    assert "export" in result.stdout
    assert "review" in result.stdout


def test_ingest_offline_mode():
    """Ingest offline mode uses sample data."""
    result = runner.invoke(app, ["ingest", "--offline"])

    assert result.exit_code == 0
    assert "Offline mode" in result.stdout or "sample" in result.stdout.lower()


def test_generate_offline_smoke(tmp_path):
    """Generate runs offline against the committed sample data."""
    result = runner.invoke(app, ["generate", "--offline", "--config-dir", "config"])
    assert result.exit_code == 0
    assert "Generated" in result.stdout


def test_validate_smoke():
    """Validate runs against the generated database."""
    runner.invoke(app, ["generate", "--offline", "--config-dir", "config"])
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0
    assert "exceptions" in result.stdout.lower() or "No exceptions" in result.stdout
