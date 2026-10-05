# SIH submission guide — SkyGuard (PS 26073)

Checklist for team members before sharing the GitHub link with reviewers.

## Links (must work without login)

| Item | URL |
|---|---|
| GitHub repository | https://github.com/RoshanSharma11/sih-2026 |
| YouTube demo | https://youtu.be/emdL6D2NRLQ |
| Live prototype | https://www.skyguard.roshansharma.net/ |

Also recorded in [submission/DEMO.md](submission/DEMO.md) and the root [README.md](README.md).

This file is the team checklist at the repository root (NSUT SIH template).

## Repository layout (NSUT-style)

| Item | Location |
|---|---|
| Project overview | `README.md` |
| Presentation notes / PPT pointer | `submission/PRESENTATION.md` |
| Demo video + prototype | `submission/DEMO.md` |
| Screenshots | `assets/screenshots/` |
| Architecture | `docs/architecture.md` |
| Source | `src/`, `frontend/`, `v2-deliverable/` |

## Before you submit

- [x] README sections 1–13 filled with SkyGuard (not template CropGuard text)
- [x] `submission/DEMO.md` YouTube + prototype URLs open in a private/incognito window
- [x] `submission/PRESENTATION.md` points at the pitch PDF or an accessible Drive link
- [x] At least Network / Station / Control screenshots under `assets/screenshots/`
- [ ] Repo is public (or shared with reviewers as required)
- [x] No `.env`, API keys, passwords, or tokens in git history or files
- [x] `.env.example` lists variable **names** only
- [x] `data/skyguard.db` and raw dumps stay gitignored

## Secrets

Never commit:

- `.env`
- IMD credentials
- webhook URLs with embedded secrets
- SQLite DBs or large parquet dumps

## Quick local verify

```bash
pip install -e ".[dev,ui]"
pip install -r v2-deliverable/requirements.txt
python scripts/run_api.py          # terminal 1
python scripts/run_dashboard.py    # terminal 2
pytest -q
```

## Pitch content source

Copy-paste blocks for the official SIH idea template: [docs/sih-idea-submission.md](docs/sih-idea-submission.md).
