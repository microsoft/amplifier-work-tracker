"""Tier 1 -- pure-function tests for `webapp.resolve_web_config`'s TLS
resolution (`webapp._resolve_tls`).

No bd, no dolt, no network -- `resolve_web_config` is pure aside from
touching the filesystem to check whether cert/key paths exist, and to
load/create the password file and signing secret via `webauth`, both of
which write under a `$HOME` this file always monkeypatches to an isolated
`tmp_path`. See `tests/integration/test_web.py` for the full end-to-end
dashboard tests (those exercise TLS only indirectly, via a real request).
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")
pytest.importorskip("cryptography", reason="the 'web' extra is not installed")

from amplifier_work_tracker import webapp  # noqa: E402
from amplifier_work_tracker import webauth as WA  # noqa: E402
from amplifier_work_tracker import webtls as WT  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    """Every webauth/webtls path (`config_dir()`, `default_cert_path()`,
    etc.) is `Path.home()`-relative -- point BOTH modules' `Path.home()`
    (they're two independent module-level imports of `pathlib.Path`, not a
    shared object) at an isolated tmp_path so this file never touches the
    developer's real `~/.config/amplifier-work-tracker/`."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(WA.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(WT.Path, "home", classmethod(lambda cls: fake_home))
    return fake_home


def _basic_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(
        host=None,
        public=False,
        port=8090,
        auth_mode="password",
        session_ttl=3600,
    )
    kwargs.update(overrides)
    return kwargs


# --------------------------------------------------------------- no TLS given


def test_resolve_web_config_defaults_to_no_tls_when_nothing_configured():
    config, messages = webapp.resolve_web_config(**_basic_kwargs())
    assert config.tls_cert is None
    assert config.tls_key is None
    assert not any("TLS" in m for m in messages)


# ------------------------------------------------------- explicit cert/key


def test_resolve_web_config_uses_explicit_tls_cert_and_key(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_text("cert", encoding="utf-8")
    key_path.write_text("key", encoding="utf-8")

    config, messages = webapp.resolve_web_config(
        **_basic_kwargs(tls_cert=str(cert_path), tls_key=str(key_path))
    )
    assert config.tls_cert == str(cert_path)
    assert config.tls_key == str(key_path)
    assert any("TLS enabled" in m for m in messages)


def test_resolve_web_config_raises_for_missing_explicit_cert(tmp_path):
    key_path = tmp_path / "key.pem"
    key_path.write_text("key", encoding="utf-8")
    with pytest.raises(webapp.WebConfigError, match="not found"):
        webapp.resolve_web_config(
            **_basic_kwargs(tls_cert=str(tmp_path / "nope.crt"), tls_key=str(key_path))
        )


def test_resolve_web_config_raises_for_missing_explicit_key(tmp_path):
    cert_path = tmp_path / "cert.pem"
    cert_path.write_text("cert", encoding="utf-8")
    with pytest.raises(webapp.WebConfigError, match="not found"):
        webapp.resolve_web_config(
            **_basic_kwargs(tls_cert=str(cert_path), tls_key=str(tmp_path / "nope.key"))
        )


def test_resolve_web_config_raises_when_only_tls_cert_given():
    with pytest.raises(webapp.WebConfigError, match="must both be given together"):
        webapp.resolve_web_config(**_basic_kwargs(tls_cert="/some/cert.pem"))


def test_resolve_web_config_raises_when_only_tls_key_given():
    with pytest.raises(webapp.WebConfigError, match="must both be given together"):
        webapp.resolve_web_config(**_basic_kwargs(tls_key="/some/key.pem"))


def test_resolve_web_config_never_silently_falls_back_to_http_for_missing_explicit_cert(tmp_path):
    """Explicit fail-loud requirement: a caller-supplied --tls-cert/--tls-key
    that doesn't exist must refuse, not silently degrade to plain http
    (unlike muxplex's own `serve()`, which prints a warning and falls back
    -- this package's fail-loud contract, matching `WebServerStartupError`
    elsewhere, is deliberately stricter here)."""
    with pytest.raises(webapp.WebConfigError):
        webapp.resolve_web_config(
            **_basic_kwargs(tls_cert="/definitely/not/here.crt", tls_key="/definitely/not/here.key")
        )


def test_resolve_web_config_raises_for_unreadable_explicit_cert(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_text("cert", encoding="utf-8")
    key_path.write_text("key", encoding="utf-8")
    cert_path.chmod(0o000)
    try:
        with pytest.raises(webapp.WebConfigError, match="not readable"):
            webapp.resolve_web_config(
                **_basic_kwargs(tls_cert=str(cert_path), tls_key=str(key_path))
            )
    finally:
        cert_path.chmod(0o600)  # restore so tmp_path cleanup can remove it


# ------------------------------------------------------------ auto-detected


def test_resolve_web_config_auto_detects_setup_tls_default_cert(_isolated_home):
    default_cert = WT.default_cert_path()
    default_key = WT.default_key_path()
    default_cert.write_text("cert", encoding="utf-8")
    default_key.write_text("key", encoding="utf-8")

    config, messages = webapp.resolve_web_config(**_basic_kwargs())
    assert config.tls_cert == str(default_cert)
    assert config.tls_key == str(default_key)
    assert any("TLS enabled" in m for m in messages)


def test_resolve_web_config_ignores_a_half_present_default_cert(_isolated_home):
    """Only the cert exists, not the key (setup-tls always writes both, but
    a manually-deleted key is possible) -- must NOT enable TLS with a
    missing key file."""
    WT.default_cert_path().write_text("cert", encoding="utf-8")
    config, _messages = webapp.resolve_web_config(**_basic_kwargs())
    assert config.tls_cert is None
    assert config.tls_key is None


def test_resolve_web_config_explicit_paths_take_priority_over_auto_detected(
    tmp_path, _isolated_home
):
    WT.default_cert_path().write_text("default-cert", encoding="utf-8")
    WT.default_key_path().write_text("default-key", encoding="utf-8")
    explicit_cert = tmp_path / "explicit.crt"
    explicit_key = tmp_path / "explicit.key"
    explicit_cert.write_text("cert", encoding="utf-8")
    explicit_key.write_text("key", encoding="utf-8")

    config, _messages = webapp.resolve_web_config(
        **_basic_kwargs(tls_cert=str(explicit_cert), tls_key=str(explicit_key))
    )
    assert config.tls_cert == str(explicit_cert)
    assert config.tls_key == str(explicit_key)


# --------------------------------------------------------------------- run()


def test_run_passes_ssl_kwargs_to_uvicorn_when_tls_configured(monkeypatch, tmp_path):
    from amplifier_work_tracker import adapter as A

    captured: dict = {}

    class _FakeUvicorn:
        @staticmethod
        def run(app, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", _FakeUvicorn)

    ws = A.Workspace(tmp_path / "root")
    auth = WA.AuthConfig(mode="password", secret="s", ttl_seconds=3600, password="p")  # noqa: S106
    config = webapp.WebServerConfig(
        host="127.0.0.1",
        port=8090,
        auth=auth,
        tls_cert="/certs/cert.pem",
        tls_key="/certs/key.pem",
    )

    webapp.run(ws, config)

    assert captured.get("ssl_certfile") == "/certs/cert.pem"
    assert captured.get("ssl_keyfile") == "/certs/key.pem"


def test_run_omits_ssl_kwargs_when_no_tls_configured(monkeypatch, tmp_path):
    from amplifier_work_tracker import adapter as A

    captured: dict = {}

    class _FakeUvicorn:
        @staticmethod
        def run(app, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", _FakeUvicorn)

    ws = A.Workspace(tmp_path / "root")
    auth = WA.AuthConfig(mode="password", secret="s", ttl_seconds=3600, password="p")  # noqa: S106
    config = webapp.WebServerConfig(host="127.0.0.1", port=8090, auth=auth)

    webapp.run(ws, config)

    assert "ssl_certfile" not in captured
    assert "ssl_keyfile" not in captured


# ------------------------------------------------- trust-bootstrap port resolution


def test_resolve_http_bootstrap_port_none_when_no_tls():
    assert webapp._resolve_http_bootstrap_port(None, tls_cert=None, port=8090) is None
    assert webapp._resolve_http_bootstrap_port(9000, tls_cert=None, port=8090) is None


def test_resolve_http_bootstrap_port_defaults_to_port_plus_one_when_tls_active():
    assert webapp._resolve_http_bootstrap_port(None, tls_cert="/some/cert.pem", port=8090) == 8091


def test_resolve_http_bootstrap_port_uses_explicit_value_when_tls_active():
    result = webapp._resolve_http_bootstrap_port(9999, tls_cert="/some/cert.pem", port=8090)
    assert result == 9999


def test_resolve_http_bootstrap_port_raises_on_collision_with_https_port():
    with pytest.raises(webapp.WebConfigError, match="must not be the same"):
        webapp._resolve_http_bootstrap_port(8090, tls_cert="/some/cert.pem", port=8090)


def test_resolve_web_config_no_trust_bootstrap_message_without_tls():
    config, messages = webapp.resolve_web_config(**_basic_kwargs())
    assert config.http_port is None
    assert not any("Trust bootstrap" in m for m in messages)


def test_resolve_web_config_defaults_trust_bootstrap_port_when_tls_active(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_text("cert", encoding="utf-8")
    key_path.write_text("key", encoding="utf-8")

    config, messages = webapp.resolve_web_config(
        **_basic_kwargs(tls_cert=str(cert_path), tls_key=str(key_path))
    )
    assert config.http_port == 8091
    assert any("Trust bootstrap listening on http://" in m for m in messages)
    assert any(":8091/trust" in m for m in messages)


def test_resolve_web_config_uses_explicit_http_port_when_tls_active(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_text("cert", encoding="utf-8")
    key_path.write_text("key", encoding="utf-8")

    config, _messages = webapp.resolve_web_config(
        **_basic_kwargs(tls_cert=str(cert_path), tls_key=str(key_path), http_port=9500)
    )
    assert config.http_port == 9500


def test_resolve_web_config_ignores_http_port_without_tls_but_notes_it():
    config, messages = webapp.resolve_web_config(**_basic_kwargs(http_port=9500))
    assert config.http_port is None
    assert any("ignored" in m and "9500" in m for m in messages)


def test_resolve_web_config_raises_on_http_port_colliding_with_https_port(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_text("cert", encoding="utf-8")
    key_path.write_text("key", encoding="utf-8")

    with pytest.raises(webapp.WebConfigError, match="must not be the same"):
        webapp.resolve_web_config(
            **_basic_kwargs(tls_cert=str(cert_path), tls_key=str(key_path), http_port=8090)
        )


# --------------------------------------------- run() with a companion listener


def test_run_starts_both_servers_when_http_port_is_set(monkeypatch, tmp_path):
    """`run()` must gather TWO uvicorn servers -- the primary app and the
    trust-bootstrap app -- when `config.http_port` is set, never just the
    primary one."""
    from amplifier_work_tracker import adapter as A

    started_ports: list[int] = []

    class _FakeServer:
        def __init__(self, config):
            self._config = config

        async def serve(self):
            started_ports.append(self._config.port)

    class _FakeUvicorn:
        Config = staticmethod(lambda *a, **k: __import__("types").SimpleNamespace(**k))
        Server = _FakeServer

        @staticmethod
        def run(app, **kwargs):
            raise AssertionError("uvicorn.run must not be called when http_port is set")

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", _FakeUvicorn)

    ws = A.Workspace(tmp_path / "root")
    auth = WA.AuthConfig(mode="password", secret="s", ttl_seconds=3600, password="p")  # noqa: S106
    config = webapp.WebServerConfig(
        host="127.0.0.1",
        port=8090,
        auth=auth,
        tls_cert="/certs/cert.pem",
        tls_key="/certs/key.pem",
        http_port=8091,
    )

    result = webapp.run(ws, config)

    assert result == 0
    assert sorted(started_ports) == [8090, 8091]
