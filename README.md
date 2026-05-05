# 🥒 CucumberAgent

Ein schlauer, modularer KI-Agent für Terminal, Projekte und Multi-Agent-Workflows.
Er ist bewusst einfach zu bedienen, bleibt aber nachvollziehbar: Du siehst, was er
plant, welche Tools er nutzen will und welche Erinnerungen dauerhaft aktiv sind.

```bash
curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/install.sh | sh
cucumber init
cucumber run
```

## Warum

CucumberAgent soll sich wie ein persönlicher Arbeits-Agent anfühlen, nicht wie ein
loses Prompt-Experiment.

- **Schlau geplant** — Herbert Swarm lässt die KI echte Projektphasen und Tasks planen, statt Keywords zu raten.
- **Vergisst sich nicht** — `personality.md`, gespeicherte Fakten, Pins und Session-Summaries werden als Memory-Contract in jeden Prompt eingebaut.
- **Einfach bedienbar** — `/doctor`, `/what-now`, `/tips`, `/examples`, `/docs` und `/explain-last` führen durch typische Situationen.
- **Sicher nachvollziehbar** — Tool-Aufrufe werden erklärt und brauchen Zustimmung, Auto-Approve ist bewusst aktivierbar.
- **Erweiterbar** — Provider, Tools und YAML-Skills lassen sich sauber ergänzen.

## Schnellstart

### Installieren

```bash
curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/install.sh | sh
```

Der Installer richtet `~/.cucumber/` ein, installiert die lokale CLI und kann ohne
interaktive Eingaben Standardwerte anlegen. Das Update-Script arbeitet bewusst
vorsichtig: Es verweigert lokale Änderungen im Installations-Checkout und nutzt
nur Fast-Forward-Merges.

```bash
curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/update.sh | sh
```

### Einrichten

```bash
cucumber init
```

Der Wizard fragt nach Agent-Name, Sprache, Ton, Begrüßung, Stärken, Nutzerinfos,
Provider, API-Key, Modell und Workspace. Unterstützte Provider: MiniMax,
OpenRouter, DeepSeek und Ollama.

### Starten

```bash
cucumber run
```

Gute erste Befehle im Chat:

```text
/doctor
/what-now
/tips
/examples
/docs memory
/docs swarm
```

## Memory-Garantie

CucumberAgent behandelt Persönlichkeit und Erinnerung als dauerhafte Grundlagen.

- `~/.cucumber/personality/personality.md` ist die unveränderliche Identität des Agenten.
- `~/.cucumber/memory/facts.json` oder `facts.db` enthält dauerhafte Fakten aus `/remember`.
- `/pin <text>` landet als höchstpriorisierter Kontext in jedem Prompt.
- Session-Summaries werden angehängt, nicht überschrieben.
- Kompression darf Chat-Historie verkürzen, aber niemals Persönlichkeit, Pins, Fakten oder dauerhafte Zusammenfassungen löschen.

Kurz gesagt: Der Agent darf klüger werden, ohne seinen Charakter oder wichtige
Erinnerungen unterwegs zu verlieren.

## Herbert Swarm

Herbert Swarm ist der native Multi-Agent-Projektbauer.

```text
/herbert-swarm /path/to/project --parallel 3
/herbert-swarm /path/to/project --dry-run
```

Der Swarm liest `SPEC.md`, scannt das Projektinventar und fragt den konfigurierten
KI-Provider nach einem JSON-Plan mit Phasen, Tasks, Rollen, Dateien und
Abhängigkeiten. CucumberAgent validiert diesen Plan, normalisiert IDs und blockt
unsichere Dateipfade. Es gibt kein Keyword-Raten für die Planung.

## Wichtige Befehle

| Befehl | Zweck |
|--------|-------|
| `cucumber doctor` | Setup, Provider, Wiki, Skills, Tools und Workspace prüfen |
| `cucumber quickstart` | Sicherer Einstieg außerhalb des Chats |
| `cucumber what-now` | Nächsten sinnvollen Schritt vorschlagen |
| `cucumber spec-template` | `SPEC.md` Vorlage für Herbert Swarm ausgeben |
| `/remember key: value` | Fakt dauerhaft speichern |
| `/forget key` | Fakt bewusst löschen |
| `/pin <text>` | Kontext dauerhaft in dieser Session priorisieren |
| `/compact` | Verlauf manuell zusammenfassen |
| `/explain-last` | Letzte Aktion verständlich erklären |

## Projektstruktur

```text
~/.cucumber/
├── config.yaml              # Provider, Modell, Präferenzen
├── personality/
│   └── personality.md       # Name, Ton, Sprache, Charakter
├── user/
│   └── user.md              # Nutzerinfos
├── memory/                  # Logs, Fakten, Session-Summary
├── autopilot/               # Projekt-Autopilot-State
├── custom_tools/            # Hot-reload Python-Tools
└── skills/                  # YAML-Skill-Manifeste
```

```text
cucumber-agent/
├── src/cucumber_agent/
│   ├── agent.py             # Promptbau, Memory-Contract, Provider-Orchestrierung
│   ├── cli.py               # REPL, UX-Helfer, Tool-Freigabe
│   ├── memory.py            # FactsStore, SessionLogger, SummaryStore
│   ├── provider.py          # BaseProvider + Registry
│   ├── tools/               # Shell, Search, Agent, Swarm, Remember, ...
│   └── skills/              # YAML-Skill-System
├── installer/               # install/update/uninstall/init
├── wiki/                    # Ausführliche Doku
└── tests/                   # Regressionstests
```

## Features

- Streaming-Antworten und Thinking-Block-Darstellung
- Multi-Provider: MiniMax, OpenRouter, DeepSeek, Ollama
- Tool-System mit Approval-Flow, Auto-Approve und Smart Retry
- Custom Tools aus `~/.cucumber/custom_tools/*.py`
- YAML-Skills mit Hot-Reload
- Persistente Fakten, Session-Logs, SQLite-Unterstützung
- Persönlichkeit, Fakten, Pins und Zusammenfassungen mit Memory-Contract
- Workspace-Erkennung für Python, Node, Rust und weitere Projekttypen
- Sub-Agent-Tool für rekursive Delegation
- Herbert Swarm für KI-geplante Parallel-Arbeit
- Autopilot für sequenzielle Projektpläne
- UX-Helfer für Diagnose, Beispiele, Tipps, Wiki-Auszüge und nächste Schritte

## Dokumentation

- [Wiki-Start](wiki/README.md)
- [CLI](wiki/CLI.md)
- [Memory & Personality](wiki/Memory.md)
- [Herbert Swarm](wiki/Swarm.md)
- [Configuration](wiki/Configuration.md)
- [Providers](wiki/Providers.md)
- [Architecture](wiki/Architecture.md)
- [AgentGuide](wiki/AgentGuide.md)
- [Skills](wiki/Skills.md)

## Entwicklung

```bash
git clone https://github.com/DavidSchuchert/cucumber-agent.git
cd cucumber-agent
uv sync

uv run ruff format
uv run ruff check
uv run pyright
uv run pytest

uv run cucumber run
```
