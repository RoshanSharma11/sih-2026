# UI registry — SkyGuard dashboard

Last updated: 2026-09-06

Dark ops console. Weather is amber, never red. Health is a badge, not the marker fill.

## Baseline — Established 2026-09-06

| Property | Value |
|---|---|
| Page background | `#070b14` |
| Panel / card | `#101827` |
| Border | `#1e2a3f` |
| Radius | `12px` cards, `8px` overlays, `999px` chips |
| Text primary | `#e8eef7` |
| Text muted | `#8b9bb4` |
| Font | IBM Plex Sans / IBM Plex Mono (meta) |
| Accent / clean | `#2dd4bf` |
| Genuine weather | `#f5b942` |
| Hardware | `#f43f5e` |
| Unknown / idle pip | `#94a3b8` / `#3d4f6f` |
| Observed series | `#5eead4` solid |
| Imputed series | `#f5b942` dashed |
| Map land / ocean | `#152036` / `#070b14` |

### Page shell

File: `frontend/theme.py`, `.streamlit/config.toml`

| Property | Class / value |
|---|---|
| Background | `#070b14` |
| Streamlit primary | `#2dd4bf` |
| Secondary surface | `#101827` |
| Spacing | `.block-container` padding-top `1.1rem`, max-width `1320px` |

**Pattern notes:** Hide Streamlit chrome (menu, footer, deploy). Kicker is uppercase teal, 0.72rem, letter-spacing 0.16em.

### Verdict banner

File: `frontend/app.py` (`sg-verdict`)

| Property | Class / value |
|---|---|
| Background | `#101827` |
| Border | `1px solid #1e2a3f`, left `4px` status color |
| Radius | `12px` |
| Text — headline | `1.15rem` / 600 / `#e8eef7` |
| Text — meta | IBM Plex Mono, `#8b9bb4` |
| Spacing | padding `1rem 1.15rem` |

**Pattern notes:** Left-edge color encodes `pipeline_status`. Weather uses `sg-verdict-weather` (`#f5b942`), never hardware red.

### Station rail + overlays

File: `frontend/app.py`

| Property | Class / value |
|---|---|
| Status pip | 4px bar under the button, `pipeline_color` |
| Overlay chip | `#18233a` fill, `#f5b942` text, radius `8px` |
| Alert row | left 3px status color, `#101827` fill, radius `0 8px 8px 0` |

**Pattern notes:** Selected station is Streamlit `type="primary"` (teal). Marker size 22 selected / 16 otherwise.
