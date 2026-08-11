from pathlib import Path

from tennis_video_helper.media.publication import replace_output_directory


def test_replace_output_directory_retries_transient_permission_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "result"
    working = tmp_path / ".result.staging"
    output.mkdir()
    working.mkdir()
    (output / "old.txt").write_text("old", encoding="utf-8")
    (working / "new.txt").write_text("new", encoding="utf-8")
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(path: Path, target: Path):
        nonlocal attempts
        if path == working and attempts < 2:
            attempts += 1
            raise PermissionError("temporary scanner lock")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr(
        "tennis_video_helper.media.publication.time.sleep",
        lambda _delay: None,
    )

    replace_output_directory(working, output)

    assert attempts == 2
    assert (output / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (output / "old.txt").exists()
