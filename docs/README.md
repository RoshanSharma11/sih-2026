# SkyGuard docs

Read these before writing code. They are the source of truth for data, simulator, and backend work. If code and docs disagree, update the docs in the same change.

## Read order

1. [context.md](context.md) — problem, scope, glossary
2. [decisions.md](decisions.md) — locked choices and why
3. [architecture.md](architecture.md) — system, repo, data flow
4. [contracts.md](contracts.md) — payloads, DB, ML interface (do not invent fields)
5. [data-simulator.md](data-simulator.md) — fetch, inject, stream, eval set
6. [backend.md](backend.md) — FastAPI, 3-tier engine, health
7. [implementation-plan.md](implementation-plan.md) — build order

## Who owns what

| Area | Owner | Doc |
|---|---|---|
| Ground-truth fetch, filter, persist | Data + Simulator | data-simulator.md |
| Fault injection library + eval labels | Data + Simulator | data-simulator.md |
| Clean telemetry streamer | Data + Simulator | data-simulator.md |
| FastAPI, SQLite, `/ingest`, query APIs | Backend | backend.md, contracts.md |
| Tier 1 rules, Tier 3 buddy check, classifier, health | Backend | backend.md |
| Demo inject control plane | Backend (uses inject library) | backend.md, data-simulator.md |
| LSTM training + real `Detector` | AI/ML (not us) | contracts.md § Detector |
| Streamlit dashboard | Frontend (not us) | contracts.md § REST |
| ESP32 firmware | Edge/QA (not us) | out of scope |

## Rule

Shared types live in `contracts.md`. Injection math lives in one library. The simulator streams **clean** data. The backend applies demo faults. Raw observations are never overwritten.
