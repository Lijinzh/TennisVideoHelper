"""Qt 异步自动更新控制器。"""

from __future__ import annotations

from datetime import date
import hashlib
import os
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import QObject, QProcess, QSettings, QStandardPaths, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QProgressDialog

from tennis_video_helper.app.updater import (
    GITHUB_LATEST_RELEASE_API,
    ReleaseUpdate,
    UpdateMetadataError,
    parse_github_release,
    validate_download_redirect,
    verify_installer,
)


class UpdateController(QObject):
    """每天后台检查一次，并在用户确认后下载和启动安装程序。"""

    def __init__(
        self,
        window: QMainWindow,
        settings: QSettings,
        *,
        current_version: str,
        task_running: Callable[[], bool],
    ) -> None:
        super().__init__(window)
        self.window = window
        self.settings = settings
        self.current_version = current_version
        self.task_running = task_running
        self.network = QNetworkAccessManager(self)
        self.check_reply: QNetworkReply | None = None
        self.download_reply: QNetworkReply | None = None
        self.progress_dialog: QProgressDialog | None = None
        self._manual_check = False
        self._release: ReleaseUpdate | None = None
        self._part_path: Path | None = None
        self._download_stream = None
        self._download_hash = hashlib.sha256()
        self._downloaded_bytes = 0
        self.auto_enabled = _settings_bool(settings, "updates/auto_check", True)

    def schedule_auto_check(self) -> None:
        if not self.auto_enabled or not _is_packaged_windows_app():
            return
        last_check = str(self.settings.value("updates/last_check_date", "") or "")
        if last_check != date.today().isoformat():
            self.check_for_updates(manual=False)

    def set_auto_enabled(self, enabled: bool) -> None:
        self.auto_enabled = bool(enabled)
        self.settings.setValue("updates/auto_check", self.auto_enabled)

    def check_for_updates(self, *, manual: bool = True) -> None:
        if self.check_reply is not None or self.download_reply is not None:
            if manual:
                QMessageBox.information(self.window, "检查更新", "更新任务正在进行中。")
            return
        self._manual_check = manual
        request = _network_request(GITHUB_LATEST_RELEASE_API)
        self.check_reply = self.network.get(request)
        self.check_reply.finished.connect(self._finish_check)

    def shutdown(self) -> None:
        for reply in (self.check_reply, self.download_reply):
            if reply is not None:
                reply.abort()
        self._close_download_stream(remove_partial=True)
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog = None

    def _finish_check(self) -> None:
        reply = self.check_reply
        self.check_reply = None
        if reply is None:
            return
        error = reply.error()
        payload = bytes(reply.readAll())
        error_text = reply.errorString()
        reply.deleteLater()
        if error != QNetworkReply.NetworkError.NoError:
            if self._manual_check:
                QMessageBox.warning(
                    self.window,
                    "检查更新失败",
                    f"暂时无法连接更新服务器：{error_text}",
                )
            return
        try:
            release = parse_github_release(payload, current_version=self.current_version)
        except UpdateMetadataError as exc:
            if self._manual_check:
                QMessageBox.warning(self.window, "检查更新失败", str(exc))
            return

        self.settings.setValue("updates/last_check_date", date.today().isoformat())
        if release is None:
            if self._manual_check:
                QMessageBox.information(
                    self.window,
                    "已经是最新版本",
                    f"当前版本 {self.current_version} 已经是最新版本。",
                )
            return
        self._offer_download(release)

    def _offer_download(self, release: ReleaseUpdate) -> None:
        size_mib = release.size / (1024 * 1024)
        notes = f"\n\n{release.notes[:700]}" if release.notes else ""
        answer = QMessageBox.question(
            self.window,
            "发现新版本",
            f"发现 Tennis Video Helper {release.version}。\n"
            f"安装包约 {size_mib:.1f} MiB，下载后会校验 SHA-256。"
            f"{notes}\n\n是否现在下载？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_download(release)

    def _start_download(self, release: ReleaseUpdate) -> None:
        cache_root = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppLocalDataLocation
            )
        ) / "updates"
        cache_root.mkdir(parents=True, exist_ok=True)
        final_path = cache_root / release.installer_name
        if verify_installer(final_path, release):
            self._offer_install(final_path, release)
            return

        self._release = release
        self._part_path = final_path.with_suffix(final_path.suffix + ".part")
        self._download_hash = hashlib.sha256()
        self._downloaded_bytes = 0
        try:
            self._download_stream = self._part_path.open("wb")
        except OSError as exc:
            self._release = None
            self._part_path = None
            QMessageBox.warning(self.window, "无法下载更新", str(exc))
            return

        self.progress_dialog = QProgressDialog(
            "正在下载并校验更新安装包……",
            "取消",
            0,
            100,
            self.window,
        )
        self.progress_dialog.setWindowTitle("下载更新")
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.canceled.connect(self._cancel_download)
        self.progress_dialog.show()

        self.download_reply = self.network.get(_network_request(release.download_url))
        self.download_reply.readyRead.connect(self._consume_download_data)
        self.download_reply.downloadProgress.connect(self._update_download_progress)
        self.download_reply.finished.connect(self._finish_download)

    def _consume_download_data(self) -> None:
        if self.download_reply is None or self._download_stream is None:
            return
        chunk = bytes(self.download_reply.readAll())
        if not chunk:
            return
        self._download_stream.write(chunk)
        self._download_hash.update(chunk)
        self._downloaded_bytes += len(chunk)

    def _update_download_progress(self, received: int, total: int) -> None:
        if self.progress_dialog is None:
            return
        expected = self._release.size if self._release is not None else total
        denominator = max(1, total if total > 0 else expected)
        percent = max(0, min(100, round(received * 100 / denominator)))
        self.progress_dialog.setValue(percent)

    def _cancel_download(self) -> None:
        if self.download_reply is not None:
            self.download_reply.abort()

    def _finish_download(self) -> None:
        reply = self.download_reply
        self.download_reply = None
        release = self._release
        self._release = None
        if reply is None or release is None:
            self._close_download_stream(remove_partial=True)
            return
        self._consume_reply_tail(reply)
        error = reply.error()
        error_text = reply.errorString()
        final_url = reply.url().toString()
        reply.deleteLater()
        self._close_download_stream(remove_partial=False)
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog = None

        if error == QNetworkReply.NetworkError.OperationCanceledError:
            self._remove_partial()
            return
        if error != QNetworkReply.NetworkError.NoError:
            self._remove_partial()
            QMessageBox.warning(self.window, "下载更新失败", error_text)
            return
        try:
            validate_download_redirect(final_url)
        except UpdateMetadataError as exc:
            self._remove_partial()
            QMessageBox.warning(self.window, "更新校验失败", str(exc))
            return
        if (
            self._downloaded_bytes != release.size
            or self._download_hash.hexdigest().lower() != release.sha256
            or self._part_path is None
        ):
            self._remove_partial()
            QMessageBox.warning(
                self.window,
                "更新校验失败",
                "安装包大小或 SHA-256 与 GitHub Release 不一致，已删除下载文件。",
            )
            return

        final_path = self._part_path.with_suffix("")
        try:
            os.replace(self._part_path, final_path)
        except OSError as exc:
            self._remove_partial()
            QMessageBox.warning(self.window, "保存更新失败", str(exc))
            return
        self._part_path = None
        self._offer_install(final_path, release)

    def _consume_reply_tail(self, reply: QNetworkReply) -> None:
        if self._download_stream is None:
            return
        chunk = bytes(reply.readAll())
        if chunk:
            self._download_stream.write(chunk)
            self._download_hash.update(chunk)
            self._downloaded_bytes += len(chunk)

    def _offer_install(self, path: Path, release: ReleaseUpdate) -> None:
        if not verify_installer(path, release):
            QMessageBox.warning(self.window, "更新校验失败", "缓存安装包校验失败。")
            return
        if self.task_running():
            QMessageBox.information(
                self.window,
                "更新已下载",
                "更新安装包已经下载并校验完成。请等待当前分析结束后，"
                "再次选择“帮助 → 检查更新”进行安装。",
            )
            return
        answer = QMessageBox.question(
            self.window,
            "安装更新",
            f"版本 {release.version} 已下载并通过 SHA-256 校验。\n\n"
            "是否关闭软件并启动安装程序？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        started = QProcess.startDetached(
            str(path), ["/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]
        )
        success = started[0] if isinstance(started, tuple) else bool(started)
        if not success:
            QMessageBox.warning(self.window, "无法启动安装程序", str(path))
            return
        QApplication.quit()

    def _close_download_stream(self, *, remove_partial: bool) -> None:
        if self._download_stream is not None:
            self._download_stream.close()
            self._download_stream = None
        if remove_partial:
            self._remove_partial()

    def _remove_partial(self) -> None:
        if self._part_path is not None:
            try:
                self._part_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._part_path = None


def _network_request(url: str) -> QNetworkRequest:
    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(b"Accept", b"application/vnd.github+json")
    request.setRawHeader(b"User-Agent", b"TennisVideoHelper-Updater")
    request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
    request.setAttribute(
        QNetworkRequest.Attribute.RedirectPolicyAttribute,
        QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
    )
    return request


def _is_packaged_windows_app() -> bool:
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def _settings_bool(settings: QSettings, key: str, default: bool) -> bool:
    value = settings.value(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)
