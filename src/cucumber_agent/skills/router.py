"""Skill Router — autonomous skill activation based on user input context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cucumber_agent.skills.loader import Skill

if TYPE_CHECKING:
    pass

# Confidence thresholds
MIN_CONFIDENCE = 0.5
CAP_MAX_SKILLS = 5  # never inject more than this many skills per turn


@dataclass
class SkillMatch:
    """A matched skill with confidence score and match reason."""

    skill: Skill
    confidence: float
    reason: str  # human-readable why this matched

    def __repr__(self) -> str:
        return f"SkillMatch({self.skill.name!r}, conf={self.confidence:.2f}, {self.reason!r})"


class MatchEngine:
    """Keyword + URL pattern matching engine for skill triggers."""

    def __init__(self, skills: list[Skill]) -> None:
        self.skills = skills
        self._build_index()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def match(self, user_input: str, context: dict | None = None) -> list[SkillMatch]:
        """Return skills sorted by confidence (highest first), capped at CAP_MAX_SKILLS."""
        scores: list[SkillMatch] = []

        input_lower = user_input.lower()
        input_words = set(re.findall(r"\w+", input_lower))

        for skill in self.skills:
            score, reason = self._score_skill(skill, input_lower, input_words)
            if score >= MIN_CONFIDENCE:
                scores.append(SkillMatch(skill=skill, confidence=score, reason=reason))

        scores.sort(key=lambda x: x.confidence, reverse=True)
        return scores[:CAP_MAX_SKILLS]

    # ------------------------------------------------------------------
    # Scoring internals
    # ------------------------------------------------------------------

    def _score_skill(
        self, skill: Skill, input_lower: str, input_words: set[str]
    ) -> tuple[float, str]:
        """Score a single skill. Returns (confidence, reason)."""

        # ── 1. URL / domain patterns ──────────────────────────────────
        url_score, url_reason = self._match_url_patterns(skill, input_lower)
        if url_score > 0:
            return url_score, url_reason

        # ── 2. Trigger keyword matching ──────────────────────────────
        return self._match_triggers(skill, input_lower, input_words)

    def _match_triggers(
        self, skill: Skill, input_lower: str, input_words: set[str]
    ) -> tuple[float, str]:
        """Match against the skill's triggers list."""
        triggers = getattr(skill, "triggers", None)
        if not triggers:
            return 0.0, ""

        best_score = 0.0
        best_reason = ""

        for trigger in triggers:
            trigger_lower = trigger.lower()
            trigger_words = set(re.findall(r"\w+", trigger_lower))

            # Exact match: trigger phrase appears as a meaningful phrase in input.
            # For short single-word triggers (≤3 chars), use word boundaries to avoid
            # false positives (e.g. "pr" inside "espresso", "git" inside "github").
            # Multi-word triggers use plain substring match — they rarely false-trigger.
            exact_match = False
            if trigger_words:
                if len(trigger_words) == 1 and len(trigger_lower) <= 3:
                    # Short single-word trigger → require word boundary
                    exact_match = bool(re.search(rf"\b{re.escape(trigger_lower)}\b", input_lower))
                else:
                    # Multi-word or longer single-word → plain substring is safe
                    exact_match = trigger_lower in input_lower

            if exact_match:
                # Prefer longer triggers (more specific)
                score = min(1.0, len(trigger_lower) / 30 + 0.5)
                if score > best_score:
                    best_score = score
                    best_reason = f"trigger exact: {trigger!r} found in input"

            # All trigger words found in input (partial match)
            elif trigger_words and trigger_words <= input_words:
                score = 0.7 + min(0.2, len(trigger_words) * 0.05)
                if score > best_score:
                    best_score = score
                    best_reason = f"all trigger words found: {list(trigger_words)}"

            # Partial word overlap (at least half the trigger words)
            elif trigger_words:
                overlap = len(trigger_words & input_words)
                if overlap >= len(trigger_words) * 0.5:
                    score = 0.4 + overlap * 0.1
                    if score > best_score:
                        best_score = score
                        best_reason = (
                            f"partial overlap ({overlap}/{len(trigger_words)}): {trigger!r}"
                        )

        return best_score, best_reason

    # -------------------------------------------------------------------------
    # URL / domain pattern matching
    # -------------------------------------------------------------------------

    # Generic URL patterns — boost skills that already matched via keywords.
    # These NEVER trigger domain-relevance checks (would cause false positives).
    _GENERIC_URL_PATTERNS: list[tuple[str, float, str]] = [
        (r"https?://[^\s]+", 0.3, "URL present"),
        (r"www\.[^\s]+", 0.25, "www URL present"),
    ]

    # Domain-specific patterns — these DO check skill.trigger relevance.
    _DOMAIN_PATTERNS: list[tuple[str, float, str]] = [
        (r"github\.com", 0.8, "github.com domain"),
        (r"gitlab\.com", 0.8, "gitlab.com domain"),
        (r"arxiv\.org", 0.9, "arxiv.org domain"),
        (r"pubmed\.ncbi\.nlm\.nih\.gov", 0.95, "pubmed domain"),
        (r"doi\.org", 0.9, "DOI detected"),
        (r"\barxiv\b", 0.7, "arxiv mentioned"),
        (r"\bpubmed\b", 0.7, "pubmed mentioned"),
        (r"\bdocker\b", 0.6, "docker mentioned"),
        (r"\bdocker-compose\b", 0.6, "docker-compose mentioned"),
        (r"\bkubernetes\b", 0.6, "kubernetes mentioned"),
        (r"\bnginx\b", 0.6, "nginx mentioned"),
        (r"\bapache\b", 0.6, "apache mentioned"),
        (r"journalctl", 0.7, "systemd journal mentioned"),
        (r"\bsystemd\b", 0.5, "systemd mentioned"),
        (r"\bapt\b|\bdnf\b|\byum\b", 0.5, "package manager mentioned"),
        (r"launchctl", 0.7, "macOS launchctl mentioned"),
        (r"\bhomebrew\b", 0.6, "homebrew mentioned"),
        (r"\bmdfind\b", 0.7, "macOS spotlight mentioned"),
        (r"\bplutil\b", 0.7, "macOS plutil mentioned"),
        (r"\bsqlite\b|\bpostgres\b|\bmysql\b", 0.6, "database mentioned"),
    ]

    def _match_url_patterns(self, skill: Skill, input_lower: str) -> tuple[float, str]:
        """Match URL patterns and domain indicators.

        Domain-specific patterns are checked first. If matched, skill trigger
        relevance is evaluated and a meaningful score is returned.

        Generic URL patterns (https://, www.) are checked second — they only
        boost skills that already matched via keyword triggers (small additive
        bonus), they never score a skill on their own.
        """
        triggers = getattr(skill, "triggers", None)
        if not triggers:
            return 0.0, ""
        trigger_text = " ".join(triggers).lower()

        # 1. Domain-specific patterns — check trigger relevance
        for pattern, score, reason in self._DOMAIN_PATTERNS:
            if re.search(pattern, input_lower):
                trigger_score = self._domain_relevance(skill, pattern, trigger_text)
                if trigger_score > 0:
                    return score * trigger_score, f"{reason} + relevant trigger"

        # 2. Generic URL patterns — only add small bonus if skill already
        #    matched via keyword triggers (trigger_score > 0 means triggers exist
        #    and some overlap was found in _match_triggers already)
        best_generic = 0.0
        for pattern, score, reason in self._GENERIC_URL_PATTERNS:
            if re.search(pattern, input_lower):
                # Only add bonus if skill has meaningful triggers
                if triggers:
                    best_generic = max(best_generic, score)

        return best_generic, "URL present + trigger" if best_generic > 0 else ""

    def _domain_relevance(self, skill: Skill, pattern: str, trigger_text: str) -> float:
        """Check if a domain pattern is relevant to this skill's triggers.

        Returns 1.0 if the matched domain is relevant to the skill's trigger keywords,
        0.0 otherwise. This prevents generic URL patterns from falsely boosting
        unrelated skills.
        """
        # domain → trigger keywords that indicate relevance to this domain.
        # NOTE: keep keywords specific (not generic words like "http", "web")
        # that would match any URL pattern including unrelated domains.
        domain_relevance: dict[str, list[str]] = {
            "github": [
                "github",
                "git",
                "pr",
                "pull request",
                "repo",
                "branch",
                "commit",
                "actions",
            ],
            "gitlab": ["gitlab", "git", "repo", "ci", "pipeline", "merge request"],
            "arxiv": ["arxiv", "paper", "research", "academic", " preprint", " preprint"],
            "pubmed": [
                "pubmed",
                "medline",
                "biomedical",
                "medical",
                "doi",
                "clinical",
                "pmc",
                "ncbi",
            ],
            "docker": [
                "docker",
                "container",
                "dockerfile",
                "image",
                "docker-compose",
                "registry",
                "pod",
            ],
            "kubernetes": ["kubernetes", "k8s", "pod", "deployment", "helm", "cluster", "kubectl"],
            "nginx": ["nginx", "reverse proxy", "load balancer"],
            "apache": ["apache", "httpd", "htaccess", "web server"],
            "journalctl": ["journal", "journalctl", "systemd", "syslog", "log"],
            "systemd": ["systemd", "service", " systemctl", "daemon", "unit", " journal"],
            "apt": ["apt", "package", "debian", "ubuntu", "yum", "dnf"],
            "launchctl": ["launchctl", "launchd", "plist", "launchagent", "launchdaemon"],
            "homebrew": ["homebrew", "brew", "macos", "cask"],
            "mdfind": ["spotlight", "mdfind", "macos", "metadata"],
            "plutil": ["plist", "preferences", "defaults", "macos"],
            "database": [
                "database",
                "db",
                "sql",
                "sqlite",
                "postgres",
                "mysql",
                "mongodb",
                "redis",
            ],
        }

        for domain, keywords in domain_relevance.items():
            if domain in pattern.lower():
                # Exact domain in pattern → check if any domain keyword in triggers
                if any(kw in trigger_text for kw in keywords):
                    return 1.0
                return 0.0  # domain present but skill has unrelated triggers

        return 0.0

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def _build_index(self) -> None:
        """Build trigger word → skills index for fast lookup."""
        # Currently we scan all skills in match() — index building is
        # optional future optimization since skill count stays small (<100).
        pass


class SkillRouter:
    """Routes user input to relevant skills and formats them for injection."""

    def __init__(self, skills: list[Skill]) -> None:
        self._engine = MatchEngine(skills)

    def get_matching_skills(self, user_input: str, context: dict | None = None) -> list[Skill]:
        """Return matched skills (highest confidence first), empty list if none."""
        if not user_input.strip():
            return []
        matches = self._engine.match(user_input, context)
        return [m.skill for m in matches]

    def get_matching_skills_with_scores(
        self, user_input: str, context: dict | None = None
    ) -> list[SkillMatch]:
        """Return matched skills with confidence scores — useful for debugging."""
        if not user_input.strip():
            return []
        return self._engine.match(user_input, context)

    def format_for_system_prompt(self, matched_skills: list[Skill]) -> str:
        """Format matched skills into a string for system-prompt injection."""
        if not matched_skills:
            return ""

        blocks = [
            "[AUTOMATISCH AKTIVIERT — diese Skills sind für die aktuelle Aufgabe relevant. Nutze ihre Anweisungen aus dem `prompt`-Abschnitt. Wenn die Aufgabe ohne diese Skills besser gelöst werden kann, ignoriere sie.]",
            "",
        ]

        for skill in matched_skills:
            prompt_content = skill.prompt.strip() if skill.prompt else skill.description
            blocks.append(f"### Skill: {skill.name} ({skill.command})")
            blocks.append(f"{prompt_content}")
            blocks.append("")

        return "\n".join(blocks)
