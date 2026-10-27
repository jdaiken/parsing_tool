"""The two hosting options stay consistent and locked down."""

import re

from conftest import ROOT


def _build_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_offline", ROOT / "tools" / "build_offline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nginx_sends_the_same_policy_as_the_page():
    build = _build_module()
    nginx = (ROOT / "deploy" / "browser" / "nginx.conf").read_text()
    sent = re.search(r'add_header Content-Security-Policy "([^"]+)"', nginx).group(1)
    assert sent == build.CSP + "; frame-ancestors 'none'"


def test_policy_allows_no_outside_address():
    build = _build_module()
    assert "http" not in build.CSP.replace("'self'", "")
    assert "connect-src 'self' blob: data:;" in build.CSP


def test_offline_build_ships_every_app_module():
    build = _build_module()
    modules = {p.name for p in ROOT.glob("*.py")}
    assert modules <= set(build.APP_FILES)


def test_server_image_installs_only_fingerprinted_packages():
    dockerfile = (ROOT / "deploy" / "server" / "Dockerfile").read_text()
    assert "pip install --require-hashes -r requirements-lock.txt" in dockerfile
    assert "USER 10001" in dockerfile
    for image in re.findall(r"ARG \w+_IMAGE=(\S+)", dockerfile + (ROOT / "deploy" / "browser" / "Dockerfile").read_text()):
        assert "@sha256:" in image, image


def test_server_compose_keeps_the_app_off_the_network():
    compose = (ROOT / "deploy" / "server" / "docker-compose.yml").read_text()
    app = compose.split("  signin:")[0]
    assert "ports:" not in app and "internal: true" in compose
    assert 'BSA_USER_HEADER: "X-Forwarded-Email"' in app
