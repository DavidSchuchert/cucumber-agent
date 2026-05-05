# Herbert Swarm / CucumberSwarm

## Was ist das?

**Herbert Swarm** (intern auch **CucumberSwarm**) ist ein intelligentes Multi-Agent-System, das Projekte automatisch plant und baut. Es lässt die konfigurierte KI eine `SPEC.md` und das vorhandene Projektinventar analysieren, speichert daraus einen phasen-basierten Task-Plan und führt Tasks parallel mit echten sub-Agents aus.

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
│  ├── _cmd_plan()     KI-Plan aus SPEC.md bauen   │
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

- **AI-first Planning**: Der Planner erzeugt Phasen und Tasks per konfigurierter KI. Es gibt keine fachliche Keyword-Heuristik, die Stack oder Phasen errät.
- **Live-Feedback**: Der Swarm zeigt während der Ausführung live an, was jeder Agent gerade tut (z.B. `[task-001] Nutzt Tool: write_file`).
- **Coding Standards**: Alle Swarm-Agenten folgen strikten Coding-Standards (modularer Code, Fehlerbehandlung, keine Platzhalter).
- **Robuste Timeouts**: Provider-Timeouts wurden auf 5 Minuten erhöht mit automatischen Retries bei Netzwerkfehlern.
- **Sicheres Scanning**: Der Planner ignoriert automatisch große Verzeichnisse wie `.git`, `node_modules` oder `.venv`.
- **Plan-Validierung**: CucumberAgent normalisiert KI-Ausgaben, blockiert absolute Pfade/`..`, mappt Dependencies auf interne Task-IDs und nutzt nur gültige Rollen.

## Commands & Bedienung

Gib einfach `/herbert-swarm` ein, um eine interaktive Hilfe zu erhalten.

Empfohlener Einstieg:

```text
/doctor
/what-now
/herbert-swarm . --dry-run
```

So prüfst du erst Setup und Plan, bevor Agenten Dateien verändern.

| Befehl | Beschreibung |
|---------|-------------|
| `/herbert-swarm <pfad>` | Startet den vollen Zyklus (Init -> Plan -> Run -> Report) |
| `/herbert-swarm <pfad> --dry-run` | Plant per KI und simuliert die Ausführung |
| `/herbert-swarm <pfad> --parallel N` | Führt bis zu `N` Tasks parallel aus |
| `/herbert-swarm status <pfad>` | Zeigt den aktuellen Fortschritt aller Tasks |
| `/herbert-swarm run <pfad>` | Setzt die Ausführung fort (z.B. nach einem Abbruch) |
| `/herbert-swarm reset <pfad>` | Löscht das Swarm-Brain des Projekts nach Bestätigung |

### Optionen

- `--parallel N`: Anzahl der Agenten, die gleichzeitig arbeiten (Standard: 3)
- `--dry-run`: Simuliert die Ausführung, ohne echte Dateien zu schreiben
- `--spec <pfad>`: Nutzt eine spezifische SPEC-Datei statt der Standard-Datei im Projektordner
- `--timeout SEKUNDEN`: Timeout pro Agent

## Task Phasen

Phasen sind nicht fest verdrahtet. Die KI entscheidet anhand der `SPEC.md`, welche Phasen sinnvoll sind und in welcher Reihenfolge sie laufen. Typische Beispiele sind `INFRA`, `DATABASE`, `BACKEND`, `FRONTEND`, `TESTING` oder eine einfache `IMPLEMENTATION`-Phase.

Wenn die KI technisch nicht erreichbar ist oder ungültiges JSON liefert, erzeugt Herbert Swarm bewusst keinen geratenen Keyword-Plan. Stattdessen wird ein neutraler Minimalplan mit einer `IMPLEMENTATION`-Aufgabe gespeichert, damit der Nutzer den Providerfehler sieht und den Plan erneut erzeugen kann.

## Brain-Datei

`<projekt>/.swarm_brain.json`

Das "Brain" ist das geteilte Gedächtnis aller Agenten. Hier werden KI-Plan, Ergebnisse, erstellte Dateien, Fehlerdetails und der Status jedes Tasks gespeichert.

## Bekannte Probleme / Pitfalls (Fixed!)

- ~~**Planner hängt bei großen Projekten**~~: Behoben durch kompaktes Projektinventar und Verzeichnis-Filter.
- ~~**Keyword-Fallback plant falschen Stack**~~: Behoben durch AI-first Planning und neutralen Minimalplan bei KI-Ausfall.
- ~~**Absturz bei paralleler Ausführung**~~: Behoben durch async Task-Ausführung ohne Thread-Event-Loops.
- ~~**Keine Info was passiert**~~: Behoben durch Live-Feedback-System.

## Siehe auch

- [AgentGuide](AgentGuide.md) — Agent-System und sub-agent Aufruf
- [Skills](Skills.md) — Wie Skills generell funktionieren
