"""Qt 异步自动更新控制器。"""

from __future__ import annotations

from datetime import datetime, time, timedelta
import hashlib
import os
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import (
    QObject,
    QProcess,
    QSettings,
    QStandardPaths,
    QTimer,
    QUrl,
)
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
from tennis_video_helper.ui.i18n import translate_text


class QMessageBox(QMessageBox):
    @staticmethod
    def _args(args: tuple) -> tuple:
        return tuple(translate_text(value) if isinstance(value, str) else value for value in args)

    @staticmethod
    def information(*args, **kwargs):
        from PySide6.QtWidgets import QMessageBox as QtMessageBox
        return QtMessageBox.information(*QMessageBox._args(args), **kwargs)

    @staticmethod
    def warning(*args, **kwargs):
        from PySide6.QtWidgets import QMessageBox as QtMessageBox
        return QtMessageBox.warning(*QMessageBox._args(args), **kwargs)

    @staticmethod
    def question(*args, **kwargs):
        from PySide6.QtWidgets import QMessageBox as QtMessageBox
        return QtMessageBox.question(*QMessageBox._args(args), **kwargs)


class QProgressDialog(QProgressDialog):
    def __init__(self, *args, **kwargs) -> None:
        translated = tuple(
            translate_text(value) if isinstance(value, str) else value for value in args
        )
        super().__init__(*translated, **kwargs)


DAILY_AUTO_CHECK_TIME = time(hour=10, minute=0)
_MAX_QT_TIMER_INTERVAL_MS = 2_147_000_000


class UpdateController(QObject):
    """首次启动立即检查，之后每天固定时间检查并安装可信更新。"""

    def __init__(
        self,
        window: QMainWindow,
        settings: QSettings,
        *,
        current_version: str,
        task_running: Callable[[], bool],
        now_provider: Callable[[], datetime] = datetime.now,
        packaged_app: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.settings = settings
        self.current_version = current_version
        self.task_running = task_running
        self._now = now_provider
        self._packaged_app = packaged_app or _is_packaged_windows_app
        self.network = QNetworkAccessManager(self)
        self.daily_check_timer = QTimer(self)
        self.daily_check_timer.setSingleShot(True)
        self.daily_check_timer.timeout.connect(self._daily_check_due)
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
        """安排首次检查或下一次本机时间 10:00 的每日检查。"""

        self.daily_check_timer.stop()
        if not self._automatic_checks_available():
            return
        now = self._now()
        last_check = str(self.settings.value("updates/last_check_date", "") or "")
        today = now.date().isoformat()

        # 从未成功检查过代表首次启动，不能等到固定时刻才检查。
        if not last_check:
            if not self.check_for_updates(manual=False):
                self._arm_next_daily_check(now)
            return

        # 软件在 10:00 之后才启动时，补做当天尚未完成的检查。
        if last_check != today and _is_at_or_after_daily_check(now):
            if not self.check_for_updates(manual=False):
                self._arm_next_daily_check(now)
            return

        self._arm_next_daily_check(now)

    def set_auto_enabled(self, enabled: bool) -> None:
        self.auto_enabled = bool(enabled)
        self.settings.setValue("updates/auto_check", self.auto_enabled)
        self.settings.sync()
        if self.auto_enabled:
            self.schedule_auto_check()
        else:
            self.daily_check_timer.stop()

    def check_for_updates(self, *, manual: bool = True) -> bool:
        if self.check_reply is not None or self.download_reply is not None:
            if manual:
                QMessageBox.information(self.window, "检查更新", "更新任务正在进行中。")
            return False
        self._manual_check = manual
        request = _network_request(GITHUB_LATEST_RELEASE_API)
        self.check_reply = self.network.get(request)
        self.check_reply.finished.connect(self._finish_check)
        return True

    def shutdown(self) -> None:
        self.daily_check_timer.stop()
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
            self._arm_next_daily_check()
            return
        try:
            release = parse_github_release(payload, current_version=self.current_version)
        except UpdateMetadataError as exc:
            if self._manual_check:
                QMessageBox.warning(self.window, "检查更新失败", str(exc))
            self._arm_next_daily_check()
            return

        self.settings.setValue(
            "updates/last_check_date", self._now().date().isoformat()
        )
        self.settings.sync()
        if release is None:
            if self._manual_check:
                QMessageBox.information(
                    self.window,
                    "已经是最新版本",
                    f"当前版本 {self.current_version} 已经是最新版本。",
                )
            self._arm_next_daily_check()
            return
        self._offer_download(release)
        self._arm_next_daily_check()

    def _daily_check_due(self) -> None:
        if not self._automatic_checks_available():
            return
        if not self.check_for_updates(manual=False):
            self._arm_next_daily_check()

    def _automatic_checks_available(self) -> bool:
        return self.auto_enabled and self._packaged_app()

    def _arm_next_daily_check(self, now: datetime | None = None) -> None:
        self.daily_check_timer.stop()
        if not self._automatic_checks_available():
            return
        current_time = now or self._now()
        last_check = str(
            self.settings.value("updates/last_check_date", "") or ""
        )
        delay_ms = milliseconds_until_daily_check(
            current_time,
            checked_today=last_check == current_time.date().isoformat(),
        )
        self.daily_check_timer.start(delay_ms)

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


def milliseconds_until_daily_check(
    now: datetime,
    *,
    checked_today: bool = False,
) -> int:
    """返回从当前本机时间到下一次每日检查的毫秒数。"""

    target = datetime.combine(now.date(), DAILY_AUTO_CHECK_TIME)
    if checked_today or target <= now:
        target += timedelta(days=1)
    delay_ms = max(1, round((target - now).total_seconds() * 1000))
    return min(delay_ms, _MAX_QT_TIMER_INTERVAL_MS)


def _is_at_or_after_daily_check(now: datetime) -> bool:
    return now.time() >= DAILY_AUTO_CHECK_TIME


def _settings_bool(settings: QSettings, key: str, default: bool) -> bool:
    value = settings.value(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)
