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

## Commands

| Command | Beschreibung |
|---------|-------------|
| `init` | Swarm-Brain für ein Projekt anlegen |
| `plan` | SPEC.md analysieren → Task-Plan erstellen |
| `run` | Tasks parallel ausführen (sub-Agents) |
| `status` | Fortschritt aller Tasks anzeigen |
| `report` | Ergebnis + erstellte Dateien anzeigen |
| `brain` | Internen Brain-State anzeigen |
| `reset` | Brain löschen (alles zurücksetzen) |

## Workflow

```bash
/herbert-swarm init --project ~/Documents/MeinProjekt
/herbert-swarm plan --project ~/Documents/MeinProjekt
/herbert-swarm run --project ~/Documents/MeinProjekt --parallel 5
```

## Task Phasen

1. **INFRA** — Config-Files (Docker, requirements.txt, package.json)
2. **DATABASE** — Models, Migrations
3. **BACKEND_CORE** — Business Logic
4. **BACKEND_API** — API Routes, Server
5. **FRONTEND** — Pages, Components
6. **TESTING** — Tests

## Brain-Datei

`~/.swarm_brain.json` (oder `<projekt>/.swarm_brain.json`)

```json
{
  "project_name": "MeinProjekt",
  "project_path": "/path/to/project",
  "spec_summary": "...",
  "facts": {
    "task_001_result": {
      "files_created": ["/abs/path/to/file.py"],
      "summary": "Created API endpoints"
    }
  },
  "tasks": {
    "task-001": {
      "id": "task-001",
      "description": "Create FastAPI endpoints",
      "agent_role": "coder",
      "files": ["backend/api/routes.py"],
      "dependencies": [],
      "status": "done",
      "phase": 3
    }
  },
  "phases": ["INFRA", "BACKEND_CORE", "BACKEND_API", "FRONTEND", "TESTING"],
  "current_phase": 3
}
```

## Wie der Planner Tasks erstellt

Der Planner scannt die SPEC.md nach Keywords:

| Keyword-Gruppe | Erkannte Tech-Stack |
|----------------|---------------------|
| FastAPI, Flask, Django, Express | → Backend |
| React, Vue, Svelte, Next.js | → Frontend |
| PostgreSQL, MongoDB, Redis | → Database |
| Docker, Kubernetes | → Docker/Container |
| pytest, Jest, GitHub Actions | → CI/Testing |

**Achtung:** Der Planner erkennt **keine Vanilla-JS/HTML-Projekte**! Für solche Projekte müssen die Tasks manuell in den Brain geschrieben werden.

## Für Agenten (KI)

Wenn du als sub-agent im Swarm arbeitest:

1. Du bekommst einen Prompt mit Task-Beschreibung und Datei-Liste
2. Du sollst ALLE Dateien vollständig implementieren (keine TODOs)
3. Nach Fertigstellung: Brain-Datei lesen → `facts.task_<id>_result` updaten
4. Bei Fehlern: Brain-Datei lesen → `tasks.<id>.status = "failed"` setzen

## Bekannte Probleme / Pitfalls

1. **Planner generiert falsche Tasks für Vanilla-JS**: Lösung — Brain manuell mit korrekten Tasks füllen
2. **Task-Dependencies werden ignoriert**: Alle Tasks einer Phase starten parallel, auch wenn sie Depts haben
3. **Phase 2 startet bevor Phase 1 fertig ist**: Ist tatsächlich so — der Planner hat das Problem
4. **Brain-Datei wird nicht aktualisiert wenn Agent abstürzt**: Manuell brain updaten

## Siehe auch

- [AgentGuide](AgentGuide.md) — Agent-System und sub-agent Aufruf
- [Skills](Skills.md) — Wie Skills generell funktionieren
