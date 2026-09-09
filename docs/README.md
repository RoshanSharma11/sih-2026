# SkyGuard docs

Read these before writing code. They are the source of truth. If code and docs disagree, update the docs in the same change.

To **fetch, run the API, stream, inject, or open the dashboard**, use the [root README](../README.md). This folder is the design record.

## Read order

1. [progress.md](progress.md) — what is built, what is next (handoff). **Start here.**
2. [context.md](context.md) — problem, scope, glossary
3. [decisions.md](decisions.md) — locked choices and why
4. [architecture.md](architecture.md) — system, repo, data flow
5. [contracts.md](contracts.md) — payloads, DB, ML adapter (do not invent fields)
6. [data-simulator.md](data-simulator.md) — catalog import, inject, stream, eval set
7. [backend.md](backend.md) — FastAPI product shell
8. [frontend.md](frontend.md) — five-page light Streamlit console
9. [implementation-plan.md](implementation-plan.md) — I0–I6 then F7+
10. [backend-simulator-summary.md](backend-simulator-summary.md) — **legacy** data+API write-up (pre-ML engine)

## Who owns what

| Area | Owner | Doc |
|---|---|---|
| Ground-truth hours, catalog import, streamer | Data + Simulator | data-simulator.md |
| Fault injection library + eval labels | Data + Simulator | data-simulator.md |
| FastAPI, SQLite, demo overlay, query APIs, ML adapter | Backend | backend.md, contracts.md |
| Production 3-tier QC (rules + LSTM + buddy) | ML (`ml/`) | ml engine + contracts § QC boundary |
| Legacy backend tiers | unused on live ingest | backend.md (legacy) |
| Streamlit dashboard | Frontend | frontend.md |
| ESP32 firmware | Edge/QA (not us) | out of scope |

## Rule

Shared types live in `contracts.md`. Injection math lives in one library. The simulator streams **clean** data. The backend applies demo faults then calls ML. Raw observations are never overwritten. Buddy checks use the ML graph, not NORTH/WEST.
