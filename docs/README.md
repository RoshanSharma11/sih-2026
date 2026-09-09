# SkyGuard docs

Read these before writing code. They are the source of truth. If code and docs disagree, update the docs in the same change.

To **fetch, run the API, stream, inject, or open the dashboard**, use the [root README](../README.md). This folder is the design record.

Implemented backend + simulator (purpose and how they work): [backend-simulator-summary.md](backend-simulator-summary.md).

## Read order

1. [progress.md](progress.md) — what is built, what is next (handoff)
2. [context.md](context.md) — problem, scope, glossary
3. [decisions.md](decisions.md) — locked choices and why
4. [architecture.md](architecture.md) — system, repo, data flow
5. [contracts.md](contracts.md) — payloads, DB, ML interface (do not invent fields)
6. [data-simulator.md](data-simulator.md) — fetch, inject, stream, eval set
7. [backend.md](backend.md) — FastAPI, 3-tier engine, health
8. [frontend.md](frontend.md) — Streamlit demo console
9. [implementation-plan.md](implementation-plan.md) — build order
10. [backend-simulator-summary.md](backend-simulator-summary.md) — what shipped in data + API, and why

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
| Streamlit dashboard | Frontend | frontend.md, contracts.md § REST |
| ESP32 firmware | Edge/QA (not us) | out of scope |

## Rule

Shared types live in `contracts.md`. Injection math lives in one library. The simulator streams **clean** data. The backend applies demo faults. Raw observations are never overwritten.
