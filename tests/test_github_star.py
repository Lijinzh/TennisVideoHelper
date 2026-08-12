from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs"


def test_homepage_has_a_transparent_github_star_entry() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    script = (SITE / "github-star.js").read_text(encoding="utf-8")
    css = (SITE / "github-star.css").read_text(encoding="utf-8")

    assert (SITE / "github-star.css").is_file()
    assert (SITE / "github-star.js").is_file()
    assert 'href="github-star.css?v=20260812-v1"' in html
    assert 'src="github-star.js?v=20260812-v1"' in html
    assert "https://github.com/Lijinzh/TennisVideoHelper" in script
    assert "https://api.github.com/repos/Lijinzh/TennisVideoHelper" in script
    assert "前往 GitHub 确认 Star" in script
    assert "不会索取或保存你的 GitHub Token" in script
    assert "stargazers_count" in script
    assert "publishedStarSnapshot = 0" in script
    assert "网站发布时的数量快照" in script
    assert "data-pixel-reveal" not in script
    assert "ghbtns.com" not in html + script
    assert "access_token" not in script
    assert ".tennis-star-section" in css
