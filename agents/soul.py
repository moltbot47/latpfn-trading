"""
Soul file loader — parses agent identity markdown into structured config.

Soul files are readable/editable markdown that define an agent's identity,
risk parameters, communication rules, and Discord personality.  Non-devs
can edit them to tune agent behavior without touching code.
"""

import logging
import re
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

SOULS_DIR = Path(__file__).parent / "souls"


class SoulFile:
    """Parsed soul file for a trading agent."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.raw: str = ""
        self.sections: Dict[str, str] = {}
        self._load()

    def _load(self):
        """Load and parse the markdown soul file."""
        path = SOULS_DIR / f"{self.agent_name}.md"
        if not path.exists():
            logger.warning("Soul file not found: %s", path)
            return
        self.raw = path.read_text(encoding="utf-8")
        self.sections = self._parse_sections(self.raw)
        logger.info(
            "Soul loaded for '%s' — %d sections",
            self.agent_name, len(self.sections),
        )

    def _parse_sections(self, text: str) -> Dict[str, str]:
        """Split markdown into {heading_lower: content} pairs."""
        sections = {}
        current_heading = "preamble"
        current_lines = []

        for line in text.splitlines():
            match = re.match(r"^(#{1,3})\s+(.+)", line)
            if match:
                if current_lines:
                    sections[current_heading] = "\n".join(current_lines).strip()
                current_heading = match.group(2).strip().lower()
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            sections[current_heading] = "\n".join(current_lines).strip()
        return sections

    @property
    def identity(self) -> str:
        return self.sections.get("identity", "")

    @property
    def personality(self) -> str:
        """Extract personality line from identity section."""
        for line in self.identity.splitlines():
            if "personality" in line.lower():
                return line.split(":", 1)[-1].strip() if ":" in line else line
        return ""

    @property
    def core_drive(self) -> str:
        """Extract core drive from identity section."""
        for line in self.identity.splitlines():
            if "core drive" in line.lower():
                return line.split(":", 1)[-1].strip() if ":" in line else line
        return ""

    @property
    def embed_color(self) -> int:
        """Extract embed color hex from Discord Personality section."""
        dp = self.sections.get("discord personality", "")
        match = re.search(r"0x([0-9a-fA-F]+)", dp)
        return int(match.group(0), 16) if match else 0x808080

    @property
    def footer_text(self) -> str:
        """Extract footer text from Discord Personality section."""
        dp = self.sections.get("discord personality", "")
        for line in dp.splitlines():
            if "footer:" in line.lower():
                # Extract quoted text or text after colon
                quoted = re.search(r'"([^"]+)"', line)
                if quoted:
                    return quoted.group(1)
                return line.split(":", 1)[-1].strip()
        return f"{self.agent_name.upper()} Agent"

    def get_section(self, heading: str) -> str:
        """Get a section by heading (case-insensitive)."""
        return self.sections.get(heading.lower(), "")

    def reload(self):
        """Hot-reload the soul file from disk."""
        self._load()
        logger.info("Soul reloaded for '%s'", self.agent_name)
