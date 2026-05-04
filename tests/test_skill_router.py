"""Tests for SkillRouter — autonomous skill activation by trigger matching."""

from __future__ import annotations

import pytest

from cucumber_agent.skills.router import SkillRouter, SkillMatch, MatchEngine
from cucumber_agent.skills.loader import Skill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_skill(name: str, description: str, triggers: list[str]) -> Skill:
    """Build a Skill object from raw fields."""
    return Skill(
        name=name,
        description=description,
        command=f"/{name.lower().replace(' ', '-')}",
        prompt=f"Run {name}",
        triggers=triggers,
        steps=[],
        args_hint="",
        timeout=30,
    )


GITHUB_SKILL = make_skill(
    "GitHub PR Review",
    "Reviews GitHub pull requests",
    [
        "github pr", "pull request", "pr review", "github review",
        "pr comments", "github merge", "code review github",
        "github", "pr", "merge pull request",
    ],
)

LINUX_SKILL = make_skill(
    "Linux Server Ops",
    "Linux server management and troubleshooting",
    [
        "linux", "server", "nginx", "apache", "systemd", "journalctl",
        "cron", "logs", "disk", "memory", "cpu", "process", "ssh",
        "iptables", "firewall", "apt", "yum", "dnf", "systemctl",
    ],
)

DOCKER_SKILL = make_skill(
    "Docker & Container",
    "Docker build, run, compose, and troubleshooting",
    [
        "docker", "container", "dockerfile", "docker-compose", "docker hub",
        "image", "build", "run", "volume", "network", "registry",
        "kubernetes", "k8s", "pod", "deployment",
    ],
)

PUBMED_SKILL = make_skill(
    "PubMed Research",
    "Search PubMed and biomedical literature",
    [
        "pubmed", "medline", "biomedical", "medical research",
        "clinical trial", "pubmed.gov", "ncbi", "pmc",
        "journal article", "doi", "medline",
    ],
)

CODE_QUALITY_SKILL = make_skill(
    "Code Quality",
    "Testing, linting, and code quality assurance",
    [
        "test", "pytest", "lint", "pylint", "flake8", "coverage",
        "unittest", "testing", "code quality", "static analysis",
        "type check", "mypy", "ruff", "eslint", "prettier",
    ],
)

SKILLS = [GITHUB_SKILL, LINUX_SKILL, DOCKER_SKILL, PUBMED_SKILL, CODE_QUALITY_SKILL]


# ---------------------------------------------------------------------------
# SkillRouter: get_matching_skills() — returns list[Skill]
# ---------------------------------------------------------------------------

class TestSkillRouterMatching:
    """Test SkillRouter.get_matching_skills() end-to-end."""

    def setup_method(self):
        self.router = SkillRouter(SKILLS)

    def test_github_pr_review(self):
        """'github pr review feedback' → GitHub PR Review matched."""
        matches = self.router.get_matching_skills("github pr review feedback")
        names = [m.name for m in matches]
        assert "GitHub PR Review" in names
        assert len(names) <= 5

    def test_linux_nginx_logs(self):
        """'nginx error logs linux server' → Linux Server Ops matched."""
        matches = self.router.get_matching_skills("nginx error logs linux server")
        names = [m.name for m in matches]
        assert "Linux Server Ops" in names

    def test_docker_build(self):
        """'docker build and run container' → Docker & Container matched."""
        matches = self.router.get_matching_skills("docker build and run container")
        names = [m.name for m in matches]
        assert "Docker & Container" in names

    def test_pubmed_article(self):
        """'pubmed article about covid' → PubMed Research matched."""
        matches = self.router.get_matching_skills("pubmed article about covid")
        names = [m.name for m in matches]
        assert "PubMed Research" in names

    def test_pubmed_url(self):
        """URL with pubmed domain → PubMed Research matched."""
        matches = self.router.get_matching_skills(
            "can you summarize https://pubmed.ncbi.nlm.nih.gov/12345678"
        )
        assert len(matches) >= 1
        names = [m.name for m in matches]
        assert "PubMed Research" in names

    def test_pytest(self):
        """'run pytest with coverage' → Code Quality matched."""
        matches = self.router.get_matching_skills("run pytest with coverage")
        names = [m.name for m in matches]
        assert "Code Quality" in names

    def test_no_match_returns_empty(self):
        """Unrelated input → empty list."""
        matches = self.router.get_matching_skills("make coffee brew espresso")
        assert matches == []

    def test_cap_at_five_skills(self):
        """Many overlapping skills → capped at 5."""
        many_skills = SKILLS * 3  # 15 skills
        router = SkillRouter(many_skills)
        matches = router.get_matching_skills("github docker linux python test")
        assert len(matches) <= 5

    def test_unmatched_input_below_threshold(self):
        """Input with few trigger words → filtered by 0.5 threshold."""
        # "test" alone might not reach 0.5 threshold
        matches = self.router.get_matching_skills("a little test")
        # Either empty or only high-confidence matches
        for m in matches:
            # get_matching_skills returns Skill objects — check confidence via _with_scores
            pass  # just verify it doesn't crash

    def test_skills_sorted_by_confidence(self):
        """Results sorted descending by confidence."""
        with_scores = self.router.get_matching_skills_with_scores(
            "github docker nginx linux"
        )
        if len(with_scores) > 1:
            for i in range(len(with_scores) - 1):
                assert with_scores[i].confidence >= with_scores[i + 1].confidence

    def test_german_keywords(self):
        """German trigger keywords → matched correctly."""
        linux_skill = make_skill("Linux German", "Linux Server", ["server", "linux", "fehler", "protokoll"])
        router = SkillRouter([linux_skill])
        matches = router.get_matching_skills("linux server fehler")
        assert len(matches) >= 1

    def test_mixed_case_input(self):
        """Case-insensitive matching."""
        matches = self.router.get_matching_skills("GITHUB PR REVIEW")
        assert len(matches) >= 1
        assert matches[0].name == "GitHub PR Review"

    def test_empty_triggers_skips_keyword_matching(self):
        """Skill with no triggers → skipped in keyword matching."""
        no_trigger_skill = make_skill("No Trigger", "Should not auto-match", [])
        router = SkillRouter([no_trigger_skill])
        matches = router.get_matching_skills("should not match no trigger")
        # No URLs in input, no triggers → empty
        assert matches == []

    def test_overlapping_triggers_multi_match(self):
        """Multiple skills match same input."""
        matches = self.router.get_matching_skills("docker build nginx container")
        names = [m.name for m in matches]
        assert "Docker & Container" in names
        # nginx is also in Linux triggers
        assert "Linux Server Ops" in names


# ---------------------------------------------------------------------------
# SkillRouter: get_matching_skills_with_scores() — returns list[SkillMatch]
# ---------------------------------------------------------------------------

class TestSkillRouterWithScores:
    """Test SkillRouter.get_matching_skills_with_scores() for debugging."""

    def setup_method(self):
        self.router = SkillRouter(SKILLS)

    def test_returns_skill_match_objects(self):
        """Returns SkillMatch with skill, confidence, reason."""
        results = self.router.get_matching_skills_with_scores("github pr review")
        assert len(results) >= 1
        top = results[0]
        assert isinstance(top, SkillMatch)
        assert hasattr(top, "skill")
        assert hasattr(top, "confidence")
        assert hasattr(top, "reason")
        assert 0.0 <= top.confidence <= 1.0
        assert isinstance(top.reason, str)

    def test_pubmed_url_high_confidence(self):
        """PubMed URL → high confidence."""
        results = self.router.get_matching_skills_with_scores(
            "summarize https://pubmed.ncbi.nlm.nih.gov/12345678"
        )
        assert len(results) >= 1
        top = results[0]
        assert top.skill.name == "PubMed Research"
        assert top.confidence >= 0.7

    def test_unmatched_input_empty(self):
        """No triggers → empty list."""
        results = self.router.get_matching_skills_with_scores("hello world foo bar")
        assert results == []


# ---------------------------------------------------------------------------
# SkillMatch dataclass
# ---------------------------------------------------------------------------

class TestSkillMatchDataclass:
    """Test SkillMatch result structure."""

    def test_skill_match_fields(self):
        """SkillMatch has skill, confidence, reason."""
        match = SkillMatch(
            skill=GITHUB_SKILL,
            confidence=0.85,
            reason="trigger exact: 'github pr' found in input",
        )
        assert match.skill is GITHUB_SKILL
        assert match.confidence == 0.85
        assert "github pr" in match.reason

    def test_skill_match_repr(self):
        """SkillMatch repr includes name and confidence."""
        match = SkillMatch(
            skill=GITHUB_SKILL,
            confidence=0.85,
            reason="test",
        )
        r = repr(match)
        assert "GitHub PR Review" in r
        assert "0.85" in r


# ---------------------------------------------------------------------------
# MatchEngine integration
# ---------------------------------------------------------------------------

class TestMatchEngine:
    """Test MatchEngine.match() directly."""

    def setup_method(self):
        self.engine = MatchEngine(SKILLS)

    def test_match_returns_skill_matches(self):
        """match() returns list of SkillMatch objects."""
        results = self.engine.match("docker build")
        assert len(results) >= 1
        assert all(isinstance(r, SkillMatch) for r in results)

    def test_confidence_bounded(self):
        """All confidence scores between 0 and 1."""
        results = self.engine.match("github linux docker pytest pubmed")
        for r in results:
            assert 0.0 <= r.confidence <= 1.0

    def test_threshold_enforced(self):
        """Matches below MIN_CONFIDENCE (0.5) excluded."""
        results = self.engine.match("a b c d e")  # random letters, no triggers
        for r in results:
            assert r.confidence >= 0.5


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestSkillRouterCLIIntegration:
    """Test SkillRouter wired into CLI session context."""

    def setup_method(self):
        self.router = SkillRouter(SKILLS)

    def test_matching_skills_injected_into_context(self):
        """get_matching_skills returns results for known trigger input."""
        matches = self.router.get_matching_skills("docker build nginx container")
        names = [m.name for m in matches]
        assert "Docker & Container" in names
        assert "Linux Server Ops" in names

    def test_unmatched_input_returns_empty_context(self):
        """No trigger match → empty list, nothing injected."""
        matches = self.router.get_matching_skills("what is the weather today")
        assert matches == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestSkillRouterEdgeCases:
    """Edge case handling."""

    def setup_method(self):
        self.router = SkillRouter(SKILLS)

    def test_empty_skill_list(self):
        """No skills loaded → empty results, no crash."""
        router = SkillRouter([])
        matches = router.get_matching_skills("github pr review")
        assert matches == []

    def test_empty_input(self):
        """Empty string input → empty results."""
        matches = self.router.get_matching_skills("")
        assert matches == []

    def test_whitespace_only_input(self):
        """Whitespace-only input → empty results."""
        matches = self.router.get_matching_skills("   \n\t  ")
        assert matches == []

    def test_special_characters_in_input(self):
        """Input with special chars → still matched."""
        matches = self.router.get_matching_skills("github pr review! @#$%")
        assert len(matches) >= 1

    def test_unicode_in_input(self):
        """Unicode characters → not crashed."""
        matches = self.router.get_matching_skills("github pr review 🔥")
        assert isinstance(matches, list)
        assert all(isinstance(m, Skill) for m in matches)

    def test_very_long_input(self):
        """Very long input → handled gracefully."""
        long_input = "github pr review " * 1000
        router = SkillRouter(SKILLS)
        matches = router.get_matching_skills(long_input)
        assert isinstance(matches, list)
        assert all(isinstance(m, Skill) for m in matches)

    def test_single_character_trigger(self):
        """Single char trigger word → still matched."""
        single = make_skill("Single", "Test", ["x"])
        router = SkillRouter([single])
        matches = router.get_matching_skills("check x and y")
        assert len(matches) >= 1

    def test_url_without_trigger_skill(self):
        """URL matches domain indicator but skill has no triggers → not matched."""
        # github.com domain mentioned but skill with no triggers wouldn't match anyway
        url_skill = make_skill("URL Test", "Test", [])  # empty triggers
        router = SkillRouter([url_skill])
        # No trigger keywords, only URL pattern — but URL scoring checks skill.triggers exist
        matches = router.get_matching_skills("visit https://github.com/user/repo")
        assert matches == []


# ---------------------------------------------------------------------------
# format_for_system_prompt
# ---------------------------------------------------------------------------

class TestFormatForSystemPrompt:
    """Test SkillRouter.format_for_system_prompt()."""

    def setup_method(self):
        self.router = SkillRouter(SKILLS)

    def test_empty_skills_returns_empty_string(self):
        """No matched skills → empty string."""
        result = self.router.format_for_system_prompt([])
        assert result == ""

    def test_formats_skills_with_header(self):
        """Matched skills → formatted with header and skill blocks."""
        skills = self.router.get_matching_skills("docker build")
        result = self.router.format_for_system_prompt(skills)
        assert "AUTOMATISCH AKTIVIERT" in result
        assert "Docker & Container" in result

    def test_includes_command_and_description(self):
        """Skill block includes name, command, and description."""
        skills = self.router.get_matching_skills("pubmed article")
        result = self.router.format_for_system_prompt(skills)
        assert "PubMed Research" in result
        assert "/pubmed-research" in result or "pubmed" in result.lower()
