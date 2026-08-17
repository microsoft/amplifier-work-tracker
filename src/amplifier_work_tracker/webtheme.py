"""Visual system for the web dashboard -- ported from the J-editorial-dark
design candidate (`.amplifier/design-gauntlet/wt-dashboard-v2/candidates/
J-editorial-dark/`, MANIFEST.md), which won a 12-candidate bake-off and
passed independent visual review with a verdict of SHIP.

This module owns everything about HOW something looks: fonts, palette,
CSS, chrome (top bar, status bar, search field), and the small rendering
helpers (age/duration formatting, the age bar + its ruler, state markers)
that turn real numbers into the design's vocabulary. `webapp.py` owns
WHAT is shown (routes, data, forms); this module owns HOW it reads.

THE ONE TYPOGRAPHIC RULE (carried over verbatim from the reference)
  Bodoni Moda (didone serif) is the voice of TIME. Every age, every
  duration -- "how long has this been sitting there" -- is set in the
  serif. Archivo (neo-grotesque) is the voice of everything else: names,
  counts, ids, statuses, prose, chrome.

THE ENCODING
  Age is position, size and colour. Count is a small dim numeral. Nothing
  is sized by how many items it holds. The oldest-unclaimed-item AGE is
  the hero of the dashboard, never a count -- see `webapp.py`'s dashboard
  route for why (a count-encoded dashboard makes the biggest queue the
  biggest object on screen, which trains the eye to look at volume
  instead of neglect).

DEVIATIONS FROM THE REFERENCE, DELIBERATE, EACH WITH A REASON
  - No persistent left-rail sidebar. The reference's rail assumed a fixed
    5-section app (Overview/Queues/Items/Agents/History); this app's real
    routes are `/`, `/projects/{name}`, `/projects/{name}/items/{id}` --
    a dynamic set of N projects, not 5 fixed sections. A fixed-width rail
    with no real content to put in it would be decoration, not IA. The
    top bar (brand + breadcrumb + identity/logout) and bottom status bar
    carry the same chrome weight instead.
  - No dedicated "05-alarm" full-page state. The reference's alarm page
    was a fixed mockup of "3 agents holding work + 1 blocked + 1 broken
    queue" -- a specific narrative, not a general mechanism. The same
    escalation vocabulary (crimson, held-duration clocks) is available to
    any real page via `state_html`/`clock_html`, applied where real data
    warrants it (e.g. a queue's own held items), without inventing a
    page for a scenario that may never occur in this exact shape.
  - The age BAR's scale is DYNAMIC (max = the real current oldest
    unclaimed age across the whole workspace), not a fixed 9-day axis.
    Real workspaces are not bounded to 9 days; hardcoding that number
    would silently misrepresent a worse day as identical to today's.
    `axis_and_bar` derives both the ruler's printed numerals and every
    row's bar length from the SAME scale value, computed once, so they
    can never drift apart the way the reference's independently-tuned
    CSS gradient and absolutely-positioned numerals did (see its own
    MANIFEST for the "axis labels sit slightly left of the bars" defect
    this construction makes structurally impossible: one shared x-position
    formula feeds both the tick mark and its numeral).
  - Age *colour* bands (a0..a3) stay on FIXED real-world day thresholds
    (<=1d / <=3d / <=6d / >6d), not rescaled to the current max. "This
    has waited a week" should mean the same colour on a calm day and a
    bad one; only the bar's LENGTH is relative to today's worst case.
"""

from __future__ import annotations

import base64
import html
import pathlib

# ---------------------------------------------------------------------------
# Fonts -- embedded as base64 data URIs, exactly like the reference. No CDN,
# no network fetch at view time: this process may serve a LAN with no
# internet egress at all (see webauth.py's module docstring -- explicitly a
# multi-person LAN service). Read and encoded ONCE at import time.
# ---------------------------------------------------------------------------

_FONTS_DIR = pathlib.Path(__file__).parent / "webfonts"


def _font_b64(name: str) -> str:
    return base64.b64encode((_FONTS_DIR / name).read_bytes()).decode()


_FONT_FACE_CSS = (
    "@font-face{font-family:'Bodoni Moda';font-style:normal;font-weight:400 900;"
    "font-display:block;src:url(data:font/woff2;base64,"
    + _font_b64("BodoniModa-var.woff2")
    + ") format('woff2');}\n"
    "@font-face{font-family:'Archivo';font-style:normal;font-weight:100 900;"
    "font-display:block;src:url(data:font/woff2;base64,"
    + _font_b64("Archivo-var.woff2")
    + ") format('woff2');}\n"
)

# ---------------------------------------------------------------------------
# CSS -- ported from the reference `shell.py`'s CSS, trimmed to what this
# app's real routes use (no fixed rail, no alarm-band, no clock faces) and
# extended with a form vocabulary the reference never needed (it was a
# read-mostly mockup; this app writes).
# ---------------------------------------------------------------------------

CSS = r"""
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root{
  --ground:#0D0D0C;
  --raise:#151513;    /* the only lighter surface text ever sits on (hovered
                         rows, fields, chips, content blocks) -- every text
                         token below is checked against BOTH --ground and this */
  --sink:#070706;

  /* NEUTRAL TEXT RAMP -- four steps, each a real measured contrast. Even the
     quietest step (--dim) clears WCAG AA (4.5:1) with margin against --ground
     AND against a hovered row (--raise), at the small sizes this UI uses. No
     content-bearing text ever drops below this floor. */
  --ink:#F2EEE6;      /* 16.80:1  -- primary text */
  --mid:#A6A199;      /*  7.57:1  -- secondary: chrome, labels, holders, ids */
  --quiet:#9C978F;    /*  6.70:1  -- tertiary: prose, footnotes, counts */
  --dim:#928E85;      /*  5.95:1  (5.60:1 on --raise) -- quietest legible step.
                         Lifted off the previous 5.29/4.98 floor so small print
                         (resolved status, row ids, axis numerals) reads as
                         quiet, never as functionally-invisible. */

  /* SIGNAL COLOURS -- exactly three, each with ONE job, never decorative.
     The accent (--amber) is spent on ATTENTION only; good news stays neutral
     (--live); a broken queue gets its own unmistakable hue (--alarm). */
  --amber:#D9A253;    /*  8.56:1  -- ATTENTION, and nothing else: accumulating
                         time / the one thing to look at (hero age, the a3 stale
                         band, oldest-unclaimed emphasis) and the interactive
                         accent that confirms it (hover, focus, caret, selection).
                         NOT good news. NOT alarm. This is the single referent. */
  --alarm:#FF6A45;    /*  6.85:1  -- BROKEN: a project the backend cannot read.
                         A distinct hot hue, brighter and more saturated than
                         both amber (warm gold) and crimson (soft coral), so a
                         broken queue is unmissable and never read as ordinary
                         attention or item-level escalation. Render lanes apply
                         it via `state_html("alarm", ...)` / `.state.alarm`. */
  --crimson:#E0655A;  /*  5.72:1  -- ESCALATION: a blocked item, a destructive
                         action. Item-level and reversible-with-care, distinct
                         from a whole-project --alarm. Never decorative. */
  --live:#A6A199;     /*  neutral (== --mid) -- "healthy / live" is GOOD NEWS and
                         is kept QUIET on purpose: the breathing status dot, no
                         accent. Good news must never spend the one accent. */

  --rule:#1F1F1D;
  --rule-hi:#333330;
  --link-underline:#333330;  /* the resting affordance for INLINE prose links --
                                see "AFFORDANCE GRAMMAR" note below the tokens */
  --serif:'Bodoni Moda',Georgia,serif;
  --sans:'Archivo','Helvetica Neue',sans-serif;
  --mono:ui-monospace,'SFMono-Regular','JetBrains Mono',Menlo,Consolas,'Liberation Mono',monospace;
  --pad:52px;
  --u:44px;           /* WCAG target minimum */
  --hero-opsz:48;
  --beat-h:50px;
  --fig-size:236px;   /* hero age figure size -- a token so density classes can
                         shrink the heaviest element without restructuring it */
  --fig-unit:32px;    /* the hero figure's unit label (DAYS/HOURS/...) */
}

/* -- AFFORDANCE GRAMMAR (one documented convention) ----------------------
   Three signals of "clickable" were in use (a trailing chevron, bold-amber
   text, and a lone underline). Consolidated to ONE rule, enforced by the
   classes below:

     1. A link's RESTING affordance is STRUCTURAL, and there are two forms,
        one per context -- never a colour:
          - ROW / navigational links (a whole row or cell that navigates):
            a trailing chevron  ">"  (`.ti a`, `td.link-cell > a`, `.attrib`).
          - INLINE prose links (a link inside a value or sentence):
            an underline in --link-underline (`.prose-link`, `.kv .v a`,
            `.links-list a`, `a.what`).
     2. --amber is NEVER a resting link colour. Amber appears on a link ONLY
        on :hover / :focus, as the universal "interactive" confirmation.
        (Amber text at rest means ATTENTION -- see the token -- not "click me".)
   New inline links should use `.prose-link`; the older selectors above are
   kept as aliases so existing markup keeps its single underline affordance. */
html{background:var(--ground)}
body{
  background:var(--ground);color:var(--ink);
  font-family:var(--sans);font-size:14px;line-height:1.5;font-weight:400;
  font-variant-numeric:tabular-nums;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
  padding-bottom:46px;
}
::selection{background:var(--amber);color:#000}
a{color:inherit}
:focus-visible{outline:2px solid var(--amber);outline-offset:3px}

/* -- top bar ---------------------------------------------------------- */
.top{
  height:74px;display:flex;align-items:center;
  padding:0 var(--pad);border-bottom:1px solid var(--rule);gap:20px;
  position:sticky;top:0;background:var(--ground);z-index:30;flex-wrap:wrap;
}
.top .brand{font-family:var(--serif);font-size:19px;font-weight:600;
  letter-spacing:.005em;color:var(--ink);text-decoration:none;
  display:flex;align-items:center;gap:9px}
.top .brand .bm{width:7px;height:7px;background:var(--amber);flex:0 0 auto}
.top h1{font-family:var(--sans);font-size:21px;font-weight:500;
  letter-spacing:-.012em;color:var(--ink);line-height:1.1}
.top .crumb{font-family:var(--sans);font-size:11px;font-weight:500;
  letter-spacing:.14em;text-transform:uppercase;color:var(--dim);
  display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.top .crumb a{text-decoration:none;color:var(--mid);display:inline-flex;
  align-items:center;min-height:var(--u)}
.top .crumb a:hover{color:var(--amber)}
.top .sp{flex:1}
.top .identity{font-family:var(--sans);font-size:11.5px;color:var(--dim);
  letter-spacing:.02em;display:flex;align-items:center;gap:9px;white-space:nowrap}
.top .identity a{color:var(--mid);text-decoration:none}
.top .identity a:hover{color:var(--amber)}
.dot{width:6px;height:6px;border-radius:50%;flex:0 0 6px;display:inline-block}
/* the live/"healthy" pulse is GOOD NEWS -> neutral (--live), never the accent.
   "live" is carried by the breathing motion + the word beside it, not colour. */
.dot.on{background:var(--live);animation:breathe 4s ease-in-out infinite}
@keyframes breathe{0%,100%{opacity:1}50%{opacity:.35}}
/* a quiet, one-shot confirmation that an auto-refresh tick actually landed --
   see webtheme.py's `auto_refresh_js`. Automatically neutralised by the
   `prefers-reduced-motion` block below (it resets EVERY animation's duration
   to ~0), so this needs no separate reduced-motion rule of its own. */
.dot.refreshed{animation:dotpulse .6s ease}
@keyframes dotpulse{0%{transform:scale(1)}40%{transform:scale(1.7)}100%{transform:scale(1)}}

/* -- content ------------------------------------------------------------ */
.wrap{padding:0 var(--pad);max-width:1440px;margin:0 auto}
.sec{padding:40px 0}
.sec.tight{padding:18px 0}
.hr{border-top:1px solid var(--rule)}
.bleed{margin:0 calc(-1 * var(--pad))}

.eyebrow{font-family:var(--sans);font-size:10px;font-weight:500;
  letter-spacing:.26em;text-transform:uppercase;color:var(--mid);line-height:1.5}
.eyebrow.am{color:var(--amber)}
.subtle{font-family:var(--sans);font-size:11.5px;color:var(--quiet);
  letter-spacing:.015em;line-height:1.6}

/* -- DENSITY -- compact affordances for sparse projects -------------------
   A 2-item queue should not wear the same heavy hero/stats chrome as a
   264-item one (~80% chrome/air on a tiny queue). This is the MECHANISM only:
   a render lane adds `compact` to a scope (the content `.wrap`, or a single
   `.sec`) and the heavy elements inside shrink; it adds `compact-hide` to a
   specific block that carries no signal for a tiny queue (a 2-tick histogram,
   an all-zero ledger). Nothing here decides WHEN to compact -- that is the
   render lane's call from the real item count. Heavy layout re-architecture
   (fold/scroll) is deliberately out of scope; these are additive knobs. */
.compact{--fig-size:118px;--fig-unit:22px}
.compact .sec{padding:22px 0}
.compact .sec.tight{padding:12px 0}
.compact .sec.heroic{padding:18px 0 22px}
.compact .figrow{margin:14px 0 0}
.compact .hero{gap:32px}
.compact .context{gap:32px}
.compact-hide{display:none}

/* -- HERO -- age is the biggest thing on the screen --------------------- */
.hero{display:flex;align-items:flex-end;gap:54px;flex-wrap:wrap}
.hero .lead{min-width:0;flex:0 0 auto}
.figrow{display:flex;align-items:baseline;gap:12px;margin:26px 0 0}
.fig{
  font-family:var(--serif);font-weight:500;color:var(--amber);
  font-size:var(--fig-size);line-height:.78;letter-spacing:-.035em;
  font-variation-settings:"opsz" var(--hero-opsz);display:block;
}
.fig.sm{--fig-size:120px}
.fig.none{color:var(--mid)}
.figunit{font-family:var(--sans);font-weight:600;font-size:var(--fig-unit);
  letter-spacing:.2em;color:var(--ink);text-transform:uppercase;line-height:1}
.figunit.am{color:var(--amber)}
.hero.solo{display:block}
.sec.heroic{padding:36px 0 40px}
.hero.solo .figrow{margin:20px 0 0}
.attrib{display:inline-flex;align-items:center;flex-wrap:wrap;gap:0 10px;
  min-height:var(--u);margin-top:14px;text-decoration:none;
  font-family:var(--sans);font-size:12px;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;color:var(--mid)}
.attrib .id{color:var(--dim);font-weight:400;letter-spacing:.04em}
.attrib .sep{color:var(--dim);font-weight:400}
.attrib .since{font-weight:400;letter-spacing:.06em;color:var(--quiet)}
.attrib::after{content:"\203A";font-weight:700;font-size:14px;
  letter-spacing:0;text-transform:none;color:var(--mid)}
a.attrib:hover{color:var(--amber)}
a.attrib:hover .since{color:var(--amber)}
a.attrib:hover::after{color:var(--amber)}

/* the hero's own pointer to the oldest item (project page): same "prose
   link" grammar as `.kv .v a` / `.links-list a` below -- an inline title,
   not a full row, so it gets the underline treatment rather than the row
   chevron. Made explicit rather than left to the browser's unstyled
   default underline, which happened to look right by accident. */
a.what{color:inherit;text-decoration:underline;text-decoration-color:var(--link-underline)}
a.what:hover{color:var(--amber)}

/* -- HEARTBEAT -- ready items as ticks, placed by age ------------------- */
.beat{width:100%}
.beat .bhead{display:flex;justify-content:space-between;align-items:baseline;
  gap:24px;margin-bottom:12px;flex-wrap:wrap}
.ticks{display:flex;align-items:flex-end;gap:2px;
  height:calc(var(--beat-h) + 1px);
  border-bottom:1px solid var(--rule);padding-bottom:0}
.tick{flex:1 1 auto;min-width:1px;background:var(--rule-hi);border-radius:0}
.tick.t0{background:#262624}
.tick.t1{background:#31312E}
.tick.t2{background:#4A463F}
.tick.t3{background:#8A6B33}
.scale{display:flex;justify-content:space-between;margin-top:8px}
.scale span{font-family:var(--sans);font-size:10px;font-weight:500;
  letter-spacing:.12em;color:var(--dim);text-transform:uppercase}
.beat .legend{display:flex;gap:34px;margin-top:0;flex-wrap:wrap;
  padding-right:2px;align-items:baseline}
.beat .legend div{display:flex;align-items:baseline;gap:8px}
.beat .legend .n{font-family:var(--sans);font-size:17px;font-weight:500;
  color:var(--mid);line-height:1;letter-spacing:.005em}
.beat .legend .n.am{color:var(--amber)}
.beat .legend .l{font-family:var(--sans);font-size:10px;font-weight:500;
  letter-spacing:.16em;text-transform:uppercase;color:var(--dim);white-space:nowrap}
.beat .legend .sw{display:inline-block;width:3px;flex:0 0 3px}
.beat .legend .sw.s0{height:7px;background:#262624}
.beat .legend .sw.s3{height:19px;background:#8A6B33}

/* -- CONTEXT BAND -- the histogram, and the counts that qualify it ------ */
.context{display:flex;align-items:flex-start;gap:54px;flex-wrap:wrap}
.context > .beat{flex:1 1 380px;min-width:280px}
.context .ledgercol{flex:1 1 320px;display:flex;flex-direction:column;min-width:280px}
.context .ledger{display:flex;gap:0;flex-wrap:wrap}
.grp{flex:1 1 0;padding-right:26px;margin-right:26px;position:relative;min-width:140px}
.grp::after{content:'';position:absolute;right:0;top:2px;bottom:4px;width:1px;
  background:var(--rule)}
.grp:last-child{margin-right:0;padding-right:0}
.grp:last-child::after{display:none}
.grp .glbl{font-family:var(--sans);font-size:10px;font-weight:600;
  letter-spacing:.2em;text-transform:uppercase;color:var(--mid);display:block;
  margin-bottom:15px;white-space:nowrap}
.stat{display:flex;align-items:baseline;gap:10px}
.stat + .stat{margin-top:14px}
.stat .v{font-family:var(--sans);font-size:17px;font-weight:500;color:var(--ink);
  line-height:1;letter-spacing:.005em;flex:0 0 auto;min-width:34px}
.stat .v .per{font-size:11px;font-weight:600;color:var(--dim);
  letter-spacing:.08em;margin-left:2px;text-transform:uppercase}
.stat .k{font-family:var(--sans);font-size:10px;font-weight:600;
  letter-spacing:.15em;text-transform:uppercase;color:var(--dim);white-space:nowrap}

/* -- tallies -- counts are SMALL and DIM. deliberately. ------------------ */
.tallies{display:flex;gap:0;flex-wrap:wrap}
.tally{padding:0 34px 0 0;margin-right:34px;position:relative}
.tally::after{content:'';position:absolute;right:0;top:3px;bottom:5px;
  width:1px;background:var(--rule)}
.tally:last-child{margin-right:0;padding-right:0}
.tally:last-child::after{display:none}
.tally .v{font-family:var(--sans);font-size:19px;font-weight:500;
  color:var(--mid);line-height:1.2;letter-spacing:.005em}
.tally .v.ink{color:var(--ink)}
.tally .k{font-family:var(--sans);font-size:10px;font-weight:600;
  letter-spacing:.17em;text-transform:uppercase;color:var(--dim);
  display:block;margin-top:5px}

/* -- A-LEDGER: the workspace overview's ready-count hero + composition ---
   bar -- see webapp.py's dashboard route module comment for the full
   rationale. Three new fills only (--st-ready/--st-deferred/--st-resolved);
   HELD and BLOCKED deliberately reuse --amber/--crimson verbatim rather than
   minting parallel hues, so a queue's composition bar never disagrees in
   colour with the same state's marker elsewhere in this app (`.state.warnv`
   /`.st-blkd`). A zero-count state renders as a 3px --st-empty seam, not as
   nothing -- the "alarm lamp present and switched off" convention -- one
   shared dim tone for every empty slot rather than five bespoke unlit hues
   (ruthless simplicity: the functional requirement is "visible, not
   absent", not "each state has its own unlit shade").

   --st-empty is its OWN token, not a reuse of --rule-hi (the app's generic
   hairline-divider colour): --rule-hi (#333330) sits only ~20 RGB units
   from --st-resolved (#4A463F) and --st-deferred (#5C574E) -- the two
   fills a seam is most often rendered directly beside, since HELD/BLOCKED/
   DEFERRED are commonly all-zero at once and their three seams land in a
   contiguous run right before RESOLVED. At that low a delta the seam reads
   as part of the neighbouring RESOLVED segment instead of its own dimmed
   marker -- measured directly off a real render, not eyeballed. --st-empty
   is lighter than every state fill it can possibly sit beside (ready,
   held/amber, blocked/crimson, deferred, resolved) so the seam always
   reads as a distinct, dimmed sliver rather than disappearing into
   whichever real colour happens to be next to it. */
:root{
  --st-ready:#E8E2D6;     /* warm parchment -- neutral backlog, not amber */
  --st-deferred:#5C574E;
  --st-resolved:#4A463F;
  --st-empty:#928E85;     /* == --dim (5.95:1 vs --ground) -- deliberately
                             reused rather than a new arbitrary hex, since
                             --dim is already the app's measured "quietest
                             legible step"; see the comment above for why
                             this can't just be --rule-hi. */
  --fig-size-ledger:62px; /* the ready-count hero figure -- 3.8x smaller
                             than --fig-size (236px), a deliberate demotion:
                             ready-COUNT is the hero now, not unclaimed AGE */
}

/* the hero, dialled down: same .hero/.figrow/.fig/.figunit vocabulary as
   the age hero, at the smaller ledger size, with a serif under-line and a
   right-aligned trio of quiet secondary readings that never compete with
   it (`.hstats`, pushed right via margin-left:auto, own font scale). */
.fig.ledger{font-size:var(--fig-size-ledger);color:var(--ink)}
.hero .under{font-family:var(--sans);font-size:11.5px;color:var(--quiet);
  margin-top:14px;letter-spacing:.015em;line-height:1.6}
.hero .under b{color:var(--ink);font-weight:600}
.hstats{display:flex;gap:44px;margin-left:auto;padding-bottom:2px;
  flex-wrap:wrap;align-self:flex-end}
.hstats .s{min-width:0}
.hstats .s .k{font-family:var(--sans);font-size:9.5px;font-weight:600;
  letter-spacing:.18em;text-transform:uppercase;color:var(--dim);
  display:block;margin-bottom:9px;white-space:nowrap}
.hstats .s .n{font-family:var(--serif);font-size:27px;font-weight:500;
  line-height:.9;letter-spacing:-.015em;color:var(--ink);display:block}
.hstats .s .n.am{color:var(--amber)}
.hstats .s .sub{font-family:var(--sans);font-size:10.5px;color:var(--dim);
  margin-top:8px;display:block;line-height:1.45;max-width:150px}
.hstats .s .sub a{color:inherit;text-decoration:underline;
  text-decoration-color:var(--link-underline)}
.hstats .s .sub a:hover{color:var(--amber)}

/* the state bar itself -- shared by the full-width workspace composition
   and every table row's mini composition, at different heights only. */
.sbar{display:flex;width:100%;background:#141412;overflow:hidden;
  border-radius:2px}
.sbar i{display:block;height:100%}
.sbar .seam{width:3px;flex:0 0 3px;background:var(--ground);position:relative}
.sbar .seam::after{content:"";position:absolute;inset:0;background:var(--st-empty)}

/* "workspace by state" -- the full-width centrepiece. */
.comp .chead{display:flex;align-items:baseline;gap:16px;margin-bottom:13px;
  flex-wrap:wrap}
.comp .chead .rt{margin-left:auto;font-family:var(--sans);font-size:11px;
  color:var(--quiet);letter-spacing:.02em}
.comp .chead .rt b{font-family:var(--serif);font-size:15px;color:var(--ink);
  font-weight:500}
.comp .sbar{height:40px}
.comp .legend{display:flex;flex-wrap:wrap;gap:34px;margin-top:11px}
.comp .legend .li{display:flex;align-items:baseline;gap:11px}
.comp .legend .sw{width:9px;height:9px;flex:0 0 9px;transform:translateY(-1px);
  border-radius:1px}
.comp .legend .n{font-family:var(--serif);font-size:17px;font-weight:500;
  color:var(--ink)}
.comp .legend .n.z{color:var(--dim)}
.comp .legend .l{font-family:var(--sans);font-size:10px;font-weight:500;
  letter-spacing:.16em;text-transform:uppercase;color:var(--dim)}

/* throughput -- sits in `.context .ledgercol` beside the (unchanged)
   ready-queue-by-age heartbeat, reusing that flex split verbatim. */
.thru .bh{display:flex;align-items:baseline;gap:12px;margin-bottom:14px}
.trow{display:flex;align-items:center;gap:12px;margin-bottom:9px}
.trow .tn{font-family:var(--serif);font-size:22px;font-weight:500;
  color:var(--ink);width:38px;flex:0 0 38px;text-align:right;line-height:1}
.trow .tl{font-family:var(--sans);font-size:10px;font-weight:500;
  letter-spacing:.15em;text-transform:uppercase;color:var(--dim);
  width:74px;flex:0 0 74px}
.trow .tb{height:11px;background:var(--st-ready);display:block;border-radius:1px}
.trow.prev .tn{color:var(--mid)}
.trow.prev .tb{background:var(--st-resolved)}
.thru .tfoot{font-family:var(--sans);font-size:11px;color:var(--quiet);
  margin-top:13px;line-height:1.6}
.thru .tfoot b{color:var(--amber);font-weight:600}

/* the per-project queue table's mini composition column. */
.tbl td.mb{padding:0 22px 0 0}
.tbl td.mb .sbar{height:9px}
.tbl td.age.z{font-family:var(--sans);font-size:12px;color:var(--dim)}

/* neutral footnotes (dagger/lozenge markers) -- NOT `.foot .fm`, which is
   reserved crimson for the broken-queues banner; these are informational,
   never an alarm. */
.foot .nm{color:var(--dim);flex:0 0 auto;font-family:var(--sans);
  font-size:11px;font-weight:600;line-height:1.55}

/* -- CONTROLS: search + filter ------------------------------------------ */
.controls{display:flex;align-items:center;gap:14px;padding:0 0 8px;flex-wrap:wrap}
.field{position:relative;flex:1;min-width:240px;max-width:520px;
  display:flex;align-items:center;height:var(--u);
  background:var(--raise);border:1px solid var(--rule);border-radius:3px}
.field:focus-within{border-color:var(--rule-hi)}
.field input{
  width:100%;height:var(--u);background:transparent;border:0;outline:0;
  padding:0 14px 0 40px;color:var(--ink);border-radius:3px;
  font-family:var(--sans);font-size:13.5px;font-weight:400;letter-spacing:.01em;
  caret-color:var(--amber);
}
.field .mag{position:absolute;left:14px;top:50%;transform:translateY(-50%);
  color:var(--dim);display:flex;pointer-events:none}
.field .hint{position:absolute;left:40px;top:50%;transform:translateY(-50%);
  font-family:var(--sans);font-size:13.5px;color:var(--dim);
  pointer-events:none;white-space:nowrap;letter-spacing:.01em}
.field.typed .hint{display:none}
.count{font-family:var(--sans);font-size:11px;font-weight:600;
  letter-spacing:.14em;text-transform:uppercase;color:var(--dim);
  white-space:nowrap;margin-left:auto}
.count b{color:var(--mid);font-weight:600}
.count.hit b{color:var(--amber)}

/* -- TABLE --------------------------------------------------------------- */
table.tbl{width:100%;border-collapse:collapse;table-layout:fixed}
.tbl th{
  font-family:var(--sans);font-size:11px;font-weight:500;letter-spacing:.16em;
  text-transform:uppercase;color:var(--mid);text-align:left;
  padding:0 14px 15px 0;border-bottom:1px solid var(--rule-hi);
  white-space:nowrap;vertical-align:bottom;
}
.tbl th.r{text-align:right;padding-right:0}
.tbl th.gap,.tbl td.gap .c{padding-left:30px}
/* `overflow:hidden` is the structural fix for the id/state collision bug:
   with `table-layout:fixed`, a column's width is enforced on the <td> box,
   but a table cell does NOT clip its own content by default -- an
   over-length single-line value (e.g. a long project-name-prefixed item id)
   simply paints past the cell boundary and visually collides with whatever
   column comes next. Clipping at the <td> itself makes that structurally
   impossible regardless of what any one column's content happens to be;
   see `.iid` below for the accompanying ellipsis so a clipped id is still
   legible (never bare mid-character cutoff) and `title=` for the full
   value. Rows that wrap (e.g. a long Title) are unaffected: their box grows
   via `min-height` before this ever has anything to clip. */
.tbl td{padding:0;border-bottom:1px solid var(--rule);vertical-align:middle;overflow:hidden}
.tbl tbody tr:hover td{background:var(--raise)}
.tbl .c{min-height:52px;display:flex;align-items:center;padding:10px 16px 10px 0}
.tbl .c.r{justify-content:flex-end;padding-right:0}
.tbl td.r{text-align:right}
.tbl tfoot td{border-bottom:0;border-top:1px solid var(--rule-hi);
  padding-top:2px;vertical-align:middle}
.totk{font-family:var(--sans);font-size:10px;font-weight:600;
  letter-spacing:.19em;text-transform:uppercase;color:var(--mid);white-space:nowrap}
.tbl tfoot .n{font-size:13.5px;font-weight:600;color:var(--mid)}
tr.hidden{display:none}
.tbl tbody tr.grp td{border-bottom:1px solid var(--rule-hi);padding-top:26px}
.tbl tbody tr.grp .c{min-height:36px;align-items:flex-end;padding-bottom:9px;gap:12px}
.grplbl{font-family:var(--sans);font-size:10.5px;font-weight:600;
  letter-spacing:.19em;text-transform:uppercase;color:var(--mid)}
.grpn{font-family:var(--serif);font-size:17px;font-weight:500;color:var(--dim)}

/* project / item name links */
.pname{font-family:var(--sans);font-size:14.5px;font-weight:500;color:var(--ink);
  text-decoration:none;letter-spacing:-.004em;display:flex;align-items:center;
  min-height:var(--u);gap:11px;width:100%}
.pname:hover{color:var(--amber)}
.pname .rank{font-family:var(--sans);font-size:10.5px;font-weight:600;
  color:var(--dim);letter-spacing:.06em;flex:0 0 20px}

/* AGE -- serif, sized and coloured by staleness. the prominent column. */
.age{font-family:var(--serif);font-weight:500;line-height:1;color:var(--mid);
  letter-spacing:-.01em;display:inline-block}
.age .u{font-family:var(--sans);font-size:11px;font-weight:600;
  letter-spacing:.1em;color:var(--dim);margin-left:3px;text-transform:uppercase}
.age.a0{font-size:19px;color:var(--dim)}
.age.a1{font-size:23px;color:var(--mid)}
.age.a2{font-size:28px;color:var(--ink)}
.age.a3{font-size:33px;color:var(--amber)}
.age.a3 .u{color:var(--amber)}
.age.none{font-size:23px;color:var(--dim);font-family:var(--serif);
  letter-spacing:0;font-weight:400}

/* the age bar: length == age / current workspace max. literal encoding. */
.track{width:96px;flex:0 0 96px;margin-right:18px;height:6px;
  align-self:center;position:relative;background:#1B1B19}
.bar{height:6px;background:#4A463F;position:absolute;left:0;top:0}
.bar.hot{background:#7A6438}
.grad{position:absolute;top:0;bottom:0;width:1px;background:rgba(242,238,230,.28)}
.tbl th.axis{white-space:normal;padding-right:0}
.rul{position:relative;display:block;width:96px;height:9px;margin-top:6px}
.rul i{position:absolute;top:0;font-style:normal;font-family:var(--sans);
  font-size:9px;font-weight:600;letter-spacing:.04em;color:var(--dim);
  line-height:1;text-transform:none;white-space:nowrap}

/* counts -- small, dim, sans. deliberately quiet. */
.n{font-family:var(--sans);font-size:13.5px;font-weight:400;color:var(--dim);
  letter-spacing:.01em;font-variant-numeric:tabular-nums}
.n.ink{color:var(--mid);font-weight:500}
.n.zero{color:var(--dim)}

/* status -- type + a hairline mark, never a pill. Each state is distinguished
   by MARKER SHAPE and WEIGHT as well as hue, so none reads on colour alone. */
.state{font-family:var(--sans);font-size:10.5px;font-weight:600;
  letter-spacing:.15em;text-transform:uppercase;color:var(--mid);
  display:inline-flex;align-items:center;gap:9px;white-space:nowrap}
.state .sq{width:5px;height:5px;flex:0 0 5px;background:var(--mid)}
.state.ok{color:var(--dim);font-weight:500}
.state.ok .sq{background:#5C5851}
/* HELD -- legible beyond hue: heavier weight AND a taller filled marker, so it
   is told apart from "healthy" (a small dim square) by shape, not just amber. */
.state.warnv{color:var(--amber);font-weight:700}
.state.warnv .sq{background:var(--amber);height:11px}
/* BROKEN -- the loudest marker: the distinct --alarm hue + bold + an oversized
   block. `state_html("alarm", ...)` renders this; render lanes mark broken
   projects with it (a broken queue must never look like a healthy empty one). */
.state.alarm{color:var(--alarm);font-weight:700}
.state.alarm .sq{background:var(--alarm);width:9px;height:9px}
.state.bad{color:var(--crimson);font-weight:700}
.state.bad .sq{background:var(--crimson);width:7px;height:7px}

/* -- item rows (dense ledger) -------------------------------------------- */
.ti{font-size:14px;line-height:1.4;color:var(--ink);letter-spacing:-.002em;
  padding-right:24px}
.ti a{color:inherit;text-decoration:none;display:flex;align-items:center;
  width:100%;min-height:var(--u);padding:7px 0}
.ti a:hover{color:var(--amber)}
.ti a::after{content:"\203A";margin-left:auto;padding-left:14px;
  font-family:var(--sans);font-weight:700;font-size:15px;color:var(--mid)}
.ti a:hover::after{color:var(--amber)}
.idx{font-family:var(--sans);font-size:10.5px;color:var(--dim);letter-spacing:.05em}
/* `display:inline-block;max-width:100%` + the ellipsis trio is what makes
   "never collide at any title length" a real guarantee rather than a hope:
   a project name long enough to outgrow the Id column's width (see the
   colgroup in webapp.py's project item table) truncates with an ellipsis
   INSIDE its own cell instead of overflowing into State -- the full id is
   still one hover away via `title=` on the element this class is applied to. */
.iid{font-family:var(--sans);font-size:12px;font-weight:600;color:var(--mid);
  letter-spacing:.05em;display:inline-block;max-width:100%;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;vertical-align:bottom}
.holder{font-family:var(--sans);font-size:12px;color:var(--dim);letter-spacing:.01em}
.st{font-family:var(--sans);font-size:10px;font-weight:600;letter-spacing:.15em;
  text-transform:uppercase;white-space:nowrap}
.st-open{color:var(--ink)}
/* HELD carries a ticking custody clock -- the word HELD plus a heavy weight
   (not amber alone) is the beyond-hue signal. */
.st-held{color:var(--amber);font-weight:700}
/* RESOLVED is the quietest status AND the most common row on a busy queue.
   Previously --dim at 9.5px/400 it read as functionally invisible; kept the
   dimmest (now the lifted --dim floor) but a touch larger and heavier so it is
   legible small print, not absent. */
.st-done{color:var(--dim);font-weight:500;font-size:10.5px;letter-spacing:.13em}
.st-blkd{color:var(--crimson);font-weight:700}
.st-deferred{color:var(--quiet)}

/* -- link-cell (stretched-link): whole cell clickable, not just text ---- */
td.link-cell{padding:0}
td.link-cell > a{display:flex;align-items:center;width:100%;min-height:52px;
  padding:10px 16px 10px 0;text-decoration:none;color:inherit}
td.link-cell > a:hover{color:var(--amber)}
td.link-cell > a::after{content:"\203A";margin-left:auto;padding-left:14px;
  font-family:var(--sans);font-weight:700;font-size:15px;color:var(--mid)}
td.link-cell > a:hover::after{color:var(--amber)}

/* -- PROSE --------------------------------------------------------------- */
.prose{font-size:16.5px;line-height:1.66;color:var(--ink);font-weight:400;
  letter-spacing:.0015em;max-width:var(--measure,620px)}
.prose p + p{margin-top:1.1em}
.content-block{white-space:pre-wrap;word-break:break-word;background:var(--raise);
  border:1px solid var(--rule);border-radius:6px;padding:0.9rem 1rem;
  font-size:15px;line-height:1.6;color:var(--ink);margin:0.3rem 0 0}
/* MONOSPACE face for content whose alignment is meaningful -- ASCII tables,
   code, fixed-width output. Proportional Archivo destroys column alignment, so
   the item-body renderer applies `.mono` (e.g. `<div class="content-block mono">`)
   to pre-formatted content. `--measure` (set per-page via page()) already caps
   comfortable reading width for prose. */
.mono{font-family:var(--mono);font-variant-ligatures:none;
  font-variant-numeric:tabular-nums}
/* the single INLINE-link resting affordance: an underline in --link-underline,
   amber only on hover (never amber at rest -- amber at rest means attention). */
.prose-link{color:inherit;text-decoration:underline;
  text-decoration-color:var(--link-underline);text-underline-offset:2px}
.prose-link:hover{color:var(--amber);text-decoration-color:var(--amber)}

.foot{margin-top:24px;display:flex;gap:14px;align-items:baseline;
  font-family:var(--sans);font-size:12px;color:var(--quiet);letter-spacing:.015em;
  max-width:900px;line-height:1.6}
.foot .fm{color:var(--crimson);flex:0 0 auto;font-weight:600;font-size:10px;
  letter-spacing:.16em;text-transform:uppercase}
.foot + .foot{margin-top:14px}

/* -- key/value blocks (item detail) -------------------------------------- */
.kv{display:flex;flex-wrap:wrap;gap:0 0}
.kv div{padding-right:32px;margin-right:32px;margin-bottom:14px;
  border-right:1px solid var(--rule)}
.kv div:last-child{border-right:0;margin-right:0;padding-right:0}
.kv .k{font-family:var(--sans);font-size:9.5px;font-weight:600;
  letter-spacing:.18em;text-transform:uppercase;color:var(--dim);display:block;
  margin-bottom:7px}
.kv .v{font-family:var(--sans);font-size:13.5px;color:var(--ink);letter-spacing:.01em}
.kv .v a{color:inherit;text-decoration:underline;text-decoration-color:var(--link-underline)}
.kv .v a:hover{color:var(--amber)}
.kv .v.serif{font-family:var(--serif);font-size:20px;font-weight:500}
.kv .v.am{color:var(--amber)}

.crit{list-style:none}
.crit li{display:flex;gap:16px;padding:13px 0;border-bottom:1px solid var(--rule)}
.crit li:last-child{border-bottom:0}

/* -- forms (this app writes; the reference mockup never needed these) --- */
.formsec{border-top:1px solid var(--rule);padding:26px 0}
.formsec legend,.formsec .flegend{font-family:var(--sans);font-size:11px;
  font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--mid);
  display:block;margin-bottom:14px}
.formsec.danger{border-top-color:var(--crimson)}
.formsec.danger .flegend{color:var(--crimson)}
label{display:block;margin:0.7rem 0 0.3rem;font-size:11px;font-weight:600;
  letter-spacing:.08em;text-transform:uppercase;color:var(--dim)}
.field-hint{font-size:11.5px;color:var(--quiet);margin:0.15rem 0 0.3rem}
input[type=text],input[type=password],textarea,select{
  width:100%;max-width:480px;padding:0.55rem 0.7rem;box-sizing:border-box;
  font-family:var(--sans);font-size:13.5px;min-height:var(--u);
  border:1px solid var(--rule);border-radius:4px;background:var(--raise);
  color:var(--ink);
}
input[type=text]:focus,input[type=password]:focus,textarea:focus,select:focus{
  outline:2px solid var(--amber);outline-offset:1px;border-color:var(--rule-hi);
}
textarea{min-height:5.5rem}
input::placeholder,textarea::placeholder{color:var(--dim);opacity:1}
button,input[type=submit],a.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:9px;
  min-height:var(--u);padding:0 20px;margin-top:0.7rem;cursor:pointer;
  border-radius:4px;border:1px solid var(--amber);background:var(--amber);
  color:#171410;font-family:var(--sans);font-size:12px;font-weight:700;
  letter-spacing:.08em;text-transform:uppercase;text-decoration:none;
}
button:hover,input[type=submit]:hover,a.btn:hover{background:#c99244}
button.secondary,a.btn.secondary{background:transparent;color:var(--mid);
  border-color:var(--rule)}
button.secondary:hover,a.btn.secondary:hover{color:var(--ink);border-color:var(--rule-hi)}
button.danger,input.danger,a.btn.danger{background:var(--crimson);
  border-color:var(--crimson);color:#1a0d0b}
button.danger:hover,a.btn.danger:hover{background:#c44c40}
/* The shared button rule's `margin-top:0.7rem` above is for a STACKED
   form (label, field, ..., button below it with real vertical breathing
   room) -- exactly wrong inside a horizontal `.controls` row (the
   search/filter bar), where it silently pushes the button ~half its own
   margin lower than the input/select beside it (`align-items:center`
   centers each item's OWN margin box, so an asymmetric top-only margin
   shifts that item's visual center down relative to its zero-margin
   siblings). Neutralized here, scoped to `.controls`, rather than removed
   from the shared rule -- stacked forms elsewhere still want the spacing. */
.controls button,.controls input[type=submit],.controls a.btn{margin-top:0}
.flash{padding:0.7rem 1rem;border-radius:6px;margin-bottom:1.2rem;font-size:12.5px;
  font-family:var(--sans);letter-spacing:.01em}
.flash-msg{background:rgba(217,162,83,.12);color:var(--amber);
  border:1px solid rgba(217,162,83,.35)}
.flash-error{background:rgba(224,101,90,.12);color:var(--crimson);
  border:1px solid rgba(224,101,90,.35)}
.muted{color:var(--dim);font-size:12px}
.empty-state{border:1px dashed var(--rule-hi);border-radius:8px;padding:1.5rem;
  color:var(--quiet);margin:0.75rem 0 1.25rem;background:var(--raise);
  font-family:var(--sans);font-size:13px;line-height:1.6}
.chip{display:inline-block;padding:0.15rem 0.6rem;border-radius:999px;
  font-size:11px;background:var(--raise);color:var(--ink);
  border:1px solid var(--rule-hi);margin:0 0.2rem 0.2rem 0;font-family:var(--sans)}
.links-list{margin:0.2rem 0 1rem;padding-left:1.2rem;font-size:13px;
  color:var(--mid)}
.links-list a{color:var(--mid);text-decoration:underline;
  text-decoration-color:var(--link-underline)}
.links-list a:hover{color:var(--amber)}

/* -- pagination ----------------------------------------------------------- */
.pagination{display:flex;justify-content:space-between;align-items:center;
  flex-wrap:wrap;gap:0.5rem 1rem;margin:-0.25rem 0 1.25rem;font-size:11.5px;
  color:var(--dim);font-family:var(--sans);letter-spacing:.02em}
.pagination a{color:var(--mid);text-decoration:none}
.pagination a:hover{color:var(--amber)}

/* -- status bar ----------------------------------------------------------- */
.statusbar{
  position:fixed;left:0;right:0;bottom:0;height:46px;z-index:40;
  background:var(--sink);border-top:1px solid var(--rule);
  display:flex;align-items:center;gap:26px;padding:0 var(--pad);
  overflow-x:auto;
}
.statusbar .s{font-family:var(--sans);font-size:11px;color:var(--dim);
  letter-spacing:.04em;display:flex;align-items:center;gap:8px;white-space:nowrap}
.statusbar .s b{color:var(--mid);font-weight:600}
.statusbar .s b.am{color:var(--amber)}
.statusbar .sp{flex:1}

.skip{position:absolute;left:-9999px;top:8px;z-index:99;background:var(--amber);
  color:#171410;min-height:var(--u);display:inline-flex;align-items:center;
  padding:0 20px;font-family:var(--sans);font-size:11px;font-weight:700;
  letter-spacing:.14em;text-transform:uppercase;text-decoration:none}
.skip:focus{left:var(--pad)}

@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{
    animation-duration:.001ms !important;animation-iteration-count:1 !important;
    transition-duration:.001ms !important;scroll-behavior:auto !important}
  .dot.on{animation:none;opacity:1}
}
"""

# ---------------------------------------------------------------------------
# icons -- inline SVG, no external refs (hygiene: fonts inline, no network)
# ---------------------------------------------------------------------------


def _svg(paths: str) -> str:
    return (
        '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" '
        'stroke-linecap="square" aria-hidden="true">' + paths + "</svg>"
    )


ICONS = {
    "mag": _svg('<circle cx="7.1" cy="7.1" r="4.6"/><path d="M10.6 10.6l3.1 3.1"/>'),
    "filter": _svg('<path d="M1.8 3h12.4L9.5 8.5v4.3l-3 1.4V8.5z"/>'),
}


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


# ---------------------------------------------------------------------------
# page shell
# ---------------------------------------------------------------------------


def page(title: str, body: str, *, js: str = "", measure_px: int = 620) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"{_PWA_HEAD_HTML}"
        f"<title>{_esc(title)}</title><style>\n{_FONT_FACE_CSS}{CSS}\n"
        f":root{{--measure:{measure_px}px}}\n</style></head><body>\n"
        '<a class="skip" href="#main">Skip to content</a>\n'
        f"{body}\n" + (f"<script>{js}</script>\n" if js else "") + "</body></html>\n"
    )


# ---------------------------------------------------------------------------
# PWA head tags -- manifest link, theme-color, iOS home-screen chrome, and
# the service-worker registration script, on every page. Ported in shape
# from muxplex's `frontend/index.html` (per explicit request); the actual
# manifest/service-worker content lives in `webpwa.py`, served by routes in
# `webapp.py` (all five PWA asset paths are auth-exempt -- a browser must
# be able to fetch them before/without a login for install to work at all).
#
# `theme-color` below is `--ground` (`#0D0D0C`) written as a literal, kept
# in sync with `webpwa.GROUND_HEX` and `CSS`'s own `--ground` by comment,
# not by cross-module import -- this file already owns its palette as a
# self-contained visual system (see this module's own docstring); the same
# comment-based-sync convention this codebase already uses elsewhere (see
# `webapp.py`'s `_item_search_key` docstring).
# ---------------------------------------------------------------------------

_PWA_HEAD_HTML = (
    '<meta name="theme-color" content="#0D0D0C">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
    '<meta name="apple-mobile-web-app-title" content="Work Tracker">'
    '<link rel="manifest" href="/manifest.json">'
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
    "<script>"
    "if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js');}"
    "</script>"
)


def top_bar(*, crumb_html: str = "", right_html: str = "") -> str:
    """The persistent top bar: brand (home link) + breadcrumb trail + a
    right-aligned slot for live/identity/logout chrome. No `<h1>` here --
    unlike the reference's fixed 5-section app, this app's real page
    titles are already the first heading each route's own body renders
    (`Dashboard` / a project name / an item id), so repeating it in the
    chrome would be redundant, not load-bearing."""
    crumb = f'<span class="crumb">{crumb_html}</span>' if crumb_html else ""
    right = f'<span class="identity">{right_html}</span>' if right_html else ""
    return (
        '<header class="top">'
        '<a class="brand" href="/"><span class="bm"></span>amplifier-work-tracker</a>'
        f'{crumb}<span class="sp"></span>{right}'
        "</header>"
    )


def statusbar(left_html: str, right_html: str = "") -> str:
    return f'<footer class="statusbar">{left_html}<span class="sp"></span>{right_html}</footer>'


def search_field(hint: str, field_id: str = "q") -> str:
    return (
        '<div class="field" id="field">'
        f'<span class="mag">{ICONS["mag"]}</span>'
        f'<input id="{field_id}" type="search" autocomplete="off" spellcheck="false" '
        f'aria-label="{_esc(hint)}">'
        f'<span class="hint" id="hint">{_esc(hint)}</span></div>'
    )


def search_js(total: int, noun: str, row_sel: str = "[data-t]", field_id: str = "q") -> str:
    """Genuinely filters the live DOM by the `data-t` attribute on each row,
    with a truthful `N OF total NOUN` counter -- ported verbatim (logic
    unchanged) from the reference's `shell.search_js`, which claims.py
    verified filters truthfully on all five reference screens.

    Re-invocation safe: `auto_refresh_js` re-executes this same script
    (via a fresh `<script>` element, since a `.innerHTML` swap never runs
    the scripts it inserts) every time it replaces the page body, so every
    element lookup below happens fresh at call time rather than being
    captured once in a stale closure -- the whole point is that it binds
    to whatever `{field_id}`/`{row_sel}` elements exist RIGHT NOW, old or
    freshly swapped-in. The one exception is the `document`-level keydown
    shortcut (`/` and Cmd/Ctrl-K): `document` itself is never replaced by
    the body swap, so re-registering that listener on every re-invocation
    would silently accumulate one duplicate per refresh tick forever --
    guarded by a `window`-level flag so it is attached exactly once for
    the life of the page, however many times this function itself reruns.
    """
    return f"""
(function(){{
  var q=document.getElementById('{field_id}'), field=document.getElementById('field'),
      out=document.getElementById('qc'),
      rows=[].slice.call(document.querySelectorAll('{row_sel}')),
      groups=[].slice.call(document.querySelectorAll('tr.grp'));
  if(!q) return;
  var TOTAL={total};
  function apply(){{
    var v=q.value.trim().toLowerCase();
    if(field) field.classList.toggle('typed', v.length>0);
    var n=0;
    rows.forEach(function(r){{
      var hit = !v || (r.getAttribute('data-t')||'').indexOf(v)>-1;
      r.classList.toggle('hidden', !hit);
      if(hit) n++;
    }});
    groups.forEach(function(g){{
      var any=false, s=g.nextElementSibling;
      while(s && !s.classList.contains('grp')){{
        if(s.hasAttribute('data-t') && !s.classList.contains('hidden')) {{any=true;break;}}
        s=s.nextElementSibling;
      }}
      g.classList.toggle('hidden', !any);
    }});
    if(out){{
      out.textContent = v ? (n+' OF '+TOTAL+' {noun}') : (TOTAL+' {noun}');
      out.classList.toggle('hit', v.length>0);
    }}
  }}
  q.addEventListener('input', apply);
  q.addEventListener('keydown', function(e){{ if(e.key==='Escape'){{ q.value=''; apply(); }} }});
  if(!window.__wtSearchShortcutBound){{
    window.__wtSearchShortcutBound = true;
    document.addEventListener('keydown', function(e){{
      var el=document.getElementById('{field_id}');
      if(!el) return;
      if(e.key==='/' && document.activeElement!==el){{ e.preventDefault(); el.focus(); }}
      if((e.metaKey||e.ctrlKey) && e.key.toLowerCase()==='k'){{ e.preventDefault(); el.focus(); }}
    }});
  }}
  apply();
}})();
"""


def auto_refresh_js(interval_ms: int) -> str:
    """A self-polling monitor: every `interval_ms`, silently re-fetch the
    CURRENT page and swap `document.body` in place -- refreshing hero
    figures, the workspace composition bar's alarm treatment, every queue
    row, and the status bar -- without a hard navigation (no browser
    loading flash, no scroll-to-top, no lost place). This is what makes a
    calm-to-alarm transition (a held/blocked item appearing) show up on a
    screen nobody is touching, which is the entire reason this dashboard
    exists (see `webapp.py`'s `_AUTO_REFRESH_MS`).

    Two independent guards, checked every tick; either one skips this
    tick only -- it tries again next interval, it never stops polling:
      - the tab is hidden (`document.hidden`): no point fetching for a
        backgrounded tab, and no risk of surprising whoever isn't looking.
      - the user is mid-input ANYWHERE on the page: `document.activeElement`
        is an INPUT/TEXTAREA/SELECT (focused, dirty or not), or the `#q`
        field (both the dashboard's client-side filter and the project
        view's server-side search box use this id) already has a typed,
        unsubmitted value. A silent body swap would otherwise destroy
        focus and whatever was typed -- see `webapp.py`'s `_page` for why
        the item-detail edit page instead never receives this script at
        all rather than leaning on this guard alone.

    A single `window`-level flag makes the whole poller idempotent: the
    fetched body's own markup includes this exact script again (every
    page render goes through the same `_page`/`page` shell), so without
    the guard each successful refresh would re-execute this IIFE and
    register a second, competing `setInterval` -- compounding on every
    tick. `window` itself is never replaced by a body swap, so the flag
    holds for the life of the page.

    The refetch URL drops `msg`/`error` query params: those are one-time
    flash notices from whatever redirected here, and re-fetching the
    exact same URL forever would otherwise re-display the same flash on
    every tick instead of letting it be transient.

    Every script tag in the freshly-swapped body is re-created (not left
    as inert markup -- `.innerHTML` never executes the `<script>` tags it
    inserts) so `search_js`'s own re-invocation-safe binding above
    actually reruns against the new DOM.
    """
    return f"""
(function(){{
  if(window.__wtAutoRefreshStarted) return;
  window.__wtAutoRefreshStarted = true;
  var INTERVAL={interval_ms};
  var inFlight=false;
  function isGuarded(){{
    if(document.hidden) return true;
    var el=document.activeElement, tag=el && el.tagName;
    if(tag==='INPUT' || tag==='TEXTAREA' || tag==='SELECT') return true;
    var q=document.getElementById('q');
    if(q && q.value) return true;
    return false;
  }}
  function refetchUrl(){{
    var u=new URL(location.href);
    u.searchParams.delete('msg');
    u.searchParams.delete('error');
    return u.pathname + (u.search || '');
  }}
  function pulse(){{
    var dots=document.querySelectorAll('.dot.on');
    dots.forEach(function(d){{
      d.classList.remove('refreshed');
      void d.offsetWidth;
      d.classList.add('refreshed');
    }});
  }}
  function tick(){{
    if(inFlight || isGuarded()) return;
    inFlight=true;
    fetch(refetchUrl(), {{credentials:'same-origin',
      headers:{{'X-Requested-With':'wt-auto-refresh'}}}})
      .then(function(r){{ return r.ok ? r.text() : null; }})
      .then(function(html){{
        if(!html) return;
        var doc=new DOMParser().parseFromString(html, 'text/html');
        if(!doc.body) return;
        document.body.innerHTML = doc.body.innerHTML;
        var scripts=[].slice.call(document.body.querySelectorAll('script'));
        scripts.forEach(function(old){{
          var s=document.createElement('script');
          s.textContent = old.textContent;
          old.replaceWith(s);
        }});
        pulse();
      }})
      .catch(function(){{ /* silent -- next tick tries again */ }})
      .finally(function(){{ inFlight=false; }});
  }}
  setInterval(tick, INTERVAL);
}})();
"""


# ---------------------------------------------------------------------------
# age / duration formatting -- the serif is the voice of time. Every one of
# these renders a `datetime`-derived quantity, never a count.
# ---------------------------------------------------------------------------


def duration_words(seconds: float) -> tuple[str, str]:
    """(`value`, `UNIT`) for the HERO figure -- e.g. `("9", "DAYS")`,
    `("14", "HOURS")`, `("3", "MINUTES")`. Never fabricates a "0": the
    caller (webapp.py) is responsible for rendering the no-ready-item
    case as its own honest empty state, not as this function's output.

    Real workspaces are not bounded to whole days the way the reference
    mockup's fixture data was -- an item unclaimed for 40 minutes is real
    and should read as "40 MINUTES", not be truncated to "0 DAYS" (which
    is exactly the fabricated-zero anti-pattern this dashboard's whole
    thesis rejects; see MANIFEST.md's "no 0 BLOCKED tile" reasoning,
    which applies here too).
    """
    seconds = max(0.0, seconds)
    days = int(seconds // 86400)
    if days >= 1:
        return str(days), "DAY" if days == 1 else "DAYS"
    hours = int(seconds // 3600)
    if hours >= 1:
        return str(hours), "HOUR" if hours == 1 else "HOURS"
    minutes = int(seconds // 60)
    if minutes >= 1:
        return str(minutes), "MINUTE" if minutes == 1 else "MINUTES"
    return str(int(seconds)), "SECOND" if int(seconds) == 1 else "SECONDS"


def age_short(seconds: float | None) -> tuple[str, str]:
    """(`value`, `unit`) for a compact ROW-level age cell -- e.g.
    `("9", "d")`, `("14", "h")`, `("32", "m")`. `None` in -> `("--", "")`
    out; the caller renders that as `.age.none`, never as a bar."""
    if seconds is None:
        return "\u2014", ""
    seconds = max(0.0, seconds)
    days = int(seconds // 86400)
    if days >= 1:
        return str(days), "d"
    hours = int(seconds // 3600)
    if hours >= 1:
        return str(hours), "h"
    minutes = int(seconds // 60)
    return str(max(minutes, 0)), "m"


def age_band_class(seconds: float | None) -> str:
    """a0 (<=1d, quietest) .. a3 (>6d, loudest amber), or "none". FIXED
    real-world day thresholds -- see module docstring for why this does
    NOT rescale with the current workspace max the way the bar length
    does: "waited a week" should always read the same colour."""
    if seconds is None:
        return "none"
    days = seconds / 86400
    if days <= 1:
        return "a0"
    if days <= 3:
        return "a1"
    if days <= 6:
        return "a2"
    return "a3"


TRACK_W = 96  # px -- the age bar/ruler's fixed pixel width


def _grad_x(fraction: float) -> float:
    return TRACK_W * fraction


def axis_ruler_html(scale_seconds: float) -> str:
    """The printed ruler for the `<th>` header, e.g. `0 .. 3 .. 6 .. 9d`
    scaled to the CURRENT workspace's oldest-unclaimed age (`scale_seconds`).

    Every numeral's x position is computed from the exact same `_grad_x`
    formula used by `bar_html` below for the graduation tick marks --
    one shared source of coordinates, so the printed numerals and the
    tick marks under every bar can never drift apart. (The reference
    design drew its graduations via an independently-tuned CSS
    `repeating-linear-gradient` and its numerals via separately hand-set
    `left` values -- two representations of the same three positions,
    which is exactly the kind of drift a later review caught as "axis
    labels sit slightly left of the bars beneath them". Deriving both
    from one formula makes that class of bug structurally impossible.)
    """
    scale_days = max(scale_seconds, 1.0) / 86400
    marks = [0.0, scale_days / 3, scale_days * 2 / 3, scale_days]
    labels = [_fmt_axis_day(d) for d in marks]
    labels[-1] = labels[-1] + "d"
    out = []
    for frac, label in zip((0.0, 1 / 3, 2 / 3, 1.0), labels, strict=True):
        x = _grad_x(frac)
        if frac == 0.0:
            style = "left:0"
        elif frac == 1.0:
            style = "right:0"
        else:
            style = f"left:{x:.1f}px;transform:translateX(-50%)"
        out.append(f'<i style="{style}">{_esc(label)}</i>')
    return f'<span class="rul">{"".join(out)}</span>'


def _fmt_axis_day(days: float) -> str:
    n = round(days)
    return str(n)


def bar_html(seconds: float | None, scale_seconds: float) -> str:
    """The age bar + its graduation ticks, for one row of the queues
    table. Length is proportional to `seconds / scale_seconds` (the
    current workspace's oldest-unclaimed age) -- the literal encoding:
    a bar half as long as the full track means half as old as the worst
    case right now. Ticks are drawn at the SAME three fractions
    `axis_ruler_html` prints numerals for, so a bar is always read
    against a scale that is actually printed above it."""
    scale = max(scale_seconds, 1.0)
    grads = "".join(
        f'<span class="grad" style="left:{_grad_x(f):.1f}px"></span>' for f in (1 / 3, 2 / 3)
    )
    if not seconds:
        return f'<span class="track">{grads}</span>'
    frac = min(1.0, seconds / scale)
    px = max(3, round(TRACK_W * frac))
    hot = " hot" if age_band_class(seconds) == "a3" else ""
    return f'<span class="track"><span class="bar{hot}" style="width:{px}px"></span>{grads}</span>'


def age_cell_html(seconds: float | None, scale_seconds: float) -> str:
    """The full "Oldest unclaimed" table cell: bar + serif age numeral,
    or the honest `--` dash when nothing is ready (never a fabricated
    age for an empty queue)."""
    if seconds is None:
        return bar_html(None, scale_seconds) + '<span class="age none">\u2014</span>'
    band = age_band_class(seconds)
    value, unit = age_short(seconds)
    return (
        bar_html(seconds, scale_seconds)
        + f'<span class="age {band}">{_esc(value)}<span class="u">{_esc(unit)}</span></span>'
    )


def state_html(kind: str, label: str) -> str:
    """A status marker: type + a hairline coloured square, never a pill.

    `kind` is one of:
      "ok"    -- healthy / quiet (dim, small square)
      "warn"  -- HELD: attention, amber, heavier weight + a taller marker
      "alarm" -- BROKEN: a project the backend cannot read; the distinct
                 --alarm hue + bold + an oversized block. Render lanes mark a
                 broken/creating project with this so it is never pixel-identical
                 to a healthy empty one.
      "bad"   -- ESCALATION: crimson, item-level (a blocked item, a danger).

    Unknown kinds fall back to "ok". Each state is legible beyond hue alone
    (weight + marker shape), per the status CSS."""
    cls = {"ok": "ok", "warn": "warnv", "alarm": "alarm", "bad": "bad"}.get(kind, "ok")
    return f'<span class="state {cls}"><span class="sq"></span>{_esc(label)}</span>'


__all__ = [
    "CSS",
    "ICONS",
    "TRACK_W",
    "age_band_class",
    "age_cell_html",
    "age_short",
    "auto_refresh_js",
    "axis_ruler_html",
    "bar_html",
    "duration_words",
    "page",
    "search_field",
    "search_js",
    "state_html",
    "statusbar",
    "top_bar",
]
