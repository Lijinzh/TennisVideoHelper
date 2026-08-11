"""安全解析和校验 Tennis Video Helper 的发行版更新。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlparse


GITHUB_LATEST_RELEASE_API = (
    "https://api.github.com/repos/Lijinzh/TennisVideoHelper-Releases/releases/latest"
)
REPOSITORY_OWNER = "Lijinzh"
REPOSITORY_NAME = "TennisVideoHelper-Releases"
MIN_INSTALLER_BYTES = 1 * 1024 * 1024
MAX_INSTALLER_BYTES = 600 * 1024 * 1024
_VERSION_PATTERN = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$"
)
_SHA256_PATTERN = re.compile(r"^sha256:(?P<digest>[0-9a-fA-F]{64})$")
_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
}


class UpdateMetadataError(ValueError):
    """远端更新元数据不完整或不可信。"""


@dataclass(frozen=True, slots=True)
class ReleaseUpdate:
    version: str
    tag: str
    installer_name: str
    download_url: str
    release_url: str
    sha256: str
    size: int
    notes: str


def normalized_version(version: str) -> str:
    match = _VERSION_PATTERN.fullmatch(version.strip())
    if match is None:
        raise UpdateMetadataError(f"不支持的版本号：{version}")
    return ".".join(
        match.group(component) for component in ("major", "minor", "patch")
    )


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_match = _version_match(candidate)
    current_match = _version_match(current)
    candidate_core = _version_core(candidate_match)
    current_core = _version_core(current_match)
    if candidate_core != current_core:
        return candidate_core > current_core
    candidate_prerelease = candidate_match.group("prerelease")
    current_prerelease = current_match.group("prerelease")
    return current_prerelease is not None and candidate_prerelease is None


def parse_github_release(
    payload: bytes | str | dict[str, object],
    *,
    current_version: str,
) -> ReleaseUpdate | None:
    if isinstance(payload, bytes):
        if len(payload) > 2 * 1024 * 1024:
            raise UpdateMetadataError("更新元数据体积异常")
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise UpdateMetadataError("更新元数据不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise UpdateMetadataError("更新元数据格式无效")
    if bool(payload.get("draft")) or bool(payload.get("prerelease")):
        return None

    tag = _required_text(payload, "tag_name")
    version = normalized_version(tag)
    if not is_newer_version(version, current_version):
        return None

    installer_name = f"TennisVideoHelper-Setup-{version}.exe"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateMetadataError("发行版缺少安装包列表")
    asset = next(
        (
            entry
            for entry in assets
            if isinstance(entry, dict) and entry.get("name") == installer_name
        ),
        None,
    )
    if asset is None:
        raise UpdateMetadataError(f"发行版缺少安装包：{installer_name}")

    size = asset.get("size")
    if not isinstance(size, int) or not MIN_INSTALLER_BYTES <= size <= MAX_INSTALLER_BYTES:
        raise UpdateMetadataError("安装包体积超出允许范围")
    digest_match = _SHA256_PATTERN.fullmatch(_required_text(asset, "digest"))
    if digest_match is None:
        raise UpdateMetadataError("安装包缺少有效的 SHA-256")
    download_url = _required_text(asset, "browser_download_url")
    validate_release_download_url(download_url, tag=tag, asset_name=installer_name)

    release_url = _required_text(payload, "html_url")
    _validate_release_page_url(release_url, tag)
    notes = str(payload.get("body") or "").strip()[:2000]
    return ReleaseUpdate(
        version=version,
        tag=tag,
        installer_name=installer_name,
        download_url=download_url,
        release_url=release_url,
        sha256=digest_match.group("digest").lower(),
        size=size,
        notes=notes,
    )


def validate_release_download_url(url: str, *, tag: str, asset_name: str) -> None:
    parsed = urlparse(url)
    expected_path = (
        f"/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/releases/download/{tag}/{asset_name}"
    )
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or unquote(parsed.path) != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise UpdateMetadataError("安装包不是预期的 GitHub Release 资源")


def validate_download_redirect(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _DOWNLOAD_HOSTS:
        raise UpdateMetadataError("安装包下载被重定向到不可信地址")


def verify_installer(path: Path, release: ReleaseUpdate) -> bool:
    try:
        if path.name != release.installer_name or path.stat().st_size != release.size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().lower() == release.sha256
    except OSError:
        return False


def _version_match(version: str) -> re.Match[str]:
    match = _VERSION_PATTERN.fullmatch(version.strip())
    if match is None:
        raise UpdateMetadataError(f"不支持的版本号：{version}")
    return match


def _version_core(match: re.Match[str]) -> tuple[int, int, int]:
    return tuple(
        int(match.group(component)) for component in ("major", "minor", "patch")
    )


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise UpdateMetadataError(f"更新元数据缺少 {key}")
    return value.strip()


def _validate_release_page_url(url: str, tag: str) -> None:
    parsed = urlparse(url)
    expected_path = f"/{REPOSITORY_OWNER}/{REPOSITORY_NAME}/releases/tag/{tag}"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or unquote(parsed.path) != expected_path
    ):
        raise UpdateMetadataError("发行说明页面地址无效")
