from __future__ import annotations

from tennis_video_helper.resources import asset_path
from tennis_video_helper.ui.main_window import COURT_BACKGROUND_THEMES


EXPECTED_COURT_ASSETS = {
    "shanbei-loess-court.webp",
    "roland-garros-clay-court.webp",
    "wimbledon-grass-court.webp",
    "us-open-night-court.webp",
    "australian-open-day-court.webp",
    "shanghai-qizhong-court.webp",
    "beijing-national-tennis-center.webp",
    "madrid-caja-magica-court.webp",
    "rio-jockey-club-court.webp",
    "indian-wells-desert-court.webp",
    "dunhuang-desert-court.webp",
    "himalaya-foothills-court.webp",
    "larung-gar-valley-court.webp",
    "hyrule-inspired-court.webp",
    "ashina-inspired-court.webp",
}


def test_all_fifteen_website_courts_are_available_in_the_app() -> None:
    court_themes = [theme for theme in COURT_BACKGROUND_THEMES if theme.asset_name]

    assert len(court_themes) == 15
    assert {theme.asset_name for theme in court_themes} == EXPECTED_COURT_ASSETS
    assert len({theme.id for theme in COURT_BACKGROUND_THEMES}) == len(
        COURT_BACKGROUND_THEMES
    )

    for theme in court_themes:
        background = asset_path("backgrounds", theme.asset_name)
        assert background is not None
        assert background.is_file()
