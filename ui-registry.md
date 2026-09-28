# UI registry — SkyGuard dashboard

Last updated: 2026-09-28 (Architecture page)

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
| Grid | 6 columns on Network, `0.75rem` gap |
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
| Alert row | `.sg-alert` — white card, 4px status left edge, 12px radius, soft shadow |
| Buddy chip | canvas fill, `#E2E8F0` border, pill |

**Pattern notes:** Selected station is Streamlit `type="primary"` (teal). Map marker size 20 selected / 13 otherwise; only the selected name is drawn on the map. Contribution bars are 8px pills, not status-colored. Alerts is an inbox: intro card, four-count KPI strip, kind filters, then cards with a human title (not raw enums) and **Inspect this hour**.

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
| Roster selected | `.sg-roster-row-on` — `#F0FDFA`, 3px teal inset |

**Pattern notes:** Camera fits stations within 2.5° of the selected id so NCR is readable. Santacruz stays on the roster when Palam is selected. Weather markers stay amber. Network is KPI → full-width dispatch board → map left / roster rail right.

### Dispatch panel

File: `frontend/views/network.py`, `frontend/panels.py`

| Property | Class / value |
|---|---|
| Shell | `st.container(border=True)` wrapping `.sg-dispatch-head` |
| Row | `.sg-dispatch-row` — 3-col grid, no card chrome, 1px `#E2E8F0` rule |
| Name | 0.95rem / 650, 3px rose (`#E11D48`) or slate (`#64748B`) left edge |
| Why | 0.86rem / `#0F172A` — human reason, never `COMMUNICATION:temp` |
| Meta | IBM Plex Mono 0.74rem / `#475569` — `7-day N · STATUS` |
| Action | Station-name buttons in a 4-across wrap under the list |

**Pattern notes:** Weather never appears. Page is 7-day `DEGRADED` / `CRITICAL`. Watch is this-hour hardware while `HEALTHY`. Empty copy is teal-free slate text, not amber. Do not put dispatch cards in the narrow rail.

### Station identity + readings

File: `frontend/views/station.py`, `frontend/panels.py`

| Property | Class / value |
|---|---|
| Identity card | `.sg-identity` — white, `#E2E8F0` border, 12px radius, soft shadow, padding `1rem 1.15rem` |
| Name | 1.35rem / 700 / `#0F172A` |
| Meta | IBM Plex Mono, 0.82rem, `#475569` |
| Reading tile | `.sg-reading` — same card chrome; missing channel uses amber wash `#FFFBEB` / `#FDE68A` |
| Value | IBM Plex Mono, 1.85rem |
| Predicted line | `#D97706`, mono, only when `imputed_interval` is a pair |

**Pattern notes:** Warm-up uses `.sg-warmup` with a slate bar and 24 hour dots (`.sg-dot-on` = `#94A3B8`). Health is a meter, not a Streamlit metric. Buddy chips stack a short name over a mono id / correlation.

### Control poll + replay results

File: `frontend/views/control.py`, `frontend/panels.py`

| Property | Class / value |
|---|---|
| Poll strip | `.sg-poll` — white card, 4px left edge (`ok` teal / `bad` rose / `idle` line) |
| Story preview | `.sg-preview` — same left-edge language as `.sg-verdict` |
| Result row | `.sg-result` — canvas fill, 4px status edge, mono meta |

**Pattern notes:** Control does not auto-navigate after Play. Results stay on the page; Inspect is the Station handoff. Weather stories stay amber. Custom events reuse `.sg-preview` and `.sg-result` for the inject builder and armed overlays.

### Architecture page

File: `frontend/views/architecture.py`, `frontend/theme.py` (`.sg-arch*`)
Last updated: 2026-09-28

| Property | Class / value |
|---|---|
| Background | `#FFFFFF` cards on `#F8FAFC` |
| Border | `1px solid #E2E8F0` |
| Border radius | `12px` cards, `8px` check tiles, `999px` pills and step numbers |
| Text — primary | `#0F172A`, 1rem / 600 titles |
| Text — secondary | `#475569`, 0.86rem |
| Text — meta | IBM Plex Mono, 0.72–0.78rem |
| Spacing | card padding `0.85rem 1rem` to `1rem 1.1rem`; grid gap `0.75rem` |
| Shadow | soft card shadow |
| Accent usage | teal `#0D9488` for the traveling hour, kickers, and the ingest expansion. Status colors only on the four verdict cards (3px top edge). |

**Pattern notes:** Static page. No API calls. The hour is `.sg-arch-packet` on an 18s loop; stages wake with `.sg-arch-wake`; the three checks cycle inside stage 05; TIMING is a dashed pill off the solid rail; the GET chip blinks at 1s. Buddy pills (Juhu, Colaba, Alibag) stay visible and pulse teal in order beside Santa Cruz. Metric charts reuse `.sg-kpis` / `.sg-kpi` and the white Plotly card. Channel colors match contribution bars (temperature teal, pressure blue, humidity purple). Status colors stay off the source cards. `prefers-reduced-motion` turns the motion off. Do not use weather or hardware colors on the source cards.

