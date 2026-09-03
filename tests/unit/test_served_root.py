"""Tier 1 -- `service.parse_systemd_served_root` / `parse_launchd_served_root`:
reading back WHICH workspace root an installed unit was actually told to serve.

Why this instrument exists (`model_performance-jyg`): the service is a
SINGLETON per user and a workspace root is not. `doctor` runs against
whichever root it was pointed at, while the sweep heartbeat is written under
the root the SUPERVISOR was given. `cli._check_sweeps_alive` joined those two
scopes without checking they referred to the same root, so on any machine
whose service serves a different root -- every isolated test root, by
construction -- an absent heartbeat was reported as a hard FAIL of a
perfectly healthy pair of sweep loops.

Both readers are PURE (text in, Path out) so every branch is testable with no
systemd, no launchd, and nothing installed. The two round-trip tests are the
load-bearing ones: they pin the READER to the WRITER (`_build_systemd_unit` /
`_LAUNCHD_PLIST_TEMPLATE`), so a future change to how `--root` is baked in
cannot silently make the reader answer None -- which would quietly restore
the old false FAIL rather than announce itself.
"""

from __future__ import annotations

from pathlib import Path

from amplifier_work_tracker import service as S

# ------------------------------------------------------------------- systemd


def test_round_trips_the_root_baked_into_a_really_rendered_unit():
    """The reader must agree with the writer. This is the test that keeps
    them from drifting apart -- not a hand-written unit fixture, but the
    real rendered output of the real install path."""
    root = Path("/srv/some/workspace root")  # a space, deliberately
    unit_text = S._systemd_unit_content(root, dolt_host="127.0.0.1", dolt_port=3307)
    assert S.parse_systemd_served_root(unit_text) == root


def test_round_trips_a_unit_rendered_with_every_web_flag_set():
    """The `--root` reader must not be confused by the other flags
    `_serve_argv_tail` can append after it."""
    root = Path("/srv/ws")
    unit_text = S._systemd_unit_content(
        root,
        dolt_host="127.0.0.1",
        dolt_port=3307,
        web_port=8095,
        web_host="0.0.0.0",
        web_public=True,
        web_auth_mode="pam",
        web_session_ttl=43200,
    )
    assert S.parse_systemd_served_root(unit_text) == root


def test_reads_the_equals_form_of_the_flag():
    unit_text = "[Service]\nExecStart=/usr/bin/awt serve --root=/srv/ws\n"
    assert S.parse_systemd_served_root(unit_text) == Path("/srv/ws")


def test_tolerates_systemd_execstart_prefix_characters():
    """`-`/`@`/`+` are systemd's own ExecStart modifiers. Our template emits
    none, but a hand-edited unit is still a unit we must read honestly
    rather than misreport as 'no root'."""
    for prefix in ("-", "@", "+", "!"):
        unit_text = f"[Service]\nExecStart={prefix}/usr/bin/awt serve --root /srv/ws\n"
        assert S.parse_systemd_served_root(unit_text) == Path("/srv/ws"), prefix


def test_a_unit_with_no_root_argument_reads_as_cannot_tell():
    unit_text = "[Service]\nExecStart=/usr/bin/awt serve\n"
    assert S.parse_systemd_served_root(unit_text) is None


def test_a_trailing_root_flag_with_no_value_reads_as_cannot_tell():
    """Never invent a root from a truncated argument -- `--root` with
    nothing after it is unanswerable, not empty."""
    unit_text = "[Service]\nExecStart=/usr/bin/awt serve --root\n"
    assert S.parse_systemd_served_root(unit_text) is None


def test_an_unquotable_execstart_reads_as_cannot_tell_rather_than_raising():
    """shlex raises on an unbalanced quote. A diagnostic reader must never
    be able to crash `doctor`."""
    unit_text = '[Service]\nExecStart=/usr/bin/awt serve --root "/srv/unclosed\n'
    assert S.parse_systemd_served_root(unit_text) is None


def test_empty_text_reads_as_cannot_tell():
    assert S.parse_systemd_served_root("") is None


# ------------------------------------------------------------------- launchd


def _plist_with(argv: list[str]) -> str:
    from xml.sax.saxutils import escape

    body = "\n".join(f"        <string>{escape(a)}</string>" for a in argv)
    return S._LAUNCHD_PLIST_TEMPLATE.format(
        label="com.amplifier-work-tracker",
        program_arguments_xml=body,
        safe_path="/usr/bin:/bin",
        log_path="/tmp/out.log",
        err_path="/tmp/err.log",
    )


def test_launchd_round_trips_the_root_from_program_arguments():
    """Same writer-to-reader pin as the systemd round-trip, through the real
    plist template and the real argv tail both install paths share."""
    root = Path("/Users/someone/ws")
    argv = ["/usr/local/bin/awt", *S._serve_argv_tail(root, dolt_host="127.0.0.1", dolt_port=3307)]
    assert S.parse_launchd_served_root(_plist_with(argv)) == root


def test_launchd_plist_with_no_root_argument_reads_as_cannot_tell():
    assert S.parse_launchd_served_root(_plist_with(["/usr/local/bin/awt", "serve"])) is None


def test_launchd_malformed_xml_reads_as_cannot_tell_rather_than_raising():
    assert S.parse_launchd_served_root("<plist><not-really>") is None


def test_launchd_plist_without_program_arguments_reads_as_cannot_tell():
    text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0"><dict><key>Label</key><string>x</string></dict></plist>'
    )
    assert S.parse_launchd_served_root(text) is None


# --------------------------------------------------------- _read_served_root


def test_read_served_root_of_a_missing_file_is_cannot_tell_not_a_crash():
    assert S._read_served_root(Path("/nonexistent/unit.service"), platform="linux") is None


def test_read_served_root_of_no_unit_at_all_is_cannot_tell():
    assert S._read_served_root(None, platform="linux") is None


def test_read_served_root_dispatches_on_platform(tmp_path):
    unit = tmp_path / "u.service"
    unit.write_text("[Service]\nExecStart=/x serve --root /srv/ws\n", encoding="utf-8")
    assert S._read_served_root(unit, platform="linux") == Path("/srv/ws")
    # Same bytes read as a plist is not valid XML -- "cannot tell", not a
    # crash and not a systemd-shaped answer smuggled through the mac path.
    assert S._read_served_root(unit, platform="darwin") is None
