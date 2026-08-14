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
        "documentation/index.html",
        "documentation/getting-started.html",
        "documentation/using.html",
        "documentation/features.html",
        "documentation/guides.html",
        "documentation/developer-guide.html",
        "documentation/reference.html",
        "documentation/docs.css",
        "documentation/docs.js",
        "documentation/docs-content.js",
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


def test_homepage_supports_system_light_dark_and_court_page_themes() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    css = (SITE / "tennis-video-helper.css").read_text(encoding="utf-8")
    script = (SITE / "tennis-video-helper.js").read_text(encoding="utf-8")
    assert 'name="color-scheme" content="light dark"' in html
    assert "data-theme-open" in html
    assert "data-theme-panel" in html
    assert 'data-color-mode="system"' in html
    assert 'data-color-mode="light"' in html
    assert 'data-color-mode="dark"' in html
    assert "data-theme-palette-select" in html
    assert 'value="follow"' in html
    assert 'value="shanghai"' in html
    assert 'value="hyrule"' in html
    assert 'value="ashina"' in html
    assert 'html[data-resolved-theme="light"]' in css
    assert 'html[data-resolved-theme="dark"]' in css
    assert 'html[data-site-palette="shanghai"]' in css
    assert 'html[data-site-palette="dunhuang"]' in css
    assert 'html[data-site-palette="hyrule"]' in css
    assert 'html[data-site-palette="ashina"]' in css
    assert "prefers-color-scheme: dark" in html
    assert "tvh-color-mode" in script
    assert "tvh-palette-choice" in script
    assert "tvh-active-court" in script
    assert "systemTheme.addEventListener" in script
    assert "paletteChoice === 'follow'" in script
    assert "球场背景主题" in html
    assert "data-theme-preview" in html
    assert "themeAssets" in script
    assert "shanbei-loess-court.webp" in script
    assert '--theme-scene: url("assets/images/tennis-video-helper/shanbei-loess-court.webp")' in css
    assert 'var(--theme-scene) center top / cover fixed' in css
    assert ".tennis-theme-preview" in css
    assert css.count("--theme-scene: url(") == 16
    assert 'tennis-video-helper.css?v=20260812-v9' in html
    assert 'tennis-video-helper.js?v=20260814-v11' in html
    for asset in (
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
    ):
        assert asset in script
        assert asset in css


def test_homepage_explains_project_architecture_for_contributors() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    css = (SITE / "tennis-video-helper.css").read_text(encoding="utf-8")
    script = (SITE / "tennis-video-helper.js").read_text(encoding="utf-8")
    assert 'id="architecture"' in html
    assert "项目是怎样工作的？" in html
    assert html.count("data-architecture-node=") == 5
    assert "声音候选" in html
    assert "骨架与球拍确认" in html
    assert "音画融合与回合状态机" in html
    assert "候选片段与人工复核" in html
    assert "验证后安全发布" in html
    assert "uv sync --extra dev" in html
    assert "uv run pytest -q" in html
    assert "Pull Request" in html
    assert "src/tennis_video_helper/detection/audio.py" in html
    assert ".tennis-architecture-map" in css
    assert "architectureContent" in script
    assert "updateArchitectureDetail" in script


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
    assert "feedbackFallback?.click()" in script
    assert "feedbackForm.checkValidity()" in script
    assert "请先填写一句话标题" in script
    assert "maxPrefilledUrlLength: 7000" in script
    assert "prepared.shortIssueUrl" in script
    assert "反馈内容较长" in script
    assert "data-feedback-fallback" in html
    assert 'option value="Windows 11 x64"' in html
    assert 'option value="Windows 10 x64"' in html
    assert 'name="gpu"' in html
    assert 'name="videoSpec"' in html
    assert "`- 显卡：${gpu}`" in script
    assert "navigator.clipboard.writeText(prepared.body)" in script
    assert ".tennis-feedback-dialog::backdrop" in css
    assert ".tennis-button--primary { color: #10151a" in css
    assert ".tennis-button { display: inline-flex" in css
    assert "color: #fff8e8; background: #10151a" in css
    assert ".tennis-button:hover { color: #10151a" in css
    assert ".tennis-button--light { color: #10151a" in css


def test_public_download_copy_is_current() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    script = (SITE / "tennis-video-helper.js").read_text(encoding="utf-8")
    github_asset = "https://github.com/Lijinzh/TennisVideoHelper/releases/download/v0.1.4/TennisVideoHelper-Setup-0.1.4.exe"
    assert "最新版安装包从公开 GitHub Release 下载" in html
    assert github_asset in html
    assert github_asset in script
    assert "tennis-video-helper.js?v=20260814-v11" in html
    assert "https://github.com/Lijinzh/TennisVideoHelper/releases/tag/v0.1.4" in html
    assert "当前安装包位于私有 GitHub Release" not in html


def test_homepage_supports_persistent_english_language_switching() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    script = (SITE / "tennis-video-helper-i18n.js").read_text(encoding="utf-8")
    css = (SITE / "tennis-video-helper.css").read_text(encoding="utf-8")
    assert "data-language-toggle" in html
    assert "tennis-video-helper-i18n.js?v=20260814-v3" in html
    assert "tvh-language" in html
    assert "tvh-language" in script
    assert "Automatic Rally Selection" in script
    assert "Download for Windows" in script
    assert "Choose Your Pixel Court" in script
    assert "How Does the Project Work?" in script
    assert "Prepare and Continue to GitHub" in script
    assert "MutationObserver" in script
    assert "document.documentElement.lang" in script
    assert ".tennis-language-trigger" in css


def test_documentation_hub_has_six_complete_sections_and_homepage_entry() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    content = (SITE / "documentation" / "docs-content.js").read_text(encoding="utf-8")
    assert 'href="documentation/">文档</a>' in html
    assert 'href="documentation/">完整文档</a>' in html
    for page_id, filename, title in (
        ("getting-started", "getting-started.html", "Getting Started"),
        ("using", "using.html", "Using"),
        ("features", "features.html", "Features"),
        ("guides", "guides.html", "Guides and Tutorials"),
        ("developer-guide", "developer-guide.html", "Developer Guide"),
        ("reference", "reference.html", "Reference"),
    ):
        page = (SITE / "documentation" / filename).read_text(encoding="utf-8")
        assert f'data-doc-page="{page_id}"' in page
        assert title in page
        assert f"{filename}" in content
    assert "六大板块" in content
    assert "Six documentation areas" in content
    assert "源视频始终只读" in content
    assert "Source videos remain read-only" in content


def test_documentation_hub_supports_navigation_search_copy_and_responsive_menu() -> None:
    script = (SITE / "documentation" / "docs.js").read_text(encoding="utf-8")
    css = (SITE / "documentation" / "docs.css").read_text(encoding="utf-8")
    assert "data-doc-search-open" in script
    assert "Ctrl K" in script
    assert "searchable" in script
    assert "navigator.clipboard.writeText" in script
    assert "data-doc-language" in script
    assert "tvh-language" in script
    assert "data-doc-menu" in script
    assert "IntersectionObserver" in script
    assert "docs-pagination" in script
    assert "@media (max-width: 860px)" in css
    assert ".docs-sidebar.is-open" in css
    assert ".docs-search-dialog::backdrop" in css
    assert ".docs-table-wrap { overflow-x: auto" in css
    assert "prefers-reduced-motion" in css


def test_documentation_reference_matches_current_release_and_cli_contract() -> None:
    content = (SITE / "documentation" / "docs-content.js").read_text(encoding="utf-8")
    assert "TennisVideoHelper-Setup-0.1.4.exe" in content
    assert "231,136,955" in content
    assert "AC02F957D9768C9849EFC85DF88D7CF3E331441A91AE0A8CE760FF9CCC16B40F" in content
    assert "--min-rally-duration" in content
    assert "--min-confirmed-hits" in content
    assert "--overwrite-existing / --keep-existing" in content
    assert "--original-quality / --1080p-output" in content
    assert "optimization-profile.json" in content
    assert "segments.csv" in content
    assert "analysis.json" in content
    assert "review-selection.json" in content


def test_contributing_redirects_to_the_full_developer_guide() -> None:
    html = (SITE / "contributing.html").read_text(encoding="utf-8")
    assert 'url=documentation/developer-guide.html' in html
    assert 'href="documentation/developer-guide.html"' in html
    assert "CONTRIBUTING.md" in html


def test_github_user_feedback_issue_form_exists() -> None:
    template = ROOT / ".github" / "ISSUE_TEMPLATE" / "user-feedback.yml"
    config = ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
    assert template.is_file()
    assert config.is_file()
    template_text = template.read_text(encoding="utf-8")
    assert "name: 用户意见反馈" in template_text
    assert 'labels: ["user feedback"]' in template_text
    assert "- type: dropdown\n    id: environment" in template_text
    assert "Windows 11 x64" in template_text
    assert "id: gpu" in template_text


def test_footer_clearly_credits_golden_philosophy() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    css = (SITE / "tennis-video-helper.css").read_text(encoding="utf-8")
    assert "Made by Golden Philosophy" in html
    assert "© 2026 Golden Philosophy. All rights reserved." in html
    assert ".tennis-footer__credits" in css
