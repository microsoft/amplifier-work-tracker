"""Tier 1 -- pure-function tests for `webapp._render_item_markdown` /
`_content_block_html` / `_fact_value_html` / `_item_row`.

No bd, no dolt, no network: these are plain string transforms. See
`tests/integration/test_web.py` for the end-to-end check that the
item-detail route actually renders a real project's real description --
this file covers the rendering rules themselves (markdown-lite syntax,
escaping, monospace/measure styling, inert fact markup) independent of
whatever the route wires up.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker.webapp import (  # noqa: E402
    _content_block_html,
    _esc,
    _fact_value_html,
    _item_row,
    _render_item_markdown,
)

# ------------------------------------------------------ _render_item_markdown


def test_render_item_markdown_converts_bold():
    assert _render_item_markdown("**important**") == "<strong>important</strong>"


def test_render_item_markdown_converts_inline_code():
    assert _render_item_markdown("run `pytest -x` now") == "run <code>pytest -x</code> now"


def test_render_item_markdown_converts_fenced_code_block_and_preserves_alignment():
    text = "```\ncol1  col2\nx     y\n```"
    rendered = _render_item_markdown(text)
    # The trailing newline right before the closing fence is dropped, so a
    # ```\ncode\n``` block doesn't render with a trailing blank line.
    assert rendered == "<pre><code>col1  col2\nx     y</code></pre>"
    assert "col1  col2" in rendered  # column spacing preserved verbatim


def test_render_item_markdown_converts_headings_to_subordinate_tags():
    """h1-h3 are reserved for page chrome -- item body headings always land
    on h4 or deeper, however many '#'s the author used."""
    assert _render_item_markdown("# Title") == "<h4>Title</h4>"
    assert _render_item_markdown("## Sub") == "<h5>Sub</h5>"
    assert _render_item_markdown("###### deep") == "<h6>deep</h6>"


def test_render_item_markdown_leaves_plain_text_unchanged():
    text = "a very specific description body"
    assert _render_item_markdown(text) == text


def test_render_item_markdown_escapes_html_before_processing_markdown():
    """Untrusted HTML never survives, even inside markdown constructs."""
    rendered = _render_item_markdown("**<script>alert(1)</script>**")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert rendered.startswith("<strong>")


def test_render_item_markdown_does_not_process_markdown_inside_code_blocks():
    text = "```\n**not bold** `not code`\n```"
    rendered = _render_item_markdown(text)
    assert "<strong>" not in rendered
    assert rendered.count("<code>") == 1  # only the outer <pre><code> wrapper
    assert "**not bold**" in rendered


def test_render_item_markdown_preserves_newlines_for_the_pre_wrap_container():
    text = "line one\nline two"
    assert _render_item_markdown(text) == text


# --------------------------------------------------------- _content_block_html


def test_content_block_html_shows_empty_message_when_text_is_none():
    html = _content_block_html(None, empty_message="No description provided.")
    assert "No description provided." in html
    assert 'class="content-block"' in html


def test_content_block_html_shows_empty_message_when_text_is_empty_string():
    html = _content_block_html("", empty_message="No acceptance criteria provided.")
    assert "No acceptance criteria provided." in html


def test_content_block_html_renders_provided_text_with_monospace_and_measure():
    html = _content_block_html("hello world", empty_message="unused")
    assert "hello world" in html
    assert 'class="content-block"' in html
    assert "monospace" in html
    assert "max-width:90ch" in html


def test_content_block_html_renders_markdown_inside_the_block():
    html = _content_block_html("**bold** text", empty_message="unused")
    assert "<strong>bold</strong> text" in html


# ------------------------------------------------------------ _fact_value_html


def test_fact_value_html_escapes_and_is_non_interactive():
    html = _fact_value_html("task")
    assert html == '<span class="fact-static" style="cursor:default">task</span>'
    assert "<a " not in html
    assert "href" not in html


def test_fact_value_html_escapes_html_special_characters():
    html = _fact_value_html("<b>bug</b>")
    assert "<b>bug</b>" not in html
    assert "&lt;b&gt;" in html


# --------------------------------------------------------------------- _item_row


def _make_item(item_id: str, title: str) -> A.Item:
    now = datetime.now(UTC)
    return A.Item(
        id=item_id,
        title=title,
        status="open",
        kind="task",
        priority=None,
        holder=None,
        created_at=now,
        updated_at=now,
        closed_at=None,
        description=None,
        acceptance=None,
        resolution=None,
        raw={},
    )


def test_item_row_never_concatenates_id_and_title_without_a_separator():
    """Regression guard for the goal's described "cortexcortex-i2u"
    no-separator concat bug: `i.id` and `i.title` must never appear
    adjacent in the row's HTML with nothing between them. As currently
    written they're rendered in separate <td> cells (id in one, title
    inside an <a> in another), so this always holds -- this test pins
    that invariant so a future edit can't silently reintroduce it."""
    item = _make_item("cortex-i2u", "cortexthing")
    row = _item_row("cortex", item, 1)
    assert f"{item.id}{item.title}" not in row
    # On the project view, show the suffix as primary; keep full id on hover via title
    assert f'<span class="iid" title="{_esc(item.id)}">i2u</span>' in row
    assert f">{_esc(item.title)}<" in row


def test_item_row_has_separate_id_and_title_cells():
    item = _make_item("proj-abcd", "some title")
    row = _item_row("proj", item, 3)
    # On the project view, show the suffix as primary; keep full id on hover via title
    assert '<td><span class="c"><span class="iid" title="proj-abcd">abcd</span></span></td>' in row
    assert '<td class="ti"><a href="/projects/proj/items/proj-abcd">some title</a></td>' in row
