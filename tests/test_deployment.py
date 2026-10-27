"""The two hosting options stay consistent and locked down."""

import re

from conftest import ROOT


def _build_module():
    """Import tools/build_offline.py, which isn't a package module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_offline", ROOT / "tools" / "build_offline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nginx_sends_the_same_policy_as_the_page():
    """The nginx image's security header and the page's own policy must stay identical."""
    build = _build_module()
    nginx = (ROOT / "deploy" / "browser" / "nginx.conf").read_text()
    sent = re.search(r'add_header Content-Security-Policy "([^"]+)"', nginx).group(1)
    assert sent == build.CSP + "; frame-ancestors 'none'"


def test_policy_allows_no_outside_address():
    """The policy names no outside address, and connections go to the app's own server only."""
    build = _build_module()
    assert "http" not in build.CSP.replace("'self'", "")
    assert "connect-src 'self' blob: data:;" in build.CSP


def test_offline_build_ships_every_app_module():
    """A new Python module must be added to the offline build, or the browser version breaks."""
    build = _build_module()
    modules = {p.name for p in ROOT.glob("*.py")}
    assert modules <= set(build.APP_FILES)


def test_server_image_installs_only_fingerprinted_packages():
    """
    The server image installs pinned, fingerprint-checked packages, runs unprivileged, and both images
    pin their base by digest.
    """
    dockerfile = (ROOT / "deploy" / "server" / "Dockerfile").read_text()
    assert "pip install --require-hashes -r requirements-lock.txt" in dockerfile
    assert "USER 10001" in dockerfile
    for image in re.findall(r"ARG \w+_IMAGE=(\S+)", dockerfile + (ROOT / "deploy" / "browser" / "Dockerfile").read_text()):
        assert "@sha256:" in image, image


def test_server_compose_keeps_the_app_off_the_network():
    """
    In the compose setup the app has no published port, sits on an internal network, and trusts the
    sign-in header.
    """
    compose = (ROOT / "deploy" / "server" / "docker-compose.yml").read_text()
    app = compose.split("  signin:")[0]
    assert "ports:" not in app and "internal: true" in compose
    assert 'BSA_USER_HEADER: "X-Forwarded-Email"' in app
