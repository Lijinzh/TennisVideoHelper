"""Capture deterministic Tennis Video Helper UI screenshots for the website."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from tennis_video_helper.core.models import MediaInfo, RallySegment
from tennis_video_helper.review.session import (
    ReviewClipCandidate,
    ReviewHit,
    ReviewSession,
    ReviewVideoCandidate,
)
import tennis_video_helper.ui.main_window as gui_module
from tennis_video_helper.ui.main_window import MainWindow


OUTPUT_DIR = Path(
    r"C:\Users\admin\Desktop\SomethingElse\zko_page\assets\images\tennis-video-helper"
)


def _court_preview() -> QPixmap:
    pixmap = QPixmap(1280, 720)
    pixmap.fill(QColor("#10171a"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.fillRect(130, 65, 1020, 590, QColor("#356d5a"))
    painter.fillRect(155, 90, 970, 540, QColor("#2c5f50"))
    line = QPen(QColor("#f4f0d7"), 8)
    painter.setPen(line)
    painter.drawRect(190, 110, 900, 500)
    painter.drawLine(640, 110, 640, 610)
    painter.drawLine(190, 360, 1090, 360)
    painter.drawRect(325, 110, 630, 500)
    painter.drawLine(325, 235, 955, 235)
    painter.drawLine(325, 485, 955, 485)
    painter.setPen(QPen(QColor("#07090c"), 12))
    painter.drawLine(190, 360, 1090, 360)
    painter.setBrush(QColor("#b7f34a"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRect(792, 290, 18, 18)
    painter.setBrush(QColor("#ffb067"))
    painter.drawRect(504, 472, 22, 58)
    painter.drawRect(492, 488, 46, 20)
    painter.end()
    return pixmap


def _build_review_session(root: Path) -> ReviewSession:
    source = root / "训练赛_2026-08-11.mp4"
    source.write_bytes(b"source")
    clips_dir = root / "review" / "clips"
    clips_dir.mkdir(parents=True)
    media = MediaInfo(
        path=source,
        duration=186.0,
        width=3840,
        height=2160,
        fps=59.94,
        video_codec="hevc",
        pixel_format="yuv420p10le",
        audio_codec="aac",
        audio_sample_rate=48_000,
        audio_channels=2,
        rotation=0,
        color_transfer="arib-std-b67",
        is_hdr10=False,
        is_dolby_vision=False,
    )
    specs = (
        (1, 18.4, 36.9, 7),
        (2, 72.1, 94.8, 11),
        (3, 132.6, 148.2, 6),
    )
    clips: list[ReviewClipCandidate] = []
    for index, start, end, hit_count in specs:
        path = clips_dir / f"rally_{index:03d}.mp4"
        path.write_bytes(b"preview")
        hits = tuple(
            ReviewHit(
                timestamp=(end - start) * (hit_index + 1) / (hit_count + 1),
                source_timestamp=start
                + (end - start) * (hit_index + 1) / (hit_count + 1),
                confidence=0.82 + min(hit_index, 5) * 0.02,
                reason="声音 + 骨架 + 球拍确认",
            )
            for hit_index in range(hit_count)
        )
        clips.append(
            ReviewClipCandidate(
                id=f"1:{index}",
                index=index,
                path=path,
                segment=RallySegment(
                    start,
                    end,
                    max(0.0, start - 2.0),
                    min(media.duration, end + 3.0),
                    end - start,
                    0.91,
                    hit_count,
                ),
                hits=hits,
            )
        )
    video = ReviewVideoCandidate(
        source=source,
        output_dir=root / "output" / source.stem,
        staging_dir=root / "review",
        media=media,
        clips=tuple(clips),
        audio_events=(),
        visual_events=(),
        fused_events=(),
    )
    return ReviewSession(root / "review", True, (video,))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    court = _court_preview()
    gui_module._video_thumbnail = lambda _path: court

    with tempfile.TemporaryDirectory(prefix="tvh-site-") as temp:
        window = MainWindow()
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.setStyleSheet(
            window.styleSheet()
            .replace(
                '"Segoe UI", "Microsoft YaHei UI"',
                '"Microsoft YaHei UI", "Segoe UI"',
            )
            .replace(
                '"Cascadia Mono", "Consolas"',
                '"Microsoft YaHei UI", "Cascadia Mono", "Consolas"',
            )
        )
        window.resize(1440, 900)
        window.show()
        window._set_review_session(_build_review_session(Path(temp)))
        window.input_edit.setText(r"D:\Tennis\训练赛")
        window.output_edit.setText(r"D:\Tennis\精选输出")
        window.current_video_label.setText("训练赛_2026-08-11.mp4")
        window.status_badge.setText("■  分析完成")
        window.acceleration_label.setText(
            "GPU 加速：ONNX GPU + NVDEC + NVENC 已启用"
        )
        window.acceleration_label.setProperty("mode", "active")
        window.percent_label.setText("100%")
        window.phase_label.setText("已找到 3 段候选 · 等待勾选导出")
        window.progress.setValue(1000)
        window.elapsed_label.setText("00:00:14")
        window.eta_label.setText("已完成")
        window.task_summary_label.setText(
            "3 段候选 / 24 个确认击球点；源视频保持只读。"
        )
        app.processEvents()
        window.task_summary_label.setText(
            "3 段候选 / 24 个确认击球点；源视频保持只读。"
        )
        window.grab().save(str(OUTPUT_DIR / "app-review.webp"), "WEBP", 90)

        window._show_parameter_panel()
        app.processEvents()
        window.grab().save(str(OUTPUT_DIR / "app-settings.webp"), "WEBP", 90)
        os._exit(0)


if __name__ == "__main__":
    main()
