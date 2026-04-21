#!/usr/bin/env python3
"""
skills.py — SkillLoader: scan skills/<name>/SKILL.md files with YAML frontmatter.

Two-layer skill injection:

  Layer 1 (cheap):  skill names + short descriptions in the system prompt
                    (~100 tokens per skill — always loaded)
  Layer 2 (on demand): full skill body returned only when the agent calls
                    load_skill("name") as a tool call

This avoids bloating every agent's context with skill content that may not
be needed for a given task.

Skill directories:
  skills/log-parser/SKILL.md
  skills/static-analysis/SKILL.md
  skills/fixer/SKILL.md
"""

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillLoader:
    """Scan skills/<name>/SKILL.md files and expose two-layer loading."""

    def __init__(self, skills_dir: Path = SKILLS_DIR):
        self.skills_dir = skills_dir
        self.skills: dict = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text(encoding="utf-8")
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    def _parse_frontmatter(self, text: str) -> tuple:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta: dict = {}
        for line in match.group(1).strip().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        """Layer 1: one-line descriptions for the system prompt."""
        if not self.skills:
            return "  (no skills available)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """Layer 2: full skill body, returned as tool_result when agent calls load_skill."""
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(self.skills.keys())
            return f"Error: Unknown skill '{name}'. Available: {available}"
        return f'<skill name="{name}">\n{skill["body"]}\n</skill>'


# Module-level singleton used by pipeline.py and tool handlers
SKILL_LOADER = SkillLoader()
