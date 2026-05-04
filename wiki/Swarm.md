# Herbert Swarm / CucumberSwarm

## Was ist das?

**Herbert Swarm** (intern auch **CucumberSwarm**) ist ein intelligentes Multi-Agent-System, das Full-Stack-Projekte automatisch plant und baut. Es analysiert eine `SPEC.md`, erstellt einen phasen-basierten Task-Plan und führt Tasks parallel mit echten sub-Agents aus.

Das Swarm-Tool ist **nativ in CucumberAgent eingebaut** — kein externes Hermes, kein npm, kein Claude Flow.

## Architektur

```
User: "/herbert-swarm RetroPixelArcade --parallel 10"
        │
        ▼
┌─────────────────────────────────────────────────┐
│  SWARM TOOL (cucumber-agent.tools.swarm)         │
│  Commands: init → plan → run → report            │
│  ├── _cmd_init()     Brain anlegen               │
│  ├── _cmd_plan()     SPEC.md analysieren         │
│  ├── _cmd_run()      Tasks parallel ausführen   │
│  ├── _cmd_status()   Fortschritt zeigen         │
│  ├── _cmd_report()   Ergebnisse zeigen          │
│  └── _cmd_brain()    Internen State zeigen       │
└─────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────┐
│  BRAIN (.swarm_brain.json im Projektordner)     │
│  - facts: Wissen das Agents teilen               │
│  - tasks: Phase, Status, Deps, Files             │
│  - files: Erstellte Dateien                      │
└─────────────────────────────────────────────────┘
        │
        ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Agent 1  │ │ Agent 2  │ │ Agent N  │
│ (async)  │ │ (async)  │ │ (async)  │
└──────────┘ └──────────┘ └──────────┘
```

## Features & Verbesserungen

- **Live-Feedback**: Der Swarm zeigt während der Ausführung live an, was jeder Agent gerade tut (z.B. `[task-001] Nutzt Tool: write_file`).
- **Coding Standards**: Alle Swarm-Agenten folgen strikten Coding-Standards (modularer Code, Fehlerbehandlung, keine Platzhalter).
- **Robuste Timeouts**: Provider-Timeouts wurden auf 5 Minuten erhöht mit automatischen Retries bei Netzwerkfehlern.
- **Sicheres Scanning**: Der Planner ignoriert automatisch große Verzeichnisse wie `.git`, `node_modules` oder `.venv`.

## Commands & Bedienung

Gib einfach `/herbert-swarm` ein, um eine interaktive Hilfe zu erhalten.

| Befehl | Beschreibung |
|---------|-------------|
| `/herbert-swarm <pfad>` | Startet den vollen Zyklus (Init -> Plan -> Run -> Report) |
| `/herbert-swarm status` | Zeigt den aktuellen Fortschritt aller Tasks |
| `/herbert-swarm run` | Setzt die Ausführung fort (z.B. nach einem Abbruch) |
| `/herbert-swarm reset` | Löscht das Swarm-Brain des Projekts (Vorsicht!) |

### Optionen

- `--parallel N`: Anzahl der Agenten, die gleichzeitig arbeiten (Standard: 3)
- `--dry-run`: Simuliert die Ausführung, ohne echte Dateien zu schreiben
- `--spec <pfad>`: Nutzt eine spezifische SPEC-Datei statt der Standard-Datei im Projektordner

## Task Phasen

1. **INFRA** — Config-Files (Docker, requirements.txt, package.json)
2. **DATABASE** — Models, Migrations
3. **BACKEND_CORE** — Business Logic
4. **BACKEND_API** — API Routes, Server
5. **FRONTEND** — Pages, Components
6. **TESTING** — Tests

## Brain-Datei

`~/.swarm_brain.json` (oder `<projekt>/.swarm_brain.json`)

Das "Brain" ist das geteilte Gedächtnis aller Agenten. Hier werden Ergebnisse, erstellte Dateien und der Status jedes Tasks gespeichert.

## Bekannte Probleme / Pitfalls (Fixed!)

- ~~**Planner hängt bei großen Projekten**~~: Behoben durch Verzeichnis-Filter.
- ~~**Absturz bei paralleler Ausführung**~~: Behoben durch Entfernung von globalem State (Race Conditions).
- ~~**Keine Info was passiert**~~: Behoben durch Live-Feedback-System.

## Siehe auch

- [AgentGuide](AgentGuide.md) — Agent-System und sub-agent Aufruf
- [Skills](Skills.md) — Wie Skills generell funktionieren
