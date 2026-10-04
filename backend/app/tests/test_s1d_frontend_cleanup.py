"""S1d: the frontend must not hardcode the backend address or call removed endpoints."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "frontend" / "src" / "App.tsx"


def _app_text() -> str:
    return APP.read_text(encoding="utf-8")


def test_no_hardcoded_ip_urls_in_app():
    assert not re.search(r"https?://\d+\.\d+\.\d+\.\d+", _app_text())


def test_only_one_http_literal_the_localhost_default():
    literals = [u for u in re.findall(r"https?://[^\s'\"`)]+", _app_text())
                if "w3.org" not in u]  # SVG xmlns is not an API address
    assert literals == ["http://localhost:8000"]


def test_every_fetch_goes_through_api_base():
    text = _app_text()
    for m in re.finditer(r"fetch\(\s*([^\n]*)", text):
        first = m.group(1)
        if first.strip() == "":
            continue  # URL is on the next line
        assert first.lstrip().startswith("`${API_BASE}"), first
    # multi-line fetches: the line after "fetch(" must start with the template
    for m in re.finditer(r"fetch\(\s*\n\s*([^\n]*)", text):
        assert m.group(1).lstrip().startswith("`${API_BASE}"), m.group(1)


def test_api_base_reads_vite_env():
    assert "import.meta.env.VITE_API_BASE" in _app_text()


def test_removed_endpoints_not_called_from_frontend():
    text = _app_text()
    for gone in ("transfer-ownership", "/owner", "mint-token", "/tokens/",
                 "stake-balance", "slash-stake", "/stake`"):
        assert gone not in text, gone


def test_removed_panels_and_state_are_gone():
    text = _app_text().lower()
    for gone in ("dataset token", "trust stake", "slash", "mint", "transfer"):
        assert gone not in text, gone


def test_env_example_exists_and_sets_api_base():
    env = (ROOT / "frontend" / ".env.example").read_text()
    assert re.search(r"^VITE_API_BASE=http", env, re.M)


def test_start_demo_no_longer_edits_source_with_sed():
    script = (ROOT / "start_demo.sh").read_text()
    assert "sed -i" not in script
    assert "src/App.tsx" not in script
    assert "VITE_API_BASE" in script
