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
        "assets/images/tennis-video-helper/shanbei-loess-court.webp",
        "assets/images/tennis-video-helper/roland-garros-clay-court.webp",
        "assets/images/tennis-video-helper/wimbledon-grass-court.webp",
        "assets/images/tennis-video-helper/us-open-night-court.webp",
        "assets/images/tennis-video-helper/australian-open-day-court.webp",
        "assets/images/tennis-video-helper/shanghai-qizhong-court.webp",
        "assets/images/tennis-video-helper/beijing-national-tennis-center.webp",
        "assets/images/tennis-video-helper/madrid-caja-magica-court.webp",
        "assets/images/tennis-video-helper/rio-jockey-club-court.webp",
        "assets/images/tennis-video-helper/indian-wells-desert-court.webp",
        "assets/images/tennis-video-helper/dunhuang-desert-court.webp",
        "assets/images/tennis-video-helper/himalaya-foothills-court.webp",
        "assets/images/tennis-video-helper/larung-gar-valley-court.webp",
        "assets/images/tennis-video-helper/hyrule-inspired-court.webp",
        "assets/images/tennis-video-helper/ashina-inspired-court.webp",
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


def test_homepage_includes_scrollable_pixel_court_gallery() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    css = (SITE / "tennis-video-helper.css").read_text(encoding="utf-8")
    script = (SITE / "tennis-video-helper.js").read_text(encoding="utf-8")
    assert 'id="courts"' in html
    assert "陕北风黄土球场" in html
    assert "法网·罗兰加洛斯红土" in html
    assert "温布尔登草地球场" in html
    assert "美网纽约夜场硬地" in html
    assert "澳网墨尔本蓝色硬地" in html
    assert "上海大师赛·旗忠网球中心" in html
    assert "北京国家网球中心·钻石球场" in html
    assert "马德里·魔力盒红土" in html
    assert "里约·赛马会红土" in html
    assert "敦煌·鸣沙月泉概念场" in html
    assert "喜马拉雅山脚概念场" in html
    assert "喇荣山谷概念球场" in html
    assert "《塞尔达传说》灵感·海拉鲁式旷野" in html
    assert "《只狼》灵感·苇名式山城" in html
    assert html.count("data-court-slide") == 15
    assert html.count("data-court-tab=") == 15
    assert html.count("真实名场") >= 9
    assert html.count("概念创作") >= 5
    assert "不把球场误写进鸟巢内部" in html
    assert ".tennis-court-section" in css
    assert "scroll-snap-type: x mandatory" in css
    assert "image-rendering: pixelated" in css
    assert "setActiveCourt" in script
    assert "data-court-next" in script


def test_feedback_window_builds_a_safe_prefilled_github_issue() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    script = (SITE / "tennis-video-helper.js").read_text(encoding="utf-8")
    css = (SITE / "tennis-video-helper.css").read_text(encoding="utf-8")
    assert 'id="feedback"' in html
    assert "data-feedback-dialog" in html
    assert "data-feedback-form" in html
    assert "Issue 创建后会公开显示" in html
    assert "https://github.com/Lijinzh/TennisVideoHelper/issues/new" in script
    assert "issueUrl.searchParams.set('title'" in script
    assert "issueUrl.searchParams.set('body'" in script
    assert "window.location.assign(prepared.issueUrl)" in script
    assert "navigator.clipboard.writeText(prepared.body)" in script
    assert ".tennis-feedback-dialog::backdrop" in css


def test_public_download_copy_is_current() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "安装包由公开 GitHub Release 提供" in html
    assert "当前安装包位于私有 GitHub Release" not in html


def test_github_user_feedback_issue_form_exists() -> None:
    template = ROOT / ".github" / "ISSUE_TEMPLATE" / "user-feedback.yml"
    config = ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
    assert template.is_file()
    assert config.is_file()
    template_text = template.read_text(encoding="utf-8")
    assert "name: 用户意见反馈" in template_text
    assert 'labels: ["user feedback"]' in template_text


def test_footer_clearly_credits_golden_philosophy() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    css = (SITE / "tennis-video-helper.css").read_text(encoding="utf-8")
    assert "Made by Golden Philosophy" in html
    assert "© 2026 Golden Philosophy. All rights reserved." in html
    assert ".tennis-footer__credits" in css
