from typer.testing import CliRunner

from tennis_video_helper.cli import app


runner = CliRunner()


def test_cli_help_lists_analyze_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "analyze" in result.stdout
