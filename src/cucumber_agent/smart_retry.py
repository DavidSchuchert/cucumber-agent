"""Smart tool retry logic - classifies commands and decides auto-retry."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class CommandCategory(Enum):
    """Category of shell command for retry behavior."""

    READ = "read"  # ls, cat, find - safe to auto-retry
    WRITE = "write"  # echo, touch, cp - needs approval on retry
    DESTRUCTIVE = "destructive"  # rm, mv - never auto-retry
    UNKNOWN = "unknown"


@dataclass
class RetryDecision:
    """Decision on whether to auto-retry a failed command."""

    should_retry: bool
    category: CommandCategory
    reason: str
    alternatives: list[str]


# Patterns for command classification
READ_PATTERNS = [
    r"\bls\b",
    r"\bcat\b",
    r"\bhead\b",
    r"\btail\b",
    r"\bwc\b",
    r"\bfind\b",
    r"\bgrep\b",
    r"\bwhich\b",
    r"^\s*file\b",  # file command — only at start to avoid matching filenames
    r"\bstat\b",
    r"\bmd5sum\b",
    r"\bsha256sum\b",
    r"\bgit\s+log\b",
    r"\bgit\s+show\b",
    r"\bgit\s+diff\b",
    r"\bgit\s+status\b",
    r"^\s*open\b",  # macOS open — only at start of command, avoids URLs
    r"\bstat\b",
]

WRITE_PATTERNS = [
    r"\becho\b",
    r"\btouch\b",
    r"\bmkdir\b",
    r"\bcp\b",
    r"\btee\b",
    r"\bwget\b",
    r"\bcurl\b.*-o",
    r"\bnano\b",
    r"\bvim\b",
    r"\bemacs\b",
    r"\bsed\b",
    r"\bawk\b",
]

DESTRUCTIVE_PATTERNS = [
    r"\brm\b",
    r"\brm\s+",
    r"\bmv\b",
    r"\brmdir\b",
    r"\bdd\b",
    r"\bshred\b",
    r"\btruncate\b",
]

# Error patterns that suggest auto-retry is worthwhile
RETRYABLE_ERROR_PATTERNS = [
    r"no such file or directory",
    r"cannot find",
    r"not found",
    r"path does not exist",
    r"enoent",
    r"doesn't exist",
]

# German ↔ English path mappings (macOS default folder names)
PATH_MAPPINGS = {
    # Images
    "bilder": "pictures",
    "pictures": "bilder",
    # Documents
    "dokumente": "documents",
    "documents": "dokumente",
    # Desktop
    "schreibtisch": "desktop",
    "desktop": "schreibtisch",
    # Music
    "musik": "music",
    "music": "musik",
    # Movies / Videos
    "filme": "movies",
    "movies": "filme",
    # Public
    "öffentlich": "public",
    "public": "öffentlich",
    # Downloads (same in both languages, kept for completeness)
    "downloads": "downloads",
}

# Shell-specific syntax patterns that should be treated as READ operations
# (variable expansions, pipeline reads, etc.)
_ZSH_FISH_READ_PATTERNS = [
    r"\bprint\b",  # fish/zsh print
    r"\bprintenv\b",  # environment variable read
    r"\benv\b",  # environment dump
    r"\btype\b",  # fish/zsh: show command type
    r"\bfunctions\b",  # fish: list functions
    r"\bset\b(?!\s+-[eEx])",  # zsh/fish: show vars (not set -e which exits)
    r"\babbr\b",  # fish: list abbreviations
    r"\bpwd\b",  # print working directory
]

_ZSH_FISH_WRITE_PATTERNS = [
    r"\bset\s+-[eEx]\b",  # zsh/fish: set -e (exit on error) — env modification
    r"\bsource\b",  # source / . — modifies shell state
    r"\.\s+\S+",  # POSIX source
    r"\bexport\b",  # export variable
    r"\bunset\b",  # unset variable
    r"\babbr\s+--add\b",  # fish: add abbreviation
    r"\bfuncsave\b",  # fish: persist function to disk
]


def classify_command(command: str) -> CommandCategory:
    """Classify a shell command by its potential for harm.

    Handles bash, zsh, and fish shell-specific syntax.
    Evaluation order: DESTRUCTIVE > READ > WRITE > UNKNOWN
    so that dangerous operations are never silently retried.
    """
    cmd = command.strip().lower()

    # Check destructive first — these never auto-retry
    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, cmd):
            return CommandCategory.DESTRUCTIVE

    # Check read operations (core + shell-specific)
    for pattern in READ_PATTERNS + _ZSH_FISH_READ_PATTERNS:
        if re.search(pattern, cmd):
            return CommandCategory.READ

    # Check write operations (core + shell-specific)
    for pattern in WRITE_PATTERNS + _ZSH_FISH_WRITE_PATTERNS:
        if re.search(pattern, cmd):
            return CommandCategory.WRITE

    return CommandCategory.UNKNOWN


def is_retryable_error(error: str) -> bool:
    """Check if an error message suggests a retry might succeed."""
    error_lower = error.lower()
    for pattern in RETRYABLE_ERROR_PATTERNS:
        if re.search(pattern, error_lower):
            return True
    return False


def extract_paths(command: str) -> list[str]:
    """Extract potential paths from a command."""
    # Match common path patterns
    patterns = [
        r"~/\S+",
        r"/Users/\S+",
        r"/home/\S+",
        r"\./\S+",
        r"\.\./\S+",
    ]

    paths = []
    for pattern in patterns:
        matches = re.findall(pattern, command)
        paths.extend(matches)

    return paths


def suggest_path_alternatives(command: str) -> list[str]:
    """Suggest alternative commands with different paths."""
    alternatives = []
    paths = extract_paths(command)

    for path in paths:
        path_lower = path.lower()
        for german, english in PATH_MAPPINGS.items():
            if german in path_lower:
                alt_path = path_lower.replace(german, english)
                if alt_path != path_lower:
                    alternatives.append(command.replace(path, alt_path, 1))
                    break  # Only suggest first match per path
            elif english in path_lower:
                alt_path = path_lower.replace(english, german)
                if alt_path != path_lower:
                    alternatives.append(command.replace(path, alt_path, 1))
                    break

    return alternatives


def should_auto_retry(command: str, error: str, smart_retry: bool = True) -> RetryDecision:
    """Decide if a failed command should be auto-retried."""
    if not smart_retry:
        return RetryDecision(
            should_retry=False,
            category=classify_command(command),
            reason="Smart retry disabled",
            alternatives=[],
        )

    category = classify_command(command)

    # Destructive commands never auto-retry
    if category == CommandCategory.DESTRUCTIVE:
        return RetryDecision(
            should_retry=False,
            category=category,
            reason="Destructive commands require user approval",
            alternatives=[],
        )

    # Check if error is retryable
    if not is_retryable_error(error):
        return RetryDecision(
            should_retry=False,
            category=category,
            reason=f"Error not retryable: {error[:50]}",
            alternatives=[],
        )

    # For READ operations, suggest path alternatives
    alternatives = []
    if category == CommandCategory.READ:
        alternatives = suggest_path_alternatives(command)

    return RetryDecision(
        should_retry=True,
        category=category,
        reason=f"Safe to retry {category.value} operation after path error",
        alternatives=alternatives,
    )


def generate_retry_command(original: str, alternative: str) -> str:
    """Generate a modified command with an alternative path."""
    # Try to replace path patterns
    patterns = [r"~/\S+", r"/Users/\S+", r"/home/\S+"]

    for pattern in patterns:
        match = re.search(pattern, original)
        if match:
            return original.replace(match.group(0), alternative, 1)

    return alternative
