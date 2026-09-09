"""Light ops-console tokens and CSS. Status color is reserved for QC state."""

from __future__ import annotations

CANVAS = "#F8FAFC"
CARD = "#FFFFFF"
TEXT = "#0F172A"
MUTED = "#475569"
LINE = "#E2E8F0"
ACCENT = "#0D9488"
CLEAN = "#0D9488"
WEATHER = "#D97706"
HARDWARE = "#E11D48"
SLATE = "#64748B"
OBSERVED = "#0F766E"
IMPUTED = "#D97706"
MAP_LAND = "#EEF2F7"
MAP_OCEAN = "#F8FAFC"
MAP_BORDER = "#CBD5E1"
GRID = "#E2E8F0"
SHADOW = "0 1px 2px rgba(15, 23, 42, 0.06), 0 8px 24px rgba(15, 23, 42, 0.04)"
EDGE = "#0F766E"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,0,0&display=swap');

html, body, [class*="css"], [data-testid="stAppViewContainer"] {{
  font-family: "IBM Plex Sans", system-ui, sans-serif;
}}

.stApp {{ background: {CANVAS}; }}
header[data-testid="stHeader"] {{ background: transparent; }}
#MainMenu, footer, .stAppDeployButton {{ visibility: hidden; height: 0; }}
div[data-testid="stToolbar"] {{ visibility: hidden; }}
.block-container {{ padding-top: 1.05rem; padding-bottom: 2.4rem; max-width: 1360px; }}

section[data-testid="stSidebar"] {{
  background: {CARD};
  border-right: 1px solid {LINE};
  width: 268px !important;
  min-width: 268px !important;
}}
[data-testid="stSidebar"] {{
  font-family: "IBM Plex Sans", system-ui, sans-serif;
  background: {CARD};
}}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
  padding: 0.35rem 0.85rem 1.2rem 0.85rem;
}}

span[data-testid="stIconMaterial"],
span[data-testid="stIconMaterial"] *,
[data-testid="stSidebarCollapseButton"] span[data-testid="stIconMaterial"],
[data-testid="stBaseButton-headerNoPadding"] span[data-testid="stIconMaterial"],
[data-testid="stHeaderActionElements"] span[data-testid="stIconMaterial"] {{
  font-family: "Material Symbols Rounded" !important;
  font-style: normal !important;
  font-weight: 400 !important;
  font-variation-settings: "FILL" 0, "wght" 500, "GRAD" 0, "opsz" 20 !important;
  font-feature-settings: "liga" 1 !important;
  -webkit-font-feature-settings: "liga" 1 !important;
  letter-spacing: normal !important;
  text-transform: none !important;
  line-height: 1 !important;
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  speak: never;
}}

.sg-brand-sub {{
  color: {MUTED};
  font-size: 0.78rem;
  margin: -0.15rem 0 0.85rem 0.15rem;
}}
.sg-nav-section {{
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: {SLATE};
  margin: 0.85rem 0.15rem 0.35rem 0.15rem;
}}
.sg-sidebar-foot {{
  margin-top: 1.4rem;
  padding-top: 0.85rem;
  border-top: 1px solid {LINE};
  color: {MUTED};
  font-size: 0.75rem;
  line-height: 1.45;
}}
.sg-sidebar-foot strong {{
  color: {TEXT};
  font-size: 0.8rem;
}}

[data-testid="stSidebar"] [data-testid="stPageLink"] {{
  margin: 0.12rem 0;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] a,
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {{
  border-radius: 10px !important;
  padding: 0.55rem 0.7rem !important;
  gap: 0.65rem !important;
  font-weight: 600 !important;
  color: {TEXT} !important;
  background: transparent;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover,
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover {{
  background: {CANVAS} !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"],
[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="true"],
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"][aria-current="page"],
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"][aria-current="true"] {{
  background: #F0FDFA !important;
  color: {OBSERVED} !important;
  box-shadow: inset 3px 0 0 {ACCENT};
}}

h1 {{ letter-spacing: -0.03em; color: {TEXT}; font-weight: 700; }}
h2, h3, h4, h5 {{ letter-spacing: -0.02em; color: {TEXT}; }}

.sg-kicker {{
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: {ACCENT};
  margin-bottom: 0.2rem;
}}
.sg-sub {{
  color: {MUTED};
  margin-top: -0.45rem;
  margin-bottom: 0.9rem;
}}

.sg-health {{
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.4rem;
  padding: 0.7rem 0.2rem 0 0;
}}
.sg-chip {{
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.28rem 0.7rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  border: 1px solid {LINE};
  background: {CARD};
  color: {TEXT};
}}
.sg-chip-ok {{ background: #F0FDFA; color: {ACCENT}; border-color: #99F6E4; }}
.sg-chip-bad {{ background: #FFF1F2; color: {HARDWARE}; border-color: #FECDD3; }}
.sg-chip-idle {{ background: {CANVAS}; color: {SLATE}; }}

.sg-kpis {{
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0.75rem;
  margin: 0.35rem 0 0.85rem 0;
}}
.sg-kpi {{
  background: {CARD};
  border: 1px solid {LINE};
  border-radius: 12px;
  box-shadow: {SHADOW};
  padding: 0.85rem 1rem 0.9rem 1rem;
  border-top: 3px solid {LINE};
}}
.sg-kpi-label {{
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: {MUTED};
}}
.sg-kpi-value {{
  font-size: 1.7rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  margin-top: 0.15rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}}

.sg-card {{
  background: {CARD};
  border: 1px solid {LINE};
  border-radius: 12px;
  box-shadow: {SHADOW};
  padding: 1rem 1.15rem;
  margin-bottom: 0.85rem;
}}

.sg-verdict {{
  border: 1px solid {LINE};
  border-left-width: 4px;
  border-radius: 12px;
  padding: 1rem 1.15rem;
  background: {CARD};
  box-shadow: {SHADOW};
  margin: 0.25rem 0 0.85rem 0;
}}
.sg-verdict-weather {{ border-left-color: {WEATHER}; }}
.sg-verdict-hardware {{ border-left-color: {HARDWARE}; }}
.sg-verdict-unknown {{ border-left-color: {SLATE}; }}
.sg-verdict-clean {{ border-left-color: {CLEAN}; }}
.sg-verdict-idle {{ border-left-color: {LINE}; }}
.sg-verdict-kicker {{
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: {MUTED};
  margin-bottom: 0.35rem;
}}
.sg-verdict-text {{
  font-size: 1.12rem;
  font-weight: 600;
  color: {TEXT};
  line-height: 1.45;
}}
.sg-verdict-meta {{
  margin-top: 0.45rem;
  color: {MUTED};
  font-size: 0.85rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}}

.sg-overlay {{
  display: inline-block;
  margin: 0.15rem 0.35rem 0.15rem 0;
  padding: 0.28rem 0.65rem;
  border-radius: 8px;
  background: #FFFBEB;
  color: {WEATHER};
  border: 1px solid #FDE68A;
  font-size: 0.8rem;
  font-weight: 600;
}}

.sg-legend {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.85rem;
  margin: 0.15rem 0 0.75rem 0;
}}
.sg-legend span {{
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: {MUTED};
  font-size: 0.8rem;
}}
.sg-dot {{
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 999px;
  display: inline-block;
}}

.sg-alert {{
  border-left: 3px solid {SLATE};
  padding: 0.55rem 0.8rem;
  margin-bottom: 0.5rem;
  background: {CARD};
  border: 1px solid {LINE};
  border-left-width: 3px;
  border-radius: 0 10px 10px 0;
}}
.sg-alert-meta {{
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  color: {MUTED};
  font-weight: 700;
  text-transform: uppercase;
}}
.sg-alert-text {{
  color: {TEXT};
  margin-top: 0.2rem;
  line-height: 1.4;
}}

.sg-buddy {{
  display: inline-block;
  padding: 0.18rem 0.55rem;
  border-radius: 999px;
  background: {CANVAS};
  border: 1px solid {LINE};
  color: {TEXT};
  font-size: 0.78rem;
  font-weight: 600;
  margin: 0.15rem 0.25rem 0.15rem 0;
}}

.sg-caption {{
  color: {MUTED};
  font-size: 0.85rem;
  line-height: 1.45;
}}

.sg-bar-row {{
  display: grid;
  grid-template-columns: 7.5rem 1fr 3.5rem;
  gap: 0.65rem;
  align-items: center;
  margin: 0.4rem 0;
}}
.sg-bar-label {{
  font-size: 0.82rem;
  color: {TEXT};
  font-weight: 600;
}}
.sg-bar {{
  height: 8px;
  background: {CANVAS};
  border: 1px solid {LINE};
  border-radius: 999px;
  overflow: hidden;
}}
.sg-bar i {{
  display: block;
  height: 100%;
  border-radius: 999px;
}}
.sg-bar-pct {{
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.78rem;
  color: {MUTED};
  text-align: right;
}}

.sg-guide h3 {{ margin-top: 1.1rem; }}
.sg-guide p, .sg-guide li {{ color: {MUTED}; line-height: 1.55; }}
.sg-tier {{
  display: grid;
  grid-template-columns: 2.4rem 1fr;
  gap: 0.75rem;
  padding: 0.85rem 0.95rem;
  border: 1px solid {LINE};
  border-radius: 12px;
  background: {CARD};
  box-shadow: {SHADOW};
  margin: 0.55rem 0;
}}
.sg-tier-n {{
  width: 2.1rem;
  height: 2.1rem;
  border-radius: 999px;
  background: #F0FDFA;
  color: {OBSERVED};
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.sg-tier strong {{ color: {TEXT}; }}

div[data-testid="stMetric"] {{
  background: {CARD};
  border: 1px solid {LINE};
  border-radius: 12px;
  box-shadow: {SHADOW};
  padding: 0.65rem 0.85rem;
}}
div[data-testid="stPlotlyChart"] {{
  background: {CARD};
  border: 1px solid {LINE};
  border-radius: 12px;
  box-shadow: {SHADOW};
  overflow: hidden;
  padding: 0.15rem;
}}
[data-testid="stMultiSelect"] [data-baseweb="tag"] {{
  background: #F0FDFA !important;
  border-color: #99F6E4 !important;
  color: {OBSERVED} !important;
}}

@media (max-width: 900px) {{
  .sg-kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
}}
</style>
"""
