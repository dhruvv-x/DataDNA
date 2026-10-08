"""S7: rules the frontend source must keep following (it is split into many files now, so every file is checked)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "frontend" / "src"
CLIENT = SRC / "api" / "client.ts"


def _files(include_tests: bool = False):
    out = []
    for path in SRC.rglob("*"):
        if path.suffix not in (".ts", ".tsx"):
            continue
        if not include_tests and (".test." in path.name or "test" in path.parts):
            continue
        out.append(path)
    return out


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_frontend_is_split_and_old_app_is_gone():
    assert len(_files()) >= 20
    assert len(_text(SRC / "App.tsx").splitlines()) < 60  # only the routes, not the 1331-line monolith


def test_no_hardcoded_ip_or_http_addresses_in_source():
    for path in _files():
        text = _text(path)
        assert not re.search(r"https?://\d+\.\d+\.\d+\.\d+", text), path
        literals = [u for u in re.findall(r"https?://[^\s'\"`)]+", text) if "w3.org" not in u]
        assert literals == [], (path, literals)


def test_only_the_api_client_calls_fetch():
    for path in _files():
        if path == CLIENT:
            continue
        assert not re.search(r"\bfetch\(", _text(path)), f"{path.name} must go through api/client.ts"


def test_every_fetch_in_the_client_goes_through_api_base():
    text = _text(CLIENT)
    calls = re.findall(r"fetch\(\s*([^\n]*)", text)
    assert len(calls) >= 2
    for first in calls:
        assert first.lstrip().startswith("`${API_BASE}"), first


def test_api_base_reads_vite_env_and_defaults_to_the_proxy():
    text = _text(CLIENT)
    assert "import.meta.env.VITE_API_BASE" in text
    assert "|| '/api'" in text


def test_access_token_is_never_stored_in_the_browser():
    for path in _files():
        text = _text(path)
        assert not re.search(r"\b(local|session)Storage\s*[.\[]", text), path  # comments may mention them


def test_removed_endpoints_and_ideas_not_in_frontend():
    for path in _files():
        text = _text(path).lower()
        for gone in ("/datasets", "/models", "/training-runs", "transfer-ownership", "mint-token", "stake-balance",
                     "slash-stake", "dataset token", "trust stake"):
            assert gone not in text, (path, gone)


def test_only_one_refresh_call_site_and_it_is_shared():
    text = _text(CLIENT)
    assert text.count("`${API_BASE}/auth/refresh`") == 1
    assert "refreshPromise" in text


def test_env_example_uses_the_proxy_and_cookie_path_is_documented():
    env = (ROOT / "frontend" / ".env.example").read_text()
    assert re.search(r"^VITE_API_BASE=/api$", env, re.M)
    root_env = (ROOT / ".env.example").read_text()
    assert re.search(r"^COOKIE_PATH=/api/auth$", root_env, re.M)


def test_start_demo_uses_the_proxy_and_no_source_edits():
    script = (ROOT / "start_demo.sh").read_text()
    assert "sed -i" not in script
    assert "src/App.tsx" not in script
    assert "VITE_API_BASE=/api" in script
    assert "ip addr" not in script  # no more WSL IP in the frontend config


def test_vite_proxy_strips_the_api_prefix():
    cfg = (ROOT / "frontend" / "vite.config.ts").read_text()
    assert "'/api'" in cfg and "replace(/^\\/api/, '')" in cfg
