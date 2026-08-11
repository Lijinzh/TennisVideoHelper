from pathlib import Path

import pytest

from tennis_video_helper.app.updater import (
    ReleaseUpdate,
    UpdateMetadataError,
    is_newer_version,
    parse_github_release,
    validate_download_redirect,
    verify_installer,
)


def _release_payload(*, version: str = "0.1.2", digest: str = "a" * 64):
    asset_name = f"TennisVideoHelper-Setup-{version}.exe"
    return {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": False,
        "html_url": (
            "https://github.com/Lijinzh/TennisVideoHelper/"
            f"releases/tag/v{version}"
        ),
        "body": "更新说明",
        "assets": [
            {
                "name": asset_name,
                "size": 10 * 1024 * 1024,
                "digest": f"sha256:{digest}",
                "browser_download_url": (
                    "https://github.com/Lijinzh/TennisVideoHelper/releases/"
                    f"download/v{version}/{asset_name}"
                ),
            }
        ],
    }


def test_version_comparison_handles_stable_and_prerelease_versions() -> None:
    assert is_newer_version("0.1.2", "0.1.1") is True
    assert is_newer_version("0.1.1", "0.1.1") is False
    assert is_newer_version("0.1.1", "0.1.1-beta.1") is True
    assert is_newer_version("0.1.1-beta.2", "0.1.1") is False


def test_github_release_requires_exact_versioned_installer_and_digest() -> None:
    release = parse_github_release(_release_payload(), current_version="0.1.1")

    assert release is not None
    assert release.version == "0.1.2"
    assert release.installer_name == "TennisVideoHelper-Setup-0.1.2.exe"
    assert release.sha256 == "a" * 64

    invalid = _release_payload(digest="invalid")
    with pytest.raises(UpdateMetadataError, match="SHA-256"):
        parse_github_release(invalid, current_version="0.1.1")


def test_github_release_rejects_untrusted_download_url() -> None:
    payload = _release_payload()
    payload["assets"][0]["browser_download_url"] = "https://example.com/update.exe"

    with pytest.raises(UpdateMetadataError, match="GitHub Release"):
        parse_github_release(payload, current_version="0.1.1")


def test_download_redirect_accepts_only_expected_https_hosts() -> None:
    validate_download_redirect("https://release-assets.githubusercontent.com/file")
    with pytest.raises(UpdateMetadataError, match="不可信"):
        validate_download_redirect("https://example.com/file")


def test_installer_verification_checks_name_size_and_hash(tmp_path: Path) -> None:
    installer = tmp_path / "TennisVideoHelper-Setup-0.1.2.exe"
    installer.write_bytes(b"verified installer")
    import hashlib

    release = ReleaseUpdate(
        version="0.1.2",
        tag="v0.1.2",
        installer_name=installer.name,
        download_url="https://github.com/placeholder",
        release_url="https://github.com/placeholder",
        sha256=hashlib.sha256(installer.read_bytes()).hexdigest(),
        size=installer.stat().st_size,
        notes="",
    )

    assert verify_installer(installer, release) is True
    installer.write_bytes(b"tampered")
    assert verify_installer(installer, release) is False
