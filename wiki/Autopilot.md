# Autopilot

## Was ist Autopilot?

**Autopilot** ist ein projekt-lokales Task-Tracking- und Planungs-System. Es ist KEIN automatischer Agent — es hilft dem Agenten, große Aufgaben in kleine, trackbare Steps zu zerlegen und dann sequentiell abzuarbeiten.

Anders als **Swarm** (Multi-Agent, parallel):
- **Swarm**: Analysiert SPEC.md, erstellt Plan, startet PARALLELE sub-Agents
- **Autopilot**: Agent zerlegt EINE Aufgabe in Tasks, arbeitet sie SEQUENTIELL ab

## Commands

| Command | Beschreibung |
|---------|-------------|
| `/autopilot start [goal]` | Neuen Autopilot für ein Ziel starten |
| `/autopilot plan [task...]` | Task(s) zum aktuellen Plan hinzufügen |
| `/autopilot status` | Status aller Tasks zeigen |
| `/autopilot next` | Nächsten Task zeigen |
| `/autopilot done [id]` | Task als erledigt markieren |
| `/autopilot fail [id] [reason]` | Task als fehlgeschlagen markieren |
| `/autopilot report` | Zusammenfassung des Plans |
| `/autopilot reset` | Plan zurücksetzen |

## Zustände (State)

`~/.cucumber/autopilot/<workspace_hash>/autopilot_state.json`

```json
{
  "version": 1,
  "workspace": "/Users/davidwork/Documents/MeinProjekt",
  "goal": "RetroPixelArcade optimieren",
  "tasks": [
    {
      "id": "task-001",
      "title": "Pong Performance verbessern",
      "detail": "Delta-Time Physics, bessere KI...",
      "agent_role": "coder",
      "priority": 1,
      "status": "done",
      "result": "Pong komplett überarbeitet",
      "started_at": "2026-05-03T10:00:00",
      "completed_at": "2026-05-03T10:15:00"
    }
  ],
  "created_at": "2026-05-03T09:00:00",
  "updated_at": "2026-05-03T10:15:00",
  "last_run_at": "2026-05-03T10:15:00",
  "last_report": "1/3 Tasks erledigt"
}
```

## Typische Workflow

```
User: "/autopilot start EasyROM Docker-Setup"

Agent zerlegt in Tasks:
  1. docker-compose.yml erstellen
  2. Backend Dockerfile erstellen
  3. Frontend Dockerfile erstellen
  4. Healthchecks konfigurieren

→ User bestätigt
→ Agent arbeitet Task für Task ab
```

## Im Gegensatz zu Swarm

| | Swarm | Autopilot |
|---|---|---|
| **Parallele Tasks** | Ja (echte sub-Agents) | Nein (nur ein Agent) |
| **Plan** | Automatisch aus SPEC.md | Manuell vom Agenten |
| **Brain** | Ja (Shared zwischen Agents) | Nein (nur lokaler State) |
| **Use Case** | Große Full-Stack Projekte | Kleine Feature-Implementierungen |
| **Tracking** | `.swarm_brain.json` | `autopilot_state.json` |

## Für Agenten

Wenn du `/autopilot start` aufrufst:
1. Definiere klare Tasks mit Titel, Detail, Priorität
2. Speichere State nach jedem Step
3. Bei Fehler: `fail [id] [reason]`
4. Bei Erfolg: `done [id]`
5. Am Ende: `report` für Zusammenfassung

## Workspace Key

Der Workspace-Key wird aus dem absoluten Pfad berechnet:
```python
sha256("/Users/davidwork/Documents/MeinProjekt")[:16]
→ z.B. "a3f2b1c9d8e7f123"
```

State-Datei: `~/.cucumber/autopilot/<key>/autopilot_state.json`

## Siehe auch

- [AgentGuide](AgentGuide.md) — Agent-System
- [Swarm](Swarm.md) — Multi-Agent Projektplanung
