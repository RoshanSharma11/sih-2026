# SkyGuard agent instructions

This is SIH PS 26073 (SkyGuard AI). Read `docs/` before writing code.

## Do this next

The current build is **live IMD hours through v2**, not the Palam / `ml/` demo. Read [`docs/v2-live-plan.md`](docs/v2-live-plan.md) and implement **step 5** before anything else. Steps are ordered. Update `docs/contracts.md` in the same change when a step adds a field.

IMD credentials are already in `.env` (`IMD_API_KEY`, `IMD_EMAIL`, `IMD_PASSWORD`, `IMD_TOKEN_URL`, `IMD_AWS_URL`). That file is gitignored. Never copy those values into code, docs, or commits. Names only live in `.env.example`.

Required read order: `docs/v2-live-plan.md` → `v2-deliverable/docs/CONTRACT.md` → `docs/progress.md` → `docs/contracts.md` → the file for the area you are changing.

- Status / handoff: `docs/progress.md`
- Data / streamer / inject: `docs/data-simulator.md`
- FastAPI / pipeline / SQLite: `docs/backend.md`
- Streamlit dashboard: `docs/frontend.md`
- Layout: `docs/architecture.md`
- Build order: `docs/implementation-plan.md`

## Git — commit after every step

The history must stay reviewable. Do not batch a whole afternoon of work into one commit.

1. After each **implementation-plan slice** (0, 1a, 1b, 2a, …), create a git commit before starting the next slice.
2. After each **finished feature or bugfix** that is smaller than a slice (for example inject functions, or `/healthz` alone), commit that increment immediately.
3. Do not leave working, tested code uncommitted at the end of a turn.
4. One commit = one reason. Do not mix fetch work with API routes, or docs with application code, unless the docs change is required to explain that same code.
5. Commit message: 1–2 sentences on **why**, written as if a teammate will revert or cherry-pick it. Follow the repo’s existing style.
6. Stage only the files for that increment. Never `git add .` if it would include unrelated edits.
7. Never commit secrets, `.env`, `data/skyguard.db`, Meteostat dumps, large parquet, or `__pycache__`.
8. Never `git push` unless the user asked. Never `--no-verify`, force-push, or amend a pushed commit.
9. If a slice is half-done and blocked, commit the complete subset (e.g. “add inject unit tests”) rather than a broken WIP dump. Do not commit code that does not import or that fails the tests for that increment.

## Product rules

1. Do not invent API fields, enum values, or table columns. Change `docs/contracts.md` in the same change if you must.
2. Fault math lives only in `skyguard.data.inject`.
3. The streamer sends clean data. Live faults go through `/demo/inject`.
4. Never overwrite raw observations. Imputed values are overlay columns.
5. Do not train models unless asked. Production QC is `v2-deliverable` `v2.engine.process_aws_data` (in-process, GAT off). Do not call `ml.engine` or legacy `skyguard.engine` tiers on live ingest. Dashboard polls the product API only; do not invent API fields. Palam is not the default station. Live catalog is the 48 in `stations_judge48.csv`.
6. Buddy check uses the ML buddy graph (≥2 neighbors). Delhi must not validate Mumbai. Station view filters must still ingest 1-hop buddies.
