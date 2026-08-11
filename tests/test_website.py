from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs"


def test_personal_github_pages_site_has_required_assets() -> None:
    required = [
        "index.html",
        "pixel-preview.css",
        "pixel-preview.js",
        "tennis-video-helper.css",
        "tennis-video-helper.js",
        "assets/images/tennis-video-helper/app-icon.png",
        "assets/images/tennis-video-helper/app-review.webp",
        "assets/images/tennis-video-helper/app-settings.webp",
    ]
    for relative_path in required:
        assert (SITE / relative_path).is_file(), relative_path


def test_site_belongs_to_lijinzh_not_zkolab() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "https://lijinzh.github.io/TennisVideoHelper/" in html
    assert "https://github.com/Lijinzh/TennisVideoHelper" in html
    assert "ZKO HOME" not in html
    assert "返回字库主页" not in html


def test_homepage_uses_larger_readable_type() -> None:
    css = (SITE / "tennis-video-helper.css").read_text(encoding="utf-8")
    assert "font-size: clamp(60px, 5.6vw, 84px)" in css
    assert "font-size: 18px" in css
    assert "font: 900 15px/1.2 var(--ui-sans)" in css
