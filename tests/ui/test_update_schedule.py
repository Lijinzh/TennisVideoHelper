from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QApplication, QMainWindow

from tennis_video_helper.ui.update_controller import (
    UpdateController,
    milliseconds_until_daily_check,
)


class MemorySettings:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = dict(values or {})
        self.sync_count = 0

    def value(self, key: str, default=None):
        return self.values.get(key, default)

    def setValue(self, key: str, value) -> None:  # noqa: N802 - Qt API
        self.values[key] = value

    def sync(self) -> None:
        self.sync_count += 1


def _controller(
    settings: MemorySettings,
    now: datetime,
) -> tuple[QApplication, UpdateController, QMainWindow]:
    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    controller = UpdateController(
        window,
        settings,  # type: ignore[arg-type]
        current_version="0.1.1",
        task_running=lambda: False,
        now_provider=lambda: now,
        packaged_app=lambda: True,
    )
    return app, controller, window


def test_daily_check_delay_targets_local_10_am() -> None:
    assert milliseconds_until_daily_check(
        datetime(2026, 8, 12, 9, 30)
    ) == 30 * 60 * 1000
    assert milliseconds_until_daily_check(
        datetime(2026, 8, 12, 10, 0)
    ) == 24 * 60 * 60 * 1000
    assert milliseconds_until_daily_check(
        datetime(2026, 8, 12, 9, 30), checked_today=True
    ) == (24 * 60 + 30) * 60 * 1000


def test_first_packaged_launch_checks_immediately(monkeypatch) -> None:
    _app, controller, window = _controller(
        MemorySettings(), datetime(2026, 8, 12, 8)
    )
    calls: list[bool] = []
    monkeypatch.setattr(
        controller,
        "check_for_updates",
        lambda *, manual=True: calls.append(manual) or True,
    )

    controller.schedule_auto_check()

    assert calls == [False]
    controller.shutdown()
    window.close()


def test_before_daily_time_waits_until_10_am(monkeypatch) -> None:
    settings = MemorySettings({"updates/last_check_date": "2026-08-11"})
    _app, controller, window = _controller(
        settings, datetime(2026, 8, 12, 9, 30)
    )
    calls: list[bool] = []
    monkeypatch.setattr(
        controller,
        "check_for_updates",
        lambda *, manual=True: calls.append(manual) or True,
    )

    controller.schedule_auto_check()

    assert calls == []
    assert controller.daily_check_timer.isActive() is True
    assert 29 * 60 * 1000 <= controller.daily_check_timer.remainingTime() <= 30 * 60 * 1000
    controller.shutdown()
    window.close()


def test_successful_check_today_waits_until_tomorrow(monkeypatch) -> None:
    settings = MemorySettings({"updates/last_check_date": "2026-08-12"})
    _app, controller, window = _controller(
        settings, datetime(2026, 8, 12, 9, 30)
    )
    calls: list[bool] = []
    monkeypatch.setattr(
        controller,
        "check_for_updates",
        lambda *, manual=True: calls.append(manual) or True,
    )

    controller.schedule_auto_check()

    assert calls == []
    assert controller.daily_check_timer.isActive() is True
    expected_delay = (24 * 60 + 30) * 60 * 1000
    assert (
        expected_delay - 1_000
        <= controller.daily_check_timer.remainingTime()
        <= expected_delay
    )
    controller.shutdown()
    window.close()


def test_after_daily_time_catches_up_and_toggle_persists(monkeypatch) -> None:
    settings = MemorySettings({"updates/last_check_date": "2026-08-11"})
    _app, controller, window = _controller(
        settings, datetime(2026, 8, 12, 15, 20)
    )
    calls: list[bool] = []
    monkeypatch.setattr(
        controller,
        "check_for_updates",
        lambda *, manual=True: calls.append(manual) or True,
    )

    controller.schedule_auto_check()
    assert calls == [False]

    controller.set_auto_enabled(False)
    assert settings.values["updates/auto_check"] is False
    assert settings.sync_count == 1
    assert controller.daily_check_timer.isActive() is False

    controller.shutdown()
    window.close()
