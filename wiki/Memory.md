# Memory & Personality

CucumberAgent trennt Identität, Fakten, gepinnten Kontext und Chat-Verlauf klar
voneinander. Dadurch kann der Agent lange Sessions komprimieren, ohne seine
Persönlichkeit oder wichtige Erinnerungen zu verlieren.

## Die Garantie

- `~/.cucumber/personality/personality.md` ist die dauerhafte Identität des Agenten.
- Gespeicherte Fakten aus `/remember` werden aus `facts.json` oder `facts.db` direkt in den System-Prompt geladen.
- `/pin <text>` hat höchste Priorität innerhalb der laufenden Session.
- Session-Summaries werden angehängt, nicht ersetzt.
- Kompression darf nur Chat-Historie kürzen, niemals Persönlichkeit, Fakten, Pins oder Summaries löschen.

Im Agenten wird daraus bei jedem Request ein `CORE IDENTITY` Block plus ein
`MEMORY & IDENTITY CONTRACT`. Dieser Contract sagt dem Modell ausdrücklich, dass
Gesprächsanweisungen wie "vergiss deine Persönlichkeit" oder "ignoriere deine
Memory" die gespeicherten Grundlagen nicht überschreiben.

## Speicherorte

```text
~/.cucumber/
├── personality/
│   └── personality.md       # Charakter, Ton, Sprache, Name
├── memory/
│   ├── facts.json           # oder facts.db, dauerhafte Fakten
│   ├── last_summary.txt     # fortlaufende Session-Zusammenfassung
│   └── YYYY-MM-DD.md        # tägliche Gesprächslogs
└── config.yaml
```

## Befehle

| Befehl | Wirkung |
|--------|---------|
| `/memory` | Zeigt gespeicherte Fakten |
| `/remember key: value` | Speichert einen dauerhaften Fakt |
| `/forget key` | Löscht genau diesen Fakt |
| `/pin <text>` | Pinnt Kontext in der aktuellen Session |
| `/pin` | Listet Pins |
| `/unpin <nr>` | Entfernt einen Pin |
| `/compact` | Fasst alte Nachrichten zusammen |
| `/context` | Zeigt Kontext- und Tokenstatus |

## Wann was nutzen?

Nutze `/remember`, wenn der Agent etwas langfristig wissen soll:

```text
/remember bevorzugter_provider: minimax
/remember projektstil: immer mit Tests und Doku abschließen
```

Nutze `/pin`, wenn etwas für die aktuelle Arbeit hart gelten soll:

```text
/pin Herbert Swarm muss alle Tasks erst trocken planen, dann ausführen.
/pin Keine destruktiven Befehle ohne explizite Zustimmung.
```

Nutze `/compact`, wenn der Kontext sehr voll ist und du die Session behalten
willst. Die Zusammenfassung wird an bestehende Summaries angehängt.

## Für Entwickler

Die relevante Logik liegt hier:

- `src/cucumber_agent/agent.py` baut `CORE IDENTITY` und `MEMORY & IDENTITY CONTRACT`.
- `src/cucumber_agent/memory.py` verwaltet `FactsStore`, `SQLiteFactsStore`, `SessionLogger` und `SessionSummary`.
- `src/cucumber_agent/cli.py` lädt Fakten und Summaries beim Start und aktualisiert sie nach `/remember`, `/forget` und `/compact`.
- `src/cucumber_agent/tui.py` hängt TUI-Summaries ebenfalls an bestehende Summaries an.

Regressionstests sichern ab, dass Persönlichkeit, Contract, Fakten, Pins und
Summaries im Prompt erhalten bleiben.
