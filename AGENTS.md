# SkyGuard agent instructions

This is SIH PS 26073 (SkyGuard AI). Read `docs/` before writing code.

Required read order: `docs/README.md` → `docs/context.md` → `docs/decisions.md` → `docs/contracts.md` → the file for the area you are changing.

- Data / streamer / inject: `docs/data-simulator.md`
- FastAPI / pipeline / SQLite: `docs/backend.md`
- Layout: `docs/architecture.md`
- Build order: `docs/implementation-plan.md`

Rules:

1. Do not invent API fields, enum values, or table columns. Change `docs/contracts.md` in the same PR if you must.
2. Fault math lives only in `skyguard.data.inject`.
3. The streamer sends clean data. Live faults go through `/demo/inject`.
4. Never overwrite raw observations. Imputed values are overlay columns.
5. Do not train models or build Streamlit unless asked. Provide an `IdentityDetector` until `MODEL_PATH` is set.
6. Buddy check stays inside a cluster (150 km). Delhi must not validate Mumbai.
