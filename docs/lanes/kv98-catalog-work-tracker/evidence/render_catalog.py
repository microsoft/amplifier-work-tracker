#!/usr/bin/env python3
"""Render THIS repo's contribution to the two always-on catalogs.

Both renderers are the SHIPPED ones, not re-implementations:

  * hooks-skills-visibility -- `SkillsVisibilityHook._format_skills_list`
    imported live from the installed amplifier-bundle-skills cache, fed
    real `SkillMetadata` parsed from this repo's SKILL.md files.
  * delegate agent catalog -- the one format string at
    amplifier-foundation/modules/tool-delegate/.../__init__.py:938
    (`f"  - {a['name']}: {a.get('description', 'No description')}"`),
    quoted here because building it in-process needs a live registry.

Usage:  render_catalog.py <repo-root> <label>
"""

import os
import re
import sys
from pathlib import Path

import yaml

SKILLS_MOD = next(
    p
    for p in Path("/home/bkrabach/.amplifier/cache").glob(
        "amplifier-bundle-skills-*/modules/tool-skills"
    )
)
sys.path.insert(0, str(SKILLS_MOD))
from amplifier_module_tool_skills.discovery import SkillMetadata  # noqa: E402
from amplifier_module_tool_skills.hooks import SkillsVisibilityHook  # noqa: E402

NAMESPACE = "work-tracker"


def frontmatter(path: Path) -> dict:
    txt = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
    if not m:
        raise SystemExit(f"no frontmatter: {path}")
    return yaml.safe_load(m.group(1))


def main() -> None:
    repo = Path(sys.argv[1]).resolve()
    label = sys.argv[2]

    # ---- delegate agent catalog -------------------------------------
    agent_lines = []
    for f in sorted(repo.glob("agents/*.md")):
        meta = frontmatter(f).get("meta", {})
        name = f"{NAMESPACE}:{meta['name']}"
        agent_lines.append(f"  - {name}: {meta.get('description', 'No description')}")
    agent_block = "\n".join(agent_lines)

    # ---- hooks-skills-visibility ------------------------------------
    skills = {}
    for f in sorted(repo.glob("skills/*/SKILL.md")):
        fm = frontmatter(f)
        skills[fm["name"]] = SkillMetadata(
            name=fm["name"],
            description=fm["description"],
            path=f,
            source=str(repo),
            version=fm.get("version"),
        )
    hook = SkillsVisibilityHook(skills=skills, config={})
    skills_block = hook._format_skills_list(skills)

    print(f"===== {label} =====")
    print("--- delegate agent catalog (this repo's entries) ---")
    print(agent_block)
    print(f"[agent catalog bytes: {len(agent_block.encode())}]")
    print()
    print("--- hooks-skills-visibility (this repo's entries) ---")
    print(skills_block)
    print(f"[skills block bytes: {len(skills_block.encode())}]")
    print()
    print(f"[COMBINED CATALOG BYTES: {len(agent_block.encode()) + len(skills_block.encode())}]")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONHASHSEED", "0")
    main()
