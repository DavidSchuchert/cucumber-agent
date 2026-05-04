"""Capabilities tool — allows the agent to see all available tools and skills."""

from __future__ import annotations

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry


class CapabilitiesTool(BaseTool):
    """List all available tools and slash commands."""

    name = "capabilities"
    description = (
        "Listet alle verfügbaren Werkzeuge (Tools) und Spezial-Befehle (Skills) auf. "
        "Nutze dieses Tool, wenn du dir unsicher bist, welche Funktionen dir zur Verfügung stehen."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optionaler Suchbegriff, um nach bestimmten Funktionen zu suchen.",
            }
        },
    }
    auto_approve = True

    async def execute(self, query: str | None = None) -> ToolResult:
        """Return a summary of all capabilities."""
        try:
            # We don't have direct access to skill_loader here easily without passing it through,
            # but we can at least return all registered tools and a reminder about skills.
            
            tools = ToolRegistry.get_capabilities_summary()
            
            lines = ["### Verfügbare Werkzeuge (Tools):"]
            for t in tools:
                if query and query.lower() not in t["name"].lower() and query.lower() not in t["description"].lower():
                    continue
                lines.append(f"- **{t['name']}**: {t['description']}")
                
            lines.append("\n### Spezial-Befehle (Skills):")
            lines.append("Diese Befehle beginnen mit einem '/' und können vom Benutzer direkt eingegeben werden.")
            lines.append("Du kannst dem Benutzer vorschlagen, einen dieser Befehle zu nutzen.")
            
            # Since we can't easily get the skills here without changing too much infra, 
            # we rely on the system prompt injection we just added.
            lines.append("(Siehe deinen System-Prompt für die vollständige Liste der Skills)")

            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


ToolRegistry.register(CapabilitiesTool())
