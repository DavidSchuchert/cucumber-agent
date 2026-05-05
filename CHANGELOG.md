# Changelog

All notable changes to CucumberAgent are documented here.

---

## [Unreleased] — 2026-05-05

### Added
- **MiniMax Token Plan MCP integration** — Added a dependency-free stdio MCP client for `minimax-coding-plan-mcp`, enabling MiniMax-backed `web_search` and `understand_image`.
- **MiniMax MCP doctor check** — `cucumber doctor` now reports whether `uvx`, `MINIMAX_API_KEY` and MiniMax MCP routing are ready when MiniMax is active.
- **Memory & Identity Contract** — Every model call now includes an explicit contract that protects the immutable personality, persistent facts, pinned context and durable summaries from accidental loss during long sessions or compression.
- **Persistent facts fallback** — The agent now reloads facts directly from the configured `FactsStore` when building prompts, so stored memories still appear even if live session metadata is missing.
- **Beginner-friendly UX commands** — Added top-level and REPL helpers such as `doctor`, `quickstart`, `what-now`, `tips`, `examples`, `docs`, `shortcuts` and `spec-template`.
- **`/docs memory` topic** — The CLI can now show the new Memory & Personality wiki page directly from the chat or terminal.
- **Installer regression tests** — Added coverage for safer installer/update behavior.
- **Memory regression tests** — Added tests for the identity contract, persistent facts injection, pinned context, summaries and TUI compression.
- **New wiki page: `wiki/Memory.md`** — Documents the memory guarantee, file locations, commands and developer-facing implementation points.

### Changed
- **Image understanding routing** — `understand_image` now tries MiniMax MCP first and falls back to the legacy MiniMax chat vision path when MCP is not explicitly required.
- **Web search routing** — `web_search` can use MiniMax MCP in `auto`/`always` mode while keeping DuckDuckGo as the auto-mode fallback.
- **Herbert Swarm planning** — Swarm planning is now AI-generated from `SPEC.md` and project inventory instead of keyword-based stack guessing. CucumberAgent validates and normalizes the provider's JSON plan.
- **README overhaul** — Reworked the README into a user-first quickstart with Memory-Garantie, Herbert Swarm explanation, important commands and development checks.
- **Wiki refresh** — Updated Architecture, CLI, Configuration, Providers, AgentGuide, Swarm and the wiki index to match the current UX and memory behavior.
- **Installer and updater hardening** — Install/update/uninstall scripts were made safer and more idempotent. The updater refuses dirty installation checkouts and uses fast-forward updates instead of destructive resets.
- **Provider registration** — MiniMax, OpenRouter, DeepSeek and Ollama setup paths are now aligned between wizard, config and provider registry.
- **Provider cache behavior** — Provider instances are recreated when constructor kwargs change, avoiding stale API key/base URL/model reuse.
- **TUI compression** — TUI summaries now append to existing summaries instead of replacing them.

### Fixed
- **Memory loss risk in prompt building** — Active facts, pins and historical summaries are now explicitly preserved in built messages.
- **Documentation lookup** — Wiki paths now resolve more reliably across local development, installed checkouts and custom install directories.
- **Installer provider mismatch** — The setup wizard no longer offers providers that are not registered in code.
- **Unsafe update behavior** — The updater no longer uses `git reset --hard`.

### Verified
- `uv run ruff check`
- `uv run ruff format --check`
- `uv run pyright`
- `uv run pytest` (`269 passed`)
- `uv run cucumber docs memory`
- `uv run cucumber doctor`

---

## [Unreleased] — 2026-05-03

### Added
- **Multi-line input** — End any prompt line with `\` to continue on the next line. The prompt switches to `  ...` indicator; lines accumulate until a line without `\` is sent. Useful for pasting code, JSON, or structured multi-step prompts.
- **`/compact`** — Manually trigger context compression at any time without waiting for the auto-trigger threshold. Summarises messages older than `summarize_keep_recent` and appends to the persistent summary store on disk.
- **`/pin <text>`** — Pin arbitrary text into the operational system prompt. Pinned context survives context compression (stored in `session.metadata["pinned"]` and injected as Tier-1 context in `agent._build_messages`). `/pin` without arguments lists all current pins.
- **`/unpin <nr>`** — Remove a pinned entry by index.
- **`/cost`** — Show per-session token counts (input / output / total / API calls) and an estimated USD cost based on known provider pricing (MiniMax, OpenRouter, DeepSeek, Ollama).
- **`/autoapprove`** — Toggle session-wide tool auto-approve. When active, all tool calls — including those made by sub-agents — execute without any prompt.
- **Tool approval `[4] Alle akzeptieren`** — One-click session-wide auto-approve from the tool approval dialog. Consistent across main agent and sub-agents.
- **Sub-agent auto-approve propagation** — When `_auto_approve_session` is enabled, the flag is synced to the sub-agent tool module so sub-agent tool calls also skip approval prompts.
- **Sub-agent menu fixed** — `[4]` in the sub-agent dialog now means "Alle akzeptieren" (was incorrectly "Abbrechen"). Abort is now `[5]`.
- **`calculator` tool** — Safe AST-based mathematical expression evaluator. Supports `+−×÷**//`, functions (`sqrt`, `sin`, `cos`, `log`, `factorial`, `gcd`, …) and constants (`pi`, `e`, `tau`). Never uses `eval()`.
- **`/context`** — Already existed but was missing from the tab-completer; now included.
- **`/tools`** — Also added to the tab-completer.

### Fixed
- **`datetime.utcnow()` deprecation** (`session.py`) — All three call sites replaced with `datetime.now(UTC)`. Eliminates 10 deprecation warnings in the test suite.
- **`minimax.py` — `import re` at module level** — Was imported inside `_parse_response()` on every API call; moved to module level.
- **`minimax.py` — stream retry** — `stream()` now retries on HTTP 529 (provider overloaded) with exponential back-off, consistent with `complete()`.
- **`cli.py` — personality update TypeError** — When the AI responds with `KEINE_VERBESSERUNG`, `parse_personality_update` returns `(None, explanation)`. The old code called `apply_personality_update(None, config)` causing `TypeError: argument of type 'NoneType' is not iterable`. Now checks `update_params is not None` before applying.
- **`cli.py` — inline imports removed** — `from cucumber_agent.session import Message, Role` and `import re` were imported inside method bodies on every invocation; promoted to module level.
- **`memory.py` — duplicate separator** — `FactsStore.add_from_text` iterated over `(": ", " = ", ": ")` — the third `": "` was dead code (identical to first). Removed.
- **`agent.py` — tiktoken encoding cached** — `estimate_tokens()` previously called `tiktoken.get_encoding("cl100k_base")` on every call; now cached as a module-level singleton via `_get_tiktoken_encoding()`.
- **`smart_retry.py` — `\bfile\b` false positive** — The pattern matched `file.zip` inside curl URLs, causing `curl -o file.zip` to be classified as a `READ` command. Anchored to `^\s*file\b`.
- **`cli.py` — context compression appends** — `_maybe_compress_context` previously overwrote the existing summary; now appends with a `[Neuere Zusammenfassung:]` header.
- **DDG web search regex** — DuckDuckGo changed its HTML and stopped using `rel="nofollow"`. Regex updated to `[^>]+class="result__a"[^>]+` (attribute-order-agnostic).

### Changed
- **MiniMax provider** — Normalises base URL: strips `/anthropic` suffix and replaces with `/v1` automatically, so old config files with the Anthropic-compat URL still work.
- **Memory system — SQLite** — `FactsStore` is now a factory: when the facts file path ends with `.db`, a `SQLiteFactsStore` is returned with identical API but SQLite backend. `SessionLogger` gains a `structured=True` flag for writing to `exchanges.db` alongside markdown logs.
- **3-Tier Memory Architecture** — `agent._build_messages()` now assembles messages in strict tiers: Tier 0 = immutable Core Identity block (reloaded from `personality.md` on every call), Tier 1 = operational context + pinned items, Tier 2 = historical summary, Tier 3 = recent messages. Personality content is explicitly excluded from compression prompts.

---

## [v1.0] — Initial release

- Core agent framework: `Agent`, `Session`, `Message`, `Role`
- Provider system: `BaseProvider` ABC + `ProviderRegistry`
- Providers: MiniMax, OpenRouter, Ollama
- Tool system: `BaseTool`, `ToolRegistry`, auto-approve flag
- Built-in tools: `shell`, `search`, `web_search`, `web_reader`, `agent`, `create_tool`
- Skill system: YAML manifests with `{args}` expansion
- Memory: `SessionLogger` (markdown daily logs), `FactsStore` (JSON)
- `smart_retry`: classifies shell commands as READ/WRITE/DESTRUCTIVE
- Personality system: `personality.md` → system prompt
- `cucumber init` setup wizard
- `cucumber run` REPL with prompt_toolkit + rich output
- One-line installer (`curl | sh`)
