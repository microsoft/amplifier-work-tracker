"""Tier 1 -- amplifier_work_tracker.prereqs: bd/dolt binary presence, bd's
version floor, and the install-command builders.

Everything here is fake-PATH / forged-output -- no network, no real
downloads, and no dependency on whether bd/dolt actually happen to be
installed on the machine running this suite. `check()` is exercised the
same way `os.environ["PATH"]` actually works: point it at a tmp directory
containing (or lacking) an executable named `bd`/`dolt`, never mock
`shutil.which` or `subprocess.run` directly -- that would test our mocks,
not the real PATH-resolution behaviour a fresh machine actually exhibits.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import prereqs as P

CI_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _write_stub(bin_dir: Path, name: str, version_output: str) -> None:
    """A fake executable that prints `version_output` for `<name> --version`
    (bd's shape) or `<name> version` (dolt's shape) and exits 0 for
    anything else it's called with, so it behaves like a real binary well
    enough for `shutil.which` + `subprocess.run(["<name>", "--version"])`
    to succeed against it."""
    script = bin_dir / name
    script.write_text(f"#!/bin/sh\necho '{version_output}'\nexit 0\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _isolated_shim_dir(tmp_path: Path, binary: str) -> str | None:
    """A tmp directory containing ONLY a symlink to the real `binary` --
    never the real binary's whole directory, which (on this very dev
    machine) holds bd AND dolt side by side and would defeat a
    dolt_missing/bd_missing test by accident. Returns None if `binary`
    isn't found on PATH at all (caller should skip)."""
    import shutil

    found = shutil.which(binary)
    if found is None:
        return None
    shim_dir = tmp_path / f"{binary}_shim"
    shim_dir.mkdir()
    (shim_dir / binary).symlink_to(found)
    return str(shim_dir)


# ---------------------------------------------------------------------------
# _os_arch -- platform/arch detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "system, machine, expected",
    [
        ("Linux", "x86_64", ("linux", "amd64")),
        ("Linux", "aarch64", ("linux", "arm64")),
        ("Darwin", "arm64", ("darwin", "arm64")),
        ("Darwin", "x86_64", ("darwin", "amd64")),
    ],
)
def test_os_arch_recognizes_supported_combinations(monkeypatch, system, machine, expected):
    monkeypatch.setattr(P.platform, "system", lambda: system)
    monkeypatch.setattr(P.platform, "machine", lambda: machine)
    assert P._os_arch() == expected


def test_os_arch_raises_on_unknown_os(monkeypatch):
    monkeypatch.setattr(P.platform, "system", lambda: "Windows")
    monkeypatch.setattr(P.platform, "machine", lambda: "AMD64")
    with pytest.raises(RuntimeError, match="no known bd/dolt release asset"):
        P._os_arch()


def test_os_arch_raises_on_unknown_arch(monkeypatch):
    monkeypatch.setattr(P.platform, "system", lambda: "Linux")
    monkeypatch.setattr(P.platform, "machine", lambda: "riscv64")
    with pytest.raises(RuntimeError, match="no known bd/dolt release asset"):
        P._os_arch()


# ---------------------------------------------------------------------------
# install command builders
# ---------------------------------------------------------------------------


def test_bd_install_version_is_derived_from_min_version_not_duplicated():
    assert P.bd_install_version() == ".".join(str(p) for p in A.MIN_VERSION)


def test_bd_install_command_linux_amd64(monkeypatch):
    monkeypatch.setattr(P.platform, "system", lambda: "Linux")
    monkeypatch.setattr(P.platform, "machine", lambda: "x86_64")
    cmd = P.bd_install_command()
    version = P.bd_install_version()
    assert f"beads_{version}_linux_amd64.tar.gz" in cmd
    assert f"gastownhall/beads/releases/download/v{version}/" in cmd
    assert "~/.local/bin/bd" in cmd
    assert "sudo" not in cmd


def test_bd_install_command_never_contains_rm(monkeypatch):
    """`rm -rf /tmp/...` trips Amplifier's own bash safety profile (the
    literal substring `rm -rf /` matches at a command position regardless
    of whether the path is actually root) -- an agent asked to run the
    command this function emits must never hit "Command denied for
    safety." Uses `mktemp -d` and simply never cleans up instead."""
    monkeypatch.setattr(P.platform, "system", lambda: "Linux")
    monkeypatch.setattr(P.platform, "machine", lambda: "x86_64")
    cmd = P.bd_install_command()
    assert "rm " not in cmd
    assert "rm-" not in cmd
    assert "mktemp -d" in cmd


def test_dolt_install_command_never_contains_rm(monkeypatch):
    monkeypatch.setattr(P.platform, "system", lambda: "Linux")
    monkeypatch.setattr(P.platform, "machine", lambda: "x86_64")
    cmd = P.dolt_install_command()
    assert "rm " not in cmd
    assert "mktemp -d" in cmd


def test_bd_install_command_linux_arm64(monkeypatch):
    monkeypatch.setattr(P.platform, "system", lambda: "Linux")
    monkeypatch.setattr(P.platform, "machine", lambda: "aarch64")
    cmd = P.bd_install_command()
    assert f"beads_{P.bd_install_version()}_linux_arm64.tar.gz" in cmd


def test_bd_install_command_darwin_arm64(monkeypatch):
    monkeypatch.setattr(P.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(P.platform, "machine", lambda: "arm64")
    cmd = P.bd_install_command()
    assert f"beads_{P.bd_install_version()}_darwin_arm64.tar.gz" in cmd


def test_bd_install_command_darwin_amd64_has_no_published_asset(monkeypatch):
    """beads does not publish this asset -- must name the gap, never emit a
    command pointed at a URL that will 404."""
    monkeypatch.setattr(P.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(P.platform, "machine", lambda: "x86_64")
    with pytest.raises(RuntimeError, match="darwin_amd64"):
        P.bd_install_command()


def test_dolt_install_command_linux_amd64_matches_ci_asset_shape(monkeypatch):
    monkeypatch.setattr(P.platform, "system", lambda: "Linux")
    monkeypatch.setattr(P.platform, "machine", lambda: "x86_64")
    cmd = P.dolt_install_command()
    assert "dolt-linux-amd64.tar.gz" in cmd
    assert f"dolthub/dolt/releases/download/v{P.DOLT_INSTALL_VERSION}/" in cmd
    assert "--strip-components=1" in cmd
    assert "~/.local/bin/dolt" in cmd
    assert "sudo" not in cmd


def test_dolt_install_command_darwin_arm64(monkeypatch):
    monkeypatch.setattr(P.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(P.platform, "machine", lambda: "arm64")
    cmd = P.dolt_install_command()
    assert "dolt-darwin-arm64.tar.gz" in cmd


# ---------------------------------------------------------------------------
# check() -- the whole state machine, exercised via a real, controlled PATH
# ---------------------------------------------------------------------------


def test_check_returns_none_when_bd_and_dolt_both_satisfied():
    """The ambient environment this suite runs in either has both real
    binaries (nothing to fix) or doesn't -- either way, this asserts
    `check()` agrees with reality rather than asserting a fixed outcome."""
    import shutil

    if shutil.which("bd") is None or shutil.which("dolt") is None:
        pytest.skip("bd/dolt not both present in the ambient test environment")
    result = P.check()
    assert result is None


def test_check_reports_bd_missing_when_path_has_neither_binary(tmp_path, monkeypatch):
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    result = P.check()
    assert result is not None
    assert result.state == "bd_missing"
    assert "bd is not on PATH" in result.fix


def test_check_prefers_bd_missing_over_dolt_missing(tmp_path, monkeypatch):
    """Dependency order: with NEITHER binary present, the first failure
    (bd) is reported, not the second (dolt) -- proves the ordering, not
    just that failures are detected at all."""
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    result = P.check()
    assert result is not None
    assert result.state == "bd_missing"


def test_check_reports_bd_too_old_via_forged_version_string(tmp_path, monkeypatch):
    """`bd` present and executable, but reporting a version below
    `adapter.MIN_VERSION` -- forged via a stub script, no real old build
    needed."""
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    _write_stub(stub_bin, "bd", "bd version 1.0.0 (deadbeef)")
    # dolt's presence must not matter here -- bd_too_old should be reported
    # regardless of whether dolt is reachable, since the ordering stops at
    # the first failure.
    monkeypatch.setenv("PATH", str(stub_bin))

    result = P.check()
    assert result is not None
    assert result.state == "bd_too_old"
    assert "1.0.0" in result.fix
    assert ".".join(str(p) for p in A.MIN_VERSION) in result.fix


def test_check_reports_bd_too_old_when_version_unparseable(tmp_path, monkeypatch):
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    _write_stub(stub_bin, "bd", "not a version string at all")
    monkeypatch.setenv("PATH", str(stub_bin))

    result = P.check()
    assert result is not None
    assert result.state == "bd_too_old"
    assert "could not be determined" in result.fix


def test_check_reports_dolt_missing_when_bd_ok_but_dolt_absent(tmp_path, monkeypatch):
    bd_shim_dir = _isolated_shim_dir(tmp_path, "bd")
    if bd_shim_dir is None:
        pytest.skip("real `bd` binary not present in the ambient test environment")
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    # ONLY a shim to the real bd on PATH -- deliberately NOT bd's whole real
    # directory, which on a dev machine may also contain dolt (installed
    # alongside it) and would silently defeat this test.
    monkeypatch.setenv("PATH", os.pathsep.join([bd_shim_dir, str(empty_bin)]))

    result = P.check()
    assert result is not None
    assert result.state == "dolt_missing"
    assert "dolt is not on PATH" in result.fix


def test_check_never_raises_for_a_missing_binary(tmp_path, monkeypatch):
    """The whole point: a missing prerequisite is the expected, common
    zero-machine case -- it must be reported, never raised."""
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    # Must not raise.
    P.check()


# ---------------------------------------------------------------------------
# CI drift guard -- makes "cannot drift" true rather than aspirational.
# ---------------------------------------------------------------------------


def test_ci_workflow_pins_match_our_constants():
    """`.github/workflows/ci.yml` is the executable source of truth for
    which bd/dolt versions actually install and pass CI. This test fails
    the moment this module's constants diverge from it -- no YAML
    dependency needed, both lines are plain `KEY: "value"` scalars."""
    assert CI_YML.is_file(), f"expected ci.yml at {CI_YML}"
    text = CI_YML.read_text(encoding="utf-8")

    bd_match = re.search(r'^\s*BD_VERSION:\s*"([^"]+)"', text, re.MULTILINE)
    dolt_match = re.search(r'^\s*DOLT_VERSION:\s*"([^"]+)"', text, re.MULTILINE)
    assert bd_match, "ci.yml no longer defines BD_VERSION -- update this guard"
    assert dolt_match, "ci.yml no longer defines DOLT_VERSION -- update this guard"

    assert bd_match.group(1) == P.bd_install_version(), (
        f"ci.yml's BD_VERSION ({bd_match.group(1)}) has drifted from adapter.MIN_VERSION "
        f"({P.bd_install_version()}) -- bump both together (see adapter.py's MIN_VERSION "
        f"comment and ci.yml's own env-block comment)"
    )
    assert dolt_match.group(1) == P.DOLT_INSTALL_VERSION, (
        f"ci.yml's DOLT_VERSION ({dolt_match.group(1)}) has drifted from "
        f"prereqs.DOLT_INSTALL_VERSION ({P.DOLT_INSTALL_VERSION}) -- bump both together"
    )
