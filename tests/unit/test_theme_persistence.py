"""Tier 1 -- a chosen theme survives a refresh.

`contracts/operator-surface.v1.md` Core 10, machine check
`antigoals.enforced`: "no view holds state that does not survive a refresh
(state persisted in `localStorage` or on the server survives; state held
only in page memory does not)". The theme toggle used to hold its choice in
page memory alone -- `wtSetTheme` set an attribute and nothing else -- so
Light came back Dark on the next load and on every navigation.

Two layers here, and the split is deliberate:

  * the STRUCTURAL tests always run. They assert the contract the server
    emits: one shared storage key, the resolver inlined in `<head>` ahead of
    the body, the setter persisting, the toggle re-syncing after a body swap.
  * the BEHAVIOURAL tests actually EXECUTE the emitted JavaScript under
    `node` against a small fake DOM, and do the real round trip: load, click
    Light, reload, assert Light came back. Structural assertions cannot tell
    a working script from a plausible-looking one; this is what closes that
    gap without adding a browser to this tier.

`node` is preinstalled on the CI runner (`ubuntu-latest`), so these are not
theoretical; on a machine without it they skip, the same way this suite's
web tests skip without the `web` extra. The structural layer still runs
there, so the emitted contract is never unasserted.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker import webapp as W  # noqa: E402
from amplifier_work_tracker import webtheme as T  # noqa: E402

# ----------------------------------------------------------------- structural


def test_the_storage_key_is_declared_once_and_used_by_both_sides():
    """The writer (`wtSetTheme`, webapp) and the first-paint reader
    (`theme_boot_js`, webtheme) must name the SAME key. Two spellings would
    fail silently and look exactly like "the toggle does nothing".
    """
    assert T.THEME_STORAGE_KEY == "wt-theme"
    assert f"'{T.THEME_STORAGE_KEY}'" in W._OBSERVATORY_THEME_JS  # noqa: SLF001
    assert f"'{T.THEME_STORAGE_KEY}'" in T.theme_boot_js()


def test_the_setter_persists_the_choice():
    setter = W._OBSERVATORY_THEME_JS  # noqa: SLF001
    assert "function wtSetTheme(t){" in setter
    assert "localStorage.setItem(" in setter


def test_the_setter_survives_storage_being_unavailable():
    """A browser with storage disabled throws on `setItem`. A theme
    preference is never worth breaking a page over.
    """
    assert "try{ localStorage.setItem(" in W._OBSERVATORY_THEME_JS  # noqa: SLF001
    assert "catch" in W._OBSERVATORY_THEME_JS  # noqa: SLF001
    assert "try{" in T.theme_boot_js()


def test_the_resolver_is_inlined_in_head_before_the_body():
    """A body-end script applies the stored theme one full paint too late --
    that is the flash-of-wrong-theme this placement exists to prevent.
    """
    html = T.page("t", "<p>body</p>", js=W._OBSERVATORY_THEME_JS)  # noqa: SLF001
    boot = T.theme_boot_js()
    assert boot in html
    assert html.index(boot) < html.index("<head>") + len(html[: html.index("</head>")])
    assert html.index(boot) < html.index("<body")


def test_the_server_still_declares_dark_as_the_first_paint_default():
    """PR #55's fix, unregressed: `<html>` must carry `data-theme` from the
    server, or a light-OS browser silently wins the token cascade. The
    resolver only ever REPLACES this attribute -- it never removes it.
    """
    html = T.page("t", "<p>body</p>")
    assert '<html lang="en" data-theme="dark">' in html
    assert "removeAttribute" not in T.theme_boot_js()


def test_the_resolver_prefers_an_explicit_choice_over_the_os_preference():
    """Order matters in the source as well as at runtime: the stored value is
    read first, and `prefers-color-scheme` is consulted only in the branch
    where it was absent or invalid.
    """
    boot = T.theme_boot_js()
    assert boot.index("localStorage.getItem") < boot.index("prefers-color-scheme")
    assert "if(t!=='light'&&t!=='dark')" in boot


def test_the_toggle_resyncs_itself_after_the_body_swap():
    """`data-theme` lives on `<html>`, which the 20s swap never touches --
    but the toggle BUTTONS come back server-rendered with Dark pressed every
    tick. The swap re-executes body scripts, so this call re-derives
    `aria-pressed` from the live attribute.
    """
    js = W._OBSERVATORY_THEME_JS  # noqa: SLF001
    assert "wtApplyTheme(document.documentElement.getAttribute('data-theme') || 'dark');" in js
    # The swap replaces body CONTENTS and re-runs their scripts -- the two
    # facts this re-sync depends on. Asserted here so a change to the swap
    # mechanism lands on a failing test that names the dependency.
    swap = T.auto_refresh_js(20000)
    assert "document.body.innerHTML = doc.body.innerHTML;" in swap
    assert "document.createElement('script')" in swap


def test_only_the_visitors_own_click_persists_anything():
    """The re-sync call and the OS preference must NOT write to storage:
    doing so would freeze whatever the OS happened to prefer on the first
    visit into a stored "choice" nobody made.
    """
    js = W._OBSERVATORY_THEME_JS  # noqa: SLF001
    apply_fn = js[js.index("function wtApplyTheme(t){") : js.index("function wtSetTheme(t){")]
    assert "localStorage" not in apply_fn
    assert "setItem" not in T.theme_boot_js()


# ---------------------------------------------------------------- behavioural

_NODE = shutil.which("node")

#: A fake DOM just large enough to run the two real scripts: the `<html>`
#: element's attributes, the two toggle buttons, `localStorage`, and
#: `matchMedia`. Everything the scripts touch and nothing else.
_HARNESS = """
const scenario = JSON.parse(require('fs').readFileSync(0, 'utf8'));
function run(storage, prefersLight, serverTheme, click) {
  const attrs = { 'data-theme': serverTheme };
  const buttons = ['dark', 'light'].map(function (name) {
    return {
      dataset: { theme: name },
      attrs: {},
      setAttribute: function (k, v) { this.attrs[k] = v; },
    };
  });
  const document = {
    documentElement: {
      setAttribute: function (k, v) { attrs[k] = v; },
      getAttribute: function (k) { return k in attrs ? attrs[k] : null; },
    },
    querySelectorAll: function (sel) {
      return sel === '.theme-toggle button' ? buttons : [];
    },
  };
  const localStorage = {
    getItem: function (k) { return k in storage ? storage[k] : null; },
    setItem: function (k, v) { storage[k] = v; },
  };
  const window = {
    matchMedia: function (q) {
      return { matches: prefersLight && q.indexOf('light') !== -1 };
    },
  };
  const src = scenario.boot + '\\n' + scenario.theme_js + '\\n' +
    (click ? "wtSetTheme('" + click + "');" : '');
  new Function('document', 'window', 'localStorage', src)(document, window, localStorage);
  const pressed = {};
  buttons.forEach(function (b) { pressed[b.dataset.theme] = b.attrs['aria-pressed']; });
  return { theme: attrs['data-theme'], pressed: pressed };
}
const storage = Object.assign({}, scenario.stored);
const first = run(storage, scenario.prefers_light, 'dark', scenario.click);
// The RELOAD: a brand-new document served the same server-side default,
// carrying over only what the browser actually kept -- `storage`.
const second = run(storage, scenario.prefers_light, 'dark', null);
console.log(JSON.stringify({ first: first, second: second, storage: storage }));
"""

needs_node = pytest.mark.skipif(_NODE is None, reason="node is not installed on this host")


def _round_trip(*, stored=None, prefers_light=False, click=None) -> dict:
    """Load a page, optionally click a theme button, then RELOAD it."""
    assert _NODE is not None
    scenario = {
        "boot": T.theme_boot_js(),
        "theme_js": W._OBSERVATORY_THEME_JS,  # noqa: SLF001
        "stored": stored or {},
        "prefers_light": prefers_light,
        "click": click,
    }
    proc = subprocess.run(
        [_NODE, "-e", _HARNESS],
        input=json.dumps(scenario),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"node harness failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


@needs_node
def test_a_fresh_visitor_with_no_preference_gets_dark():
    out = _round_trip()
    assert out["first"]["theme"] == "dark"
    assert out["first"]["pressed"] == {"dark": "true", "light": "false"}
    assert out["storage"] == {}, "nothing was chosen, so nothing should have been stored"


@needs_node
def test_choosing_light_then_reloading_keeps_light():
    """THE row's own question, asked end to end: render, set the theme,
    re-render, assert the stored value is applied.
    """
    out = _round_trip(click="light")
    assert out["first"]["theme"] == "light"
    assert out["storage"] == {T.THEME_STORAGE_KEY: "light"}
    assert out["second"]["theme"] == "light", (
        "the theme died on refresh -- the server default won again, which is "
        "exactly the Core 10 violation this closed"
    )
    assert out["second"]["pressed"] == {"dark": "false", "light": "true"}, (
        "the page came back Light but the toggle shows Dark pressed"
    )


@needs_node
def test_choosing_dark_on_a_light_os_survives_the_reload_too():
    """The harder direction: the stored choice must beat a CONTRADICTING OS
    preference, not merely beat an absent one.
    """
    out = _round_trip(prefers_light=True, click="dark")
    assert out["first"]["theme"] == "dark"
    assert out["second"]["theme"] == "dark"
    assert out["second"]["pressed"] == {"dark": "true", "light": "false"}


@needs_node
def test_the_os_light_preference_is_honoured_when_nothing_is_stored():
    out = _round_trip(prefers_light=True)
    assert out["first"]["theme"] == "light"
    assert out["first"]["pressed"] == {"dark": "false", "light": "true"}
    assert out["storage"] == {}, (
        "an OS preference is not a choice the visitor made -- storing it would "
        "freeze the first visit's ambient setting forever"
    )


@needs_node
def test_a_junk_stored_value_falls_back_to_the_default_rather_than_applying_it():
    out = _round_trip(stored={T.THEME_STORAGE_KEY: "chartreuse"})
    assert out["first"]["theme"] == "dark"
