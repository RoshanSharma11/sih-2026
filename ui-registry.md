# UI registry — SkyGuard dashboard

Last updated: 2026-09-09

Light ops console. Weather is amber, never rose. Health is a badge, not the marker fill. Status color is reserved for QC state.

## Baseline — Established 2026-09-09

| Property | Value |
|---|---|
| Page background | `#F8FAFC` |
| Panel / card | `#FFFFFF` |
| Border | `#E2E8F0` |
| Radius | `12px` cards, `8px` overlays, `999px` chips |
| Shadow | `0 1px 2px rgba(15, 23, 42, 0.06), 0 8px 24px rgba(15, 23, 42, 0.04)` |
| Text primary | `#0F172A` |
| Text muted | `#475569` |
| Font | IBM Plex Sans / IBM Plex Mono (meta, KPI, contribution %) |
| Accent / clean | `#0D9488` |
| Genuine weather | `#D97706` |
| Hardware | `#E11D48` |
| Unknown / idle | `#64748B` |
| Observed series | `#0F766E` solid |
| Imputed series | `#D97706` dashed |
| Map | Carto Positron tiles; camera fits selected cluster |
| Contribution T / P / H | `#0F766E` / `#0369A1` / `#6D28D9` (not status colors) |

### Page shell

File: `frontend/theme.py`, `.streamlit/config.toml`

| Property | Class / value |
|---|---|
| Background | `#F8FAFC` |
| Streamlit primary | `#0D9488` |
| Secondary surface | `#FFFFFF` |
| Spacing | `.block-container` padding-top `1.05rem`, max-width `1360px` |
| Sidebar | 268px, white, `#E2E8F0` right border, custom `st.page_link` nav |

**Pattern notes:** Hide Streamlit chrome (menu, footer, deploy). Kicker is uppercase teal, 0.72rem, letter-spacing 0.16em. Brand is `st.logo` (wordmark + mark) plus a custom `st.page_link` sidebar. Never set `[data-testid="stSidebar"] * { font-family }` — that concatenates Material icon ligatures onto labels (`mapNetwork`). Keep Material Symbols Rounded on `stIconMaterial`.

### KPI strip

File: `frontend/chrome.py` (`sg-kpis`)

| Property | Class / value |
|---|---|
| Grid | 5 columns, `0.75rem` gap |
| Card | `.sg-kpi` — white, `#E2E8F0` border, 12px radius, 3px status-colored top edge, soft shadow |
| Label | 0.72rem / 600 / uppercase / `#475569` |
| Value | IBM Plex Mono, 1.7rem, status color |

**Pattern notes:** Counts come from `latest.label` on the view set. Do not poll 151 detail endpoints.

### Verdict banner

File: `frontend/views/station.py` (`sg-verdict`)

| Property | Class / value |
|---|---|
| Background | `#FFFFFF` |
| Border | `1px solid #E2E8F0`, left `4px` status color |
| Radius | `12px` |
| Text — headline | `1.12rem` / 600 / `#0F172A` |
| Text — meta | IBM Plex Mono, `#475569` |
| Spacing | padding `1rem 1.15rem` |

**Pattern notes:** Left-edge color encodes five-way `label` (fallback `pipeline_status`). Weather uses `sg-verdict-weather` (`#D97706`), never hardware rose.

### Alerts + overlays

File: `frontend/views/alerts.py`, `frontend/chrome.py`

| Property | Class / value |
|---|---|
| Overlay chip | `#FFFBEB` fill, `#D97706` text, `#FDE68A` border, radius `8px` |
| Alert row | left 3px status color, white fill, `#E2E8F0` border, radius `0 10px 10px 0` |
| Buddy chip | canvas fill, `#E2E8F0` border, pill |

**Pattern notes:** Selected station is Streamlit `type="primary"` (teal). Map marker size 20 selected / 13 otherwise; only the selected name is drawn on the map. Contribution bars are 8px pills, not status-colored.

### Sidebar nav

File: `frontend/app.py`, `frontend/chrome.py`, `frontend/assets/`

| Property | Class / value |
|---|---|
| Width | 268px |
| Nav section | `.sg-nav-section` — 0.68rem / 700 / uppercase / `#64748B` |
| Active link | `#F0FDFA` fill, `#0F766E` text, 3px teal inset |
| Hover | `#F8FAFC` |
| Footer | `.sg-sidebar-foot` — top `#E2E8F0` rule |

**Pattern notes:** `st.navigation(..., position="hidden")` plus `st.page_link`. Human titles only (`Network`, not `mapNetwork`).

### Network map + roster

File: `frontend/map_view.py`, `frontend/views/network.py`

| Property | Class / value |
|---|---|
| Basemap | `carto-positron` via `go.Scattermap` |
| Height | 640px |
| Buddy edge | `#0F766E`, 2.4px |
| Plotly card | white, `#E2E8F0` border, 12px radius |
| Roster selected | Streamlit primary button |

**Pattern notes:** Camera fits stations within 2.5° of the selected id so NCR is readable. Santacruz stays on the roster when Palam is selected. Weather markers stay amber.
