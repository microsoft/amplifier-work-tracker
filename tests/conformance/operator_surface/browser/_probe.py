"""In-page measurement probes, and the pure-Python re-checks that read them.

Every constant here is JavaScript evaluated inside the real page; every
function here is a re-check the test runs over the JSON that came back. The
split is the whole design: the browser MEASURES, the artifact RECORDS, and
Python DECIDES. No probe returns a verdict, and no re-check trusts one.

What each probe measures, and the honest limits of each
------------------------------------------------------

`TEXT_CONTRAST_JS`
    Every visible text-bearing element's computed foreground against its
    effective background, resolved by walking ancestors until an opaque
    background-color is found. An element whose background is a gradient or
    an image cannot be reduced to one colour, so it is returned with
    `resolved: false` and COUNTED SEPARATELY rather than being scored against
    a guess -- an invented background would manufacture whichever verdict the
    guess happened to produce.

`TARGET_SIZE_JS`
    The border box of every interactive element. Each is classified `inline`
    (an `<a>` with `display: inline` sitting inside flowing text) or
    `control`. The 44px floor is asserted over CONTROLS only, which is WCAG
    2.5.8's own inline-link exception -- and the inline population is still
    emitted, so the exemption is visible in the artifact rather than hidden in
    the code.

`OVERFLOW_JS`
    `document.scrollingElement.scrollWidth` vs `clientWidth`, plus the widest
    offending elements when they differ, so a failure names a culprit instead
    of only a number.

`MOTION_JS`
    Every animation `document.getAnimations()` reports, with its effective
    duration, its target's path and the property or keyframe name driving it.
    Under `prefers-reduced-motion: reduce` the surface's kernel rule collapses
    durations to `.001ms` rather than removing animations, so the honest
    question is "does anything actually RUN", i.e. is any effective duration
    longer than `MOTION_EPSILON_MS`.

    WHEN it is asked matters as much as what it asks: a transition created
    before the preference was applied keeps the duration it was created with,
    so a sample taken at the instant of the change catches the page finishing
    what it had already started. `test_tier_b.py::_settled_motion` polls this
    probe until the page is quiescent and records the instant-of-change
    reading separately; neither reading is dropped.

`NON_TEXT_JS`
    Border colours against their own element's background, and SVG
    stroke/fill against theirs. This is a NAMED SUBSET of "non-text
    contrast", not all of it: a decorative gradient edge or an icon drawn as
    a background image is not reachable this way. The subset measured is
    recorded in the artifact so nobody reads the number as a stronger claim
    than it is.

`SWAP_*`
    The Core 6 body-swap instrumentation. See `test_tier_b.py`'s
    `swap.survives` section for why the poll guard is lifted for exactly one
    synchronous call and restored before the swap lands.
"""

from __future__ import annotations

from typing import Any

#: An animation whose effective duration is at or under this is not running.
#: The surface's reduced-motion rule sets `animation-duration:.001ms`, so the
#: floor has to be a small positive number rather than exactly zero.
MOTION_EPSILON_MS = 1.0

#: WCAG floors, quoted from Core 7: "Text contrast is at least 4.5:1 and
#: non-text contrast at least 3:1 ... interactive targets are at least 44px".
TEXT_CONTRAST_FLOOR = 4.5
NON_TEXT_CONTRAST_FLOOR = 3.0
TARGET_SIZE_FLOOR_PX = 44.0

# --------------------------------------------------------------- shared JS

_COLOUR_HELPERS = r"""
function parseColour(value){
  if(!value) return null;
  var m = value.match(/^rgba?\(([^)]+)\)$/);
  if(!m) return null;
  var parts = m[1].split(',').map(function(p){ return parseFloat(p.trim()); });
  if(parts.length < 3) return null;
  var a = parts.length > 3 ? parts[3] : 1;
  return {r: parts[0], g: parts[1], b: parts[2], a: a};
}
function channel(c){
  var s = c / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}
function luminance(c){
  return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
}
function ratio(fg, bg){
  var l1 = luminance(fg), l2 = luminance(bg);
  var hi = Math.max(l1, l2), lo = Math.min(l1, l2);
  return (hi + 0.05) / (lo + 0.05);
}
function composite(fg, bg){
  if(fg.a >= 1) return {r: fg.r, g: fg.g, b: fg.b, a: 1};
  var a = fg.a;
  return {r: fg.r * a + bg.r * (1 - a),
          g: fg.g * a + bg.g * (1 - a),
          b: fg.b * a + bg.b * (1 - a), a: 1};
}
function hex(c){
  function h(v){ var s = Math.round(v).toString(16); return s.length < 2 ? '0' + s : s; }
  return '#' + h(c.r) + h(c.g) + h(c.b);
}
/* The effective background BEHIND `el`: the first ancestor with an opaque
   background-color, compositing any translucent layers passed on the way.
   Returns resolved:false when a gradient/image intervenes -- see the module
   docstring for why that is not silently treated as transparent. */
function effectiveBackground(el){
  var stack = [];
  var node = el;
  while(node && node.nodeType === 1){
    var cs = getComputedStyle(node);
    if(cs.backgroundImage && cs.backgroundImage !== 'none'){
      return {resolved: false, reason: 'background-image', colour: null};
    }
    var c = parseColour(cs.backgroundColor);
    if(c && c.a > 0){
      if(c.a >= 1){
        var out = {r: c.r, g: c.g, b: c.b, a: 1};
        for(var i = stack.length - 1; i >= 0; i--) out = composite(stack[i], out);
        return {resolved: true, reason: '', colour: out};
      }
      stack.push(c);
    }
    node = node.parentElement;
  }
  return {resolved: false, reason: 'no opaque ancestor background', colour: null};
}
function isVisible(el){
  var cs = getComputedStyle(el);
  if(cs.visibility === 'hidden' || cs.display === 'none') return false;
  if(parseFloat(cs.opacity) === 0) return false;
  var r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}
function pathOf(el){
  var bits = [];
  var node = el;
  while(node && node.nodeType === 1 && bits.length < 4){
    var b = node.tagName.toLowerCase();
    if(node.id) { b += '#' + node.id; bits.unshift(b); break; }
    if(node.className && typeof node.className === 'string'){
      var cls = node.className.trim().split(/\s+/).slice(0, 2).join('.');
      if(cls) b += '.' + cls;
    }
    bits.unshift(b);
    node = node.parentElement;
  }
  return bits.join('>');
}
"""


def _with_helpers(body: str) -> str:
    """Wrap a probe body so the colour helpers are in scope.

    `page.evaluate` treats its argument as a single EXPRESSION, so a string
    that opens with `function parseColour(...)` is a syntax error, not a
    program. Measured the hard way: every contrast, target and motion number
    in this kit's first run was lost to `SyntaxError: Unexpected token
    'function'`, and the tests around them failed for a reason that had
    nothing to do with the surface. Wrapping the helpers plus the body in one
    arrow-IIFE makes the whole thing an expression again.
    """
    # `return (` on ONE line, deliberately: JavaScript's automatic semicolon
    # insertion turns a bare `return` followed by a newline into `return;`.
    # Measured -- an earlier form here put the body on the next line and every
    # probe using these helpers silently returned `undefined`, which reached
    # Python as `None` and surfaced as a TypeError three frames away.
    return f"(() => {{\n{_COLOUR_HELPERS}\nreturn ({body});\n}})()"


TEXT_CONTRAST_JS = _with_helpers(
    r"""
(() => {
  var out = [], unresolved = [];
  var all = document.querySelectorAll('body *');
  for(var i = 0; i < all.length; i++){
    var el = all[i];
    var own = '';
    for(var k = 0; k < el.childNodes.length; k++){
      var n = el.childNodes[k];
      if(n.nodeType === 3) own += n.textContent;
    }
    own = own.replace(/\s+/g, ' ').trim();
    if(!own) continue;
    if(!isVisible(el)) continue;
    var cs = getComputedStyle(el);
    var fg = parseColour(cs.color);
    if(!fg) continue;
    var bg = effectiveBackground(el);
    var size = parseFloat(cs.fontSize);
    var weight = parseInt(cs.fontWeight, 10) || 400;
    var entry = {
      path: pathOf(el),
      text: own.slice(0, 60),
      colour: cs.color,
      font_px: size,
      font_weight: weight,
      large: size >= 24 || (size >= 18.66 && weight >= 700)
    };
    if(!bg.resolved){ entry.reason = bg.reason; unresolved.push(entry); continue; }
    var solid = composite(fg, bg.colour);
    entry.foreground_hex = hex(solid);
    entry.background_hex = hex(bg.colour);
    entry.ratio = Math.round(ratio(solid, bg.colour) * 100) / 100;
    out.push(entry);
  }
  return {scored: out, unresolved: unresolved};
})()
"""
)

TARGET_SIZE_JS = r"""
(() => {
  var sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary,' +
            '[role=button], [role=link], [role=tab], [onclick]';
  var out = [];
  var els = document.querySelectorAll(sel);
  for(var i = 0; i < els.length; i++){
    var el = els[i];
    var cs = getComputedStyle(el);
    if(cs.visibility === 'hidden' || cs.display === 'none') continue;
    var r = el.getBoundingClientRect();
    if(r.width === 0 && r.height === 0) continue;
    /* WCAG 2.5.8's inline exception: a link rendered inline inside flowing
       text is sized by the sentence, not by the author. */
    var inline = el.tagName === 'A' && cs.display === 'inline';
    var label = (el.getAttribute('aria-label') || el.textContent || '').replace(/\s+/g,' ').trim();
    out.push({
      path: (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')),
      label: label.slice(0, 40),
      kind: inline ? 'inline' : 'control',
      width: Math.round(r.width * 100) / 100,
      height: Math.round(r.height * 100) / 100
    });
  }
  return out;
})()
"""

#: Horizontal overflow, measured TWO ways on purpose.
#:
#: Conformance 4's literal metric is `scrollWidth == clientWidth`. Measured on
#: this surface, that metric is VACUOUS: `webtheme.py` sets `overflow-x: clip`
#: on `html`/`body`, so content that runs past the viewport is clipped rather
#: than scrolled and `scrollWidth` never grows -- the contract's own bad half
#: ("a fixed-width element wider than 430px emits scrollWidth > clientWidth")
#: does not fire against the shipped page at all. So the probe ALSO reports
#: `elements_beyond_viewport`: elements whose border box extends past
#: `clientWidth`, which clipping cannot hide. Both numbers, plus the computed
#: `overflow-x` that explains the difference, go into the artifact -- naming
#: the vacuity instead of quietly passing on it.
OVERFLOW_JS = r"""
(() => {
  var se = document.scrollingElement || document.documentElement;
  var limit = se.clientWidth;
  var beyond = [];
  var all = document.querySelectorAll('body *');
  for(var i = 0; i < all.length; i++){
    var el = all[i];
    var cs = getComputedStyle(el);
    if(cs.visibility === 'hidden' || cs.display === 'none') continue;
    if(cs.position === 'fixed') continue;
    var r = el.getBoundingClientRect();
    if(r.width === 0 || r.height === 0) continue;
    if(r.right > limit + 1){
      beyond.push({
        path: (el.tagName.toLowerCase() +
               (el.id ? '#' + el.id : '') +
               (el.className && typeof el.className === 'string'
                  ? '.' + el.className.trim().split(/\s+/)[0] : '')),
        right: Math.round(r.right * 100) / 100,
        width: Math.round(r.width * 100) / 100
      });
    }
  }
  beyond.sort(function(a, b){ return b.right - a.right; });
  return {
    scroll_width: se.scrollWidth,
    client_width: limit,
    overflow_px: se.scrollWidth - limit,
    overflow_x_style: getComputedStyle(document.body).overflowX,
    root_overflow_x_style: getComputedStyle(document.documentElement).overflowX,
    elements_beyond_viewport: beyond.length,
    widest_beyond: beyond.slice(0, 8)
  };
})()
"""

#: The status hues AS THE PAGE RESOLVES THEM for the current theme. Read from
#: the live token block rather than hardcoded in Python, because the light
#: theme redefines all three (`--alarm:#92400e`, `--blocked:#991b1b`,
#: `--watch:#3a4468` -- webtheme.py:391). The kit's first run hardcoded the
#: dark values and consequently swept the light renders for colours that
#: cannot appear there, reporting a clean zero for a page it had not actually
#: examined.
RESOLVE_STATUS_TOKENS_JS = r"""
(() => {
  var cs = getComputedStyle(document.documentElement);
  return {
    theme: document.documentElement.getAttribute('data-theme'),
    alarm: cs.getPropertyValue('--alarm').trim(),
    blocked: cs.getPropertyValue('--blocked').trim(),
    watch: cs.getPropertyValue('--watch').trim()
  };
})()
"""

MOTION_JS = _with_helpers(
    r"""
(() => {
  var running = [];
  var anims = typeof document.getAnimations === 'function' ? document.getAnimations() : [];
  var now = performance.now();
  for(var i = 0; i < anims.length; i++){
    var a = anims[i];
    var timing = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : {};
    var duration = typeof timing.duration === 'number' ? timing.duration : 0;
    var target = a.effect && a.effect.target ? a.effect.target : null;
    /* NAMED, not just counted: a row that has to say WHICH animations still
       run under the preference cannot be written from a bare integer, and an
       artifact that only carries the integer forces the note to hand-wave. */
    running.push({
      state: a.playState,
      duration_ms: Math.round(duration * 1000) / 1000,
      target: target ? target.tagName.toLowerCase() : '',
      path: target ? pathOf(target) : '',
      label: target ? (target.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40) : '',
      kind: (a.constructor && a.constructor.name) || '',
      property: a.transitionProperty || a.animationName || '',
      current_time_ms: Math.round((a.currentTime || 0) * 1000) / 1000,
      measured_at_ms: Math.round(now * 1000) / 1000
    });
  }
  var sampled = [];
  var els = document.querySelectorAll('body *');
  for(var j = 0; j < els.length && sampled.length < 400; j++){
    var cs = getComputedStyle(els[j]);
    var ad = cs.animationDuration || '0s', td = cs.transitionDuration || '0s';
    if(ad !== '0s' || td !== '0s'){
      sampled.push({animation: ad, transition: td});
    }
  }
  return {
    reduced_motion_matches: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    animations: running,
    non_zero_declared: sampled
  };
})()
"""
)

#: Non-text contrast over a NAMED, DEFENSIBLE population: the visual boundary
#: of an interactive control, and SVG icon strokes. WCAG 1.4.11 covers "user
#: interface components and graphical objects", not decorative rules -- an
#: earlier form here measured EVERY border on the page and reported 36-65
#: failures per view, most of them panel hairlines the guideline exempts. A
#: number that large stops being a finding and starts being noise, so the
#: population is narrowed here and NAMED in the artifact (`population`), where
#: it can be argued with.
NON_TEXT_JS = _with_helpers(
    r"""
(() => {
  var interactive = 'a[href], button, input:not([type=hidden]), select, textarea, summary,' +
                    '[role=button], [role=link], [role=tab], [onclick]';
  var out = [], unresolved = 0, skipped_decorative = 0;
  var els = document.querySelectorAll('body *');
  for(var i = 0; i < els.length; i++){
    var el = els[i];
    if(!isVisible(el)) continue;
    var isControl = el.matches(interactive);
    var isIcon = el.tagName.toLowerCase() === 'svg' || !!el.ownerSVGElement;
    if(!isControl && !isIcon){ skipped_decorative++; continue; }
    var cs = getComputedStyle(el);
    var bg = effectiveBackground(el.parentElement || el);
    if(!bg.resolved){ unresolved++; continue; }
    var record = function(kind, value, widthPx){
      var c = parseColour(value);
      if(!c || c.a === 0) return;
      var solid = composite(c, bg.colour);
      out.push({
        path: pathOf(el), kind: kind,
        colour: hex(solid), background_hex: hex(bg.colour),
        thickness_px: widthPx,
        ratio: Math.round(ratio(solid, bg.colour) * 100) / 100
      });
    };
    var bw = parseFloat(cs.borderTopWidth) || 0;
    if(isControl && bw >= 1 && cs.borderTopStyle !== 'none'){
      record('control-border', cs.borderTopColor, bw);
    }
    if(isIcon && cs.stroke && cs.stroke !== 'none'){
      record('icon-stroke', cs.stroke, parseFloat(cs.strokeWidth) || 1);
    }
  }
  return {
    population: 'interactive control borders + svg icon strokes (WCAG 1.4.11 scope)',
    measured: out,
    unresolved_backgrounds: unresolved,
    skipped_decorative: skipped_decorative
  };
})()
"""
)


# ------------------------------------------------------------------ Core 6

#: Installed with `page.add_init_script`, so it runs BEFORE the surface's own
#: inline scripts. It captures the poller's `setInterval(tick, 20000)`
#: registration instead of scheduling it: the only body-swap in a Core 6 run
#: is then the one the test forces, which is what makes the measurement
#: deterministic rather than a race against a 20-second timer.
SWAP_CAPTURE_INIT_JS = r"""
(() => {
  var real = window.setInterval.bind(window);
  window.__wtCapturedIntervals = [];
  window.setInterval = function(fn, ms){
    window.__wtCapturedIntervals.push({fn: fn, ms: ms});
    return -1;
  };
  window.__wtRealSetInterval = real;
})();
"""

#: Drop a sentinel into the body before a swap. A whole-body `innerHTML`
#: replacement destroys it, so its ABSENCE afterwards is the proof the swap
#: actually happened. Without this the good half passes vacuously whenever the
#: forced fetch quietly fails -- the poller swallows every error by design
#: (`.catch(function(){ /* silent */ })`), so "nothing changed" and "nothing
#: was swapped" look identical from the outside.
SWAP_SENTINEL_JS = r"""
(() => {
  var el = document.createElement('div');
  el.id = 'wt-swap-sentinel';
  el.setAttribute('hidden', 'hidden');
  document.body.appendChild(el);
  return true;
})()
"""

SWAP_SENTINEL_PRESENT_JS = "!!document.getElementById('wt-swap-sentinel')"

#: Tag every live region present BEFORE the swap. A whole-body innerHTML
#: replacement destroys the tagged nodes, so counting survivors afterwards is
#: a direct, numeric answer to "was a pending announcement destroyed?".
SWAP_MARK_LIVE_REGIONS_JS = r"""
(() => {
  var sel = '[aria-live], [role=status], [role=alert], [role=log]';
  var found = document.querySelectorAll(sel);
  var marked = [];
  for(var i = 0; i < found.length; i++){
    found[i].setAttribute('data-wt-preswap', String(i));
    marked.push({
      index: i,
      role: found[i].getAttribute('role') || '',
      aria_live: found[i].getAttribute('aria-live') || '',
      text: (found[i].textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)
    });
  }
  return marked;
})()
"""

#: The post/pre-swap DOM snapshot Conformance 3 asks for.
#:
#: `<details>` are keyed by ORDINAL + class signature, not by id: measured on
#: the shipped surface, NO `<details>` on L0, L1 or L2 carries an id at all
#: (help popover, activity feed, actions drawer -- all id-less), and
#: `restoreState` only ever re-opens `details[id]`. Keying this snapshot by id
#: would therefore compare two empty lists and report survival for a mechanism
#: that has no targets. `open_details_by_id` is kept alongside so the artifact
#: shows both readings.
SWAP_STATE_JS = r"""
(() => {
  var btn = document.getElementById('refreshToggle');
  var open = [], byId = [];
  var all = document.querySelectorAll('details');
  for(var i = 0; i < all.length; i++){
    var d = all[i];
    var sig = i + ':' + (typeof d.className === 'string' ? d.className.trim() : '');
    if(d.open){ open.push(sig); if(d.id) byId.push(d.id); }
  }
  var live = document.querySelectorAll('[aria-live], [role=status], [role=alert], [role=log]');
  return {
    scroll_y: Math.round(window.scrollY),
    details_total: all.length,
    details_with_id: document.querySelectorAll('details[id]').length,
    open_details: open.sort(),
    open_details_by_id: byId.sort(),
    pause_flag: !!window.__wtRefreshPaused,
    pause_control_pressed: btn ? btn.getAttribute('aria-pressed') : null,
    live_region_count: live.length,
    surviving_marked_live_regions: document.querySelectorAll('[data-wt-preswap]').length
  };
})()
"""

#: Force ONE tick of the surface's own poller.
#:
#: The pause guard is lifted for exactly the synchronous entry of `tick()` and
#: restored on the very next statement -- before the fetch it starts can
#: resolve, and therefore before the swap it performs. What is bypassed is the
#: SCHEDULING guard ("a paused page should not poll"); what is measured is the
#: page's state at the moment the swap lands, which is still `paused`. Doing
#: it any other way would mean either never swapping while paused (measuring
#: nothing) or clearing the very flag under test (measuring a lie).
SWAP_FORCE_TICK_JS = r"""
(() => {
  var ticks = window.__wtCapturedIntervals || [];
  var chosen = null;
  for(var i = 0; i < ticks.length; i++){
    if(ticks[i].ms >= 1000){ chosen = ticks[i]; break; }
  }
  var q = document.getElementById('q');
  var guards = {
    document_hidden: document.hidden,
    visibility_state: document.visibilityState,
    active_element: document.activeElement ? document.activeElement.tagName : null,
    q_value: q ? q.value : null,
    paused_flag: !!window.__wtRefreshPaused
  };
  if(!chosen) return {forced: false, reason: 'no poller interval was registered',
                      guards: guards,
                      captured: ticks.map(function(t){ return t.ms; })};
  var wasPaused = window.__wtRefreshPaused;
  window.__wtRefreshPaused = false;
  try { chosen.fn(); } finally { window.__wtRefreshPaused = wasPaused; }
  return {forced: true, interval_ms: chosen.ms, guard_restored_to: !!wasPaused,
          guards: guards};
})()
"""

#: The BAD half of Conformance 3: "a whole-body innerHTML replacement that
#: recreates the region". A naive swap with no capture/restore at all -- which
#: is what the surface would do if `captureState`/`restoreState` were deleted.
SWAP_NAIVE_REPLACEMENT_JS = r"""
(async () => {
  var u = new URL(location.href);
  var res = await fetch(u.pathname + (u.search || ''),
                        {credentials: 'same-origin',
                         headers: {'X-Requested-With': 'wt-auto-refresh'}});
  var html = await res.text();
  var doc = new DOMParser().parseFromString(html, 'text/html');
  document.body.innerHTML = doc.body.innerHTML;
  return true;
})()
"""

#: The same naive replacement, but with a forced layout flush between
#: emptying the body and refilling it.
#:
#: Why a second variant exists, measured rather than assumed: on chromium 148
#: a SYNCHRONOUS `body.innerHTML = html` preserves `window.scrollY` all by
#: itself -- the document never gets a chance to collapse, so the browser
#: never clamps the offset. The contract's literal bad half therefore does not
#: discriminate on the scroll half of Core 6 at all. Clearing the body,
#: reading `offsetHeight` to force layout, and only then refilling is the same
#: whole-body replacement written the other common way, and it DOES lose the
#: offset -- which is what proves the good half's scroll assertion can see a
#: loss when there is one.
SWAP_NAIVE_REPLACEMENT_WITH_REFLOW_JS = r"""
(async () => {
  var u = new URL(location.href);
  var res = await fetch(u.pathname + (u.search || ''),
                        {credentials: 'same-origin',
                         headers: {'X-Requested-With': 'wt-auto-refresh'}});
  var html = await res.text();
  var doc = new DOMParser().parseFromString(html, 'text/html');
  document.body.innerHTML = '';
  void document.body.offsetHeight;   /* force layout: the document collapses */
  document.body.innerHTML = doc.body.innerHTML;
  return true;
})()
"""

#: The BAD half of Conformance 1: "the retired-palette region reinstated -- a
#: hardcoded amber outside the token set". `#D9A253` is the real specimen
#: still in the tree at `webtrust.py`'s page-local `<style>` block (`--amber`),
#: not an invented colour.
INJECT_RETIRED_PALETTE_JS = r"""
(() => {
  var el = document.createElement('div');
  el.id = 'wt-bad-half-retired-palette';
  el.textContent = 'retired palette region';
  el.setAttribute('style', 'position:fixed;top:0;left:0;width:220px;height:80px;' +
                           'z-index:99999;background:#D9A253;color:#0D0D0C');
  document.body.appendChild(el);
  return true;
})()
"""

#: The BAD half GOAL item 3 names: one alarm chip on an otherwise calm page.
#: Painted with the token itself (`var(--alarm)`), so it is the contract's own
#: hue rather than a lookalike.
INJECT_ALARM_CHIP_JS = r"""
(() => {
  var el = document.createElement('div');
  el.id = 'wt-bad-half-alarm-chip';
  el.textContent = 'STALE';
  el.setAttribute('style', 'position:fixed;top:0;right:0;width:180px;height:60px;' +
                           'z-index:99999;background:var(--alarm);color:#101010');
  document.body.appendChild(el);
  return true;
})()
"""

#: The BAD half of Conformance 4, overflow arm: "a fixture with a fixed-width
#: element wider than 430px emits `scrollWidth > clientWidth`".
INJECT_WIDE_ELEMENT_JS = r"""
(() => {
  var el = document.createElement('div');
  el.id = 'wt-bad-half-wide-element';
  el.setAttribute('style', 'width:900px;height:12px;background:transparent');
  document.body.appendChild(el);
  return true;
})()
"""

#: The BAD half of Conformance 4, contrast arm: "a fixture using the recorded
#: 4.27:1 ink pair emits a contrast number below the floor".
#:
#: LITERAL colours, not the live tokens -- and that is the whole point. This
#: injection used to paint the live `--ink-quiet` ink on the live `--ground`,
#: which WAS the pair OSV1-009 recorded at 4.27:1. The contrast lane then
#: closed OSV1-009 by moving `--ink-quiet` (#7c8ba0 -> #596473), and the same
#: injection started measuring 5.36:1 in light -- ABOVE the floor. A bad half
#: that stops naming a defect the moment the product is fixed was never naming
#: the defect, it was naming the product; Freeze 4 asks for a fixture that
#: FAILS the check by construction.
#:
#: `#9aa3b2` on `#eef2fb` is 2.27:1 by the ledger's own luminance math
#: (`_support.contrast_ratio`) -- below the 4.5:1 text floor in either theme,
#: whatever the token set does next.
#:
#: `#wt-bad-half-contrast-control` is the CONTROL, injected in the same act:
#: `#1b2430` on the same ground is 13.96:1. A probe that reported everything
#: below the floor would satisfy the assertion above and fail this one, so the
#: two together are what make the number a measurement rather than a foregone
#: conclusion. (That control used to be carried by measuring the SAME token
#: pair in dark, which only worked while the pair was theme-dependent.)
INJECT_BELOW_FLOOR_PAIR_JS = r"""
(() => {
  var add = function(id, text, css){
    var el = document.createElement('p');
    el.id = id;
    el.textContent = text;
    el.setAttribute('style', 'position:fixed;left:0;z-index:99999;font-size:14px;' + css);
    document.body.appendChild(el);
  };
  add('wt-bad-half-low-contrast', 'literal below-floor ink pair',
      'bottom:0;color:#9aa3b2;background:#eef2fb');
  add('wt-bad-half-contrast-control', 'literal above-floor control pair',
      'bottom:26px;color:#1b2430;background:#eef2fb');
  return true;
})()
"""


# ------------------------------------------------------- pure-Python re-checks


def below_text_floor(measurement: dict[str, Any], *, floor: float = TEXT_CONTRAST_FLOOR) -> list:
    """Every scored text entry under the floor, worst first."""
    scored = measurement["scored"]
    bad = [e for e in scored if float(e["ratio"]) < floor]
    return sorted(bad, key=lambda e: float(e["ratio"]))


def undersized_controls(
    measurement: dict[str, Any], *, floor: float = TARGET_SIZE_FLOOR_PX
) -> list:
    """Every non-inline interactive target whose smaller side is under the floor."""
    controls = [t for t in measurement["targets"] if t["kind"] == "control"]
    bad = [t for t in controls if min(float(t["width"]), float(t["height"])) < floor]
    return sorted(bad, key=lambda t: min(float(t["width"]), float(t["height"])))


def running_animations(measurement: dict[str, Any], *, epsilon: float = MOTION_EPSILON_MS) -> list:
    """Animations that actually run under the reduced-motion preference."""
    return [
        a
        for a in measurement["animations"]
        if a["state"] == "running" and float(a["duration_ms"]) > epsilon
    ]


def below_non_text_floor(
    measurement: dict[str, Any], *, floor: float = NON_TEXT_CONTRAST_FLOOR
) -> list:
    return sorted(
        (e for e in measurement["measured"] if float(e["ratio"]) < floor),
        key=lambda e: float(e["ratio"]),
    )


def summarise(entries: list, keys: tuple[str, ...], limit: int = 6) -> str:
    """A compact, quotable failure body -- the worst `limit` offenders."""
    return "\n".join(
        "    " + ", ".join(f"{k}={e.get(k)!r}" for k in keys) for e in entries[:limit]
    ) + (f"\n    ... and {len(entries) - limit} more" if len(entries) > limit else "")
