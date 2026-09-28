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
WARMING = "#94A3B8"
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
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 0.75rem;
  margin: 0.35rem 0 0.85rem 0;
}}
.sg-kpis-4 {{
  grid-template-columns: repeat(4, minmax(0, 1fr));
}}
.sg-kpis-5 {{
  grid-template-columns: repeat(5, minmax(0, 1fr));
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
.sg-verdict-warming {{ border-left-color: {WARMING}; }}
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

.sg-network-intro .sg-verdict-text {{
  font-size: 1.05rem;
  margin-top: 0.15rem;
}}
.sg-network-intro .sg-legend {{
  margin: 0.75rem 0 0 0;
}}
.sg-map-head {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.75rem;
  margin: 0 0 0.45rem 0;
}}
.sg-map-head strong {{
  font-size: 0.92rem;
  color: {TEXT};
}}
.sg-map-head span {{
  color: {MUTED};
  font-size: 0.78rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}}
.sg-roster-group {{
  font-size: 0.8rem;
  font-weight: 650;
  letter-spacing: 0;
  text-transform: none;
  color: {SLATE};
  margin: 0.85rem 0 0.4rem 0;
}}
.sg-roster-row {{
  display: grid;
  grid-template-columns: 0.7rem 1fr auto;
  gap: 0.55rem;
  align-items: center;
  padding: 0.55rem 0.7rem;
  border: 1px solid {LINE};
  border-radius: 10px;
  background: {CARD};
  margin-bottom: 0.35rem;
}}
.sg-roster-row-on {{
  background: #F0FDFA;
  border-color: #99F6E4;
  box-shadow: inset 3px 0 0 {ACCENT};
}}
.sg-roster-name {{
  font-size: 0.86rem;
  font-weight: 600;
  color: {TEXT};
  line-height: 1.25;
}}
.sg-roster-meta {{
  color: {MUTED};
  font-size: 0.72rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  margin-top: 0.12rem;
}}
.sg-roster-label {{
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  white-space: nowrap;
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
  border-left: 4px solid {SLATE};
  padding: 0.95rem 1.1rem;
  margin-bottom: 0;
  background: {CARD};
  border: 1px solid {LINE};
  border-left-width: 4px;
  border-radius: 12px;
  box-shadow: {SHADOW};
}}
.sg-alert-head {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
}}
.sg-alert-title {{
  font-size: 1.08rem;
  font-weight: 700;
  color: {TEXT};
  letter-spacing: -0.02em;
}}
.sg-alert-who {{
  margin-top: 0.2rem;
  color: {TEXT};
  font-size: 0.88rem;
  font-weight: 600;
}}
.sg-alert-meta {{
  margin-top: 0.2rem;
  font-size: 0.78rem;
  letter-spacing: 0;
  color: {MUTED};
  font-weight: 500;
  text-transform: none;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}}
.sg-alert-text {{
  color: {TEXT};
  margin-top: 0.5rem;
  line-height: 1.45;
}}
.sg-alert-share {{
  margin-top: 0.4rem;
  color: {MUTED};
  font-size: 0.78rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}}
.sg-alert-note {{
  margin-top: 0.45rem;
  color: {MUTED};
  font-size: 0.8rem;
}}
.sg-alert-legend {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
}}
.sg-alert-legend p {{
  margin: 0.4rem 0 0 0;
  color: {MUTED};
  font-size: 0.82rem;
  line-height: 1.45;
}}
.sg-dispatch-head {{
  margin-bottom: 0.15rem;
}}
.sg-dispatch-list {{
  margin: 0.15rem 0 0.35rem 0;
}}
.sg-dispatch-list .sg-dispatch-row:last-child {{
  border-bottom: none;
  padding-bottom: 0.15rem;
}}
.sg-dispatch-row {{
  display: grid;
  grid-template-columns: minmax(7rem, 11rem) minmax(0, 1fr) auto;
  gap: 0.55rem 1rem;
  align-items: baseline;
  padding: 0.55rem 0.1rem 0.6rem 0;
  border: none;
  border-bottom: 1px solid {LINE};
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}}
.sg-dispatch-name {{
  font-size: 0.95rem;
  font-weight: 650;
  color: {TEXT};
  line-height: 1.3;
  border-left: 3px solid {SLATE};
  padding-left: 0.55rem;
}}
.sg-dispatch-page {{
  border-left-color: {HARDWARE};
}}
.sg-dispatch-watch {{
  border-left-color: {SLATE};
}}
.sg-dispatch-why {{
  font-size: 0.86rem;
  color: {TEXT};
  line-height: 1.4;
}}
.sg-dispatch-meta {{
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.74rem;
  color: {MUTED};
  white-space: nowrap;
}}

.sg-identity {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  background: {CARD};
  border: 1px solid {LINE};
  border-radius: 12px;
  box-shadow: {SHADOW};
  padding: 1rem 1.15rem;
  margin: 0.15rem 0 0.85rem 0;
}}
.sg-identity-name {{
  font-size: 1.35rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: {TEXT};
}}
.sg-identity-meta {{
  color: {MUTED};
  font-size: 0.82rem;
  margin-top: 0.2rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}}
.sg-identity-tag {{
  flex-shrink: 0;
  padding: 0.28rem 0.75rem;
  border-radius: 999px;
  background: {CANVAS};
  border: 1px solid {LINE};
  color: {TEXT};
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}}

.sg-readings {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
  margin: 0.15rem 0 0.85rem 0;
}}
.sg-reading {{
  background: {CARD};
  border: 1px solid {LINE};
  border-radius: 12px;
  box-shadow: {SHADOW};
  padding: 0.9rem 1rem 1rem 1rem;
}}
.sg-reading-gap {{
  border-color: #FDE68A;
  background: #FFFBEB;
}}
.sg-reading-label {{
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: {MUTED};
}}
.sg-reading-value {{
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 1.85rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: {TEXT};
  margin-top: 0.2rem;
  line-height: 1.1;
}}
.sg-reading-value span {{
  font-size: 0.85rem;
  font-weight: 600;
  color: {MUTED};
  margin-left: 0.3rem;
}}
.sg-reading-sub {{
  margin-top: 0.4rem;
  color: {MUTED};
  font-size: 0.78rem;
}}
.sg-reading-pred {{
  margin-top: 0.35rem;
  color: {WEATHER};
  font-size: 0.78rem;
  font-weight: 600;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}}

.sg-warmup, .sg-meter {{
  background: {CARD};
  border: 1px solid {LINE};
  border-radius: 12px;
  box-shadow: {SHADOW};
  padding: 0.95rem 1.1rem;
  margin: 0 0 0.85rem 0;
}}
.sg-warmup-head, .sg-meter-head {{
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: {MUTED};
  margin-bottom: 0.55rem;
}}
.sg-warmup-count {{
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  color: {TEXT};
}}
.sg-window {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.28rem;
  margin-top: 0.7rem;
}}
.sg-dot-on, .sg-dot-off {{
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 999px;
  display: inline-block;
}}
.sg-dot-on {{ background: {WARMING}; }}
.sg-dot-off {{ background: {LINE}; }}

.sg-buddy {{
  display: inline-flex;
  flex-direction: column;
  padding: 0.35rem 0.7rem;
  border-radius: 10px;
  background: {CANVAS};
  border: 1px solid {LINE};
  color: {TEXT};
  font-size: 0.82rem;
  font-weight: 600;
  margin: 0.15rem 0.35rem 0.15rem 0;
}}
.sg-buddy em {{
  font-style: normal;
  font-size: 0.72rem;
  font-weight: 500;
  color: {MUTED};
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}}
.sg-buddy-row {{
  display: flex;
  flex-wrap: wrap;
}}

.sg-section {{
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: {ACCENT};
  margin: 0.35rem 0 0.55rem 0;
}}

.sg-poll {{
  background: {CARD};
  border: 1px solid {LINE};
  border-left-width: 4px;
  border-radius: 12px;
  box-shadow: {SHADOW};
  padding: 0.95rem 1.1rem;
  margin: 0.15rem 0 1rem 0;
}}
.sg-poll-ok {{ border-left-color: {CLEAN}; }}
.sg-poll-bad {{ border-left-color: {HARDWARE}; }}
.sg-poll-idle {{ border-left-color: {LINE}; }}
.sg-poll-state {{
  font-size: 1.05rem;
  font-weight: 700;
  color: {TEXT};
}}
.sg-poll-meta {{
  margin-top: 0.25rem;
  color: {MUTED};
  font-size: 0.85rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}}
.sg-poll-error {{
  margin-top: 0.45rem;
  color: {HARDWARE};
  font-size: 0.82rem;
}}

.sg-preview {{
  border: 1px solid {LINE};
  border-left-width: 4px;
  border-radius: 12px;
  background: {CARD};
  box-shadow: {SHADOW};
  padding: 1rem 1.15rem;
  margin: 0.35rem 0 0.85rem 0;
}}
.sg-preview-dl {{
  margin: 0.7rem 0 0 0;
  display: grid;
  gap: 0.45rem;
}}
.sg-preview-dl div {{
  display: grid;
  grid-template-columns: 6.5rem 1fr;
  gap: 0.75rem;
}}
.sg-preview-dl dt {{
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: {MUTED};
}}
.sg-preview-dl dd {{
  margin: 0;
  color: {TEXT};
  font-size: 0.92rem;
  line-height: 1.45;
}}

.sg-results {{
  display: grid;
  gap: 0.55rem;
  margin-top: 0.7rem;
}}
.sg-result {{
  border: 1px solid {LINE};
  border-left-width: 4px;
  border-radius: 10px;
  padding: 0.7rem 0.85rem;
  background: {CANVAS};
}}
.sg-result-top {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
}}
.sg-result-meta {{
  margin-top: 0.3rem;
  color: {MUTED};
  font-size: 0.8rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}}
.sg-result-reason {{
  margin-top: 0.4rem;
  color: {TEXT};
  font-size: 0.88rem;
  line-height: 1.4;
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

.sg-arch {{
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}}
.sg-arch .sg-kpi-value {{
  font-size: 1.35rem;
}}
.sg-arch-band {{
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: {SLATE};
  margin: 0.85rem 0 0;
}}
.sg-arch-sources {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
}}
.sg-arch-node,
.sg-arch-step,
.sg-arch-out,
.sg-arch-set,
.sg-arch-note {{
  background: {CARD};
  border: 1px solid {LINE};
  border-radius: 12px;
  box-shadow: {SHADOW};
}}
.sg-arch-node {{
  padding: 0.95rem 1.05rem 1rem;
}}
.sg-arch-kicker {{
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: {ACCENT};
}}
.sg-arch-node strong,
.sg-arch-step strong,
.sg-arch-out strong,
.sg-arch-set strong,
.sg-arch-note strong {{
  display: block;
  color: {TEXT};
  font-size: 1rem;
  margin: 0.28rem 0 0.35rem;
}}
.sg-arch-node p,
.sg-arch-step p,
.sg-arch-out p,
.sg-arch-set p,
.sg-arch-note p {{
  margin: 0;
  color: {MUTED};
  font-size: 0.86rem;
  line-height: 1.45;
}}
.sg-arch-merge {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  height: 46px;
  margin-top: -0.2rem;
}}
.sg-arch-merge span {{
  display: block;
  width: 2px;
  height: 100%;
  margin: 0 auto;
  position: relative;
  background: linear-gradient({LINE}, {ACCENT});
  border-radius: 999px;
}}
.sg-arch-merge span::after {{
  content: "";
  position: absolute;
  left: -4px;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: {ACCENT};
  box-shadow: 0 0 0 4px rgba(13, 148, 136, 0.16);
  animation: sg-arch-drop 2.8s ease-in-out infinite;
}}
.sg-arch-merge span:nth-child(2)::after {{ animation-delay: 0.2s; }}
.sg-arch-merge span:nth-child(3)::after {{ animation-delay: 0.4s; }}
@keyframes sg-arch-drop {{
  0% {{ top: -8px; opacity: 0; }}
  16% {{ opacity: 1; }}
  100% {{ top: 34px; opacity: 0; }}
}}
.sg-arch-flow {{
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  padding-left: 1.85rem;
}}
.sg-arch-flow::before {{
  content: "";
  position: absolute;
  left: 0.42rem;
  top: 0.7rem;
  bottom: 0.7rem;
  width: 2px;
  background: {LINE};
  border-radius: 999px;
}}
.sg-arch-packet {{
  position: absolute;
  left: 0.02rem;
  width: 14px;
  height: 14px;
  border-radius: 999px;
  background: {ACCENT};
  box-shadow: 0 0 0 5px rgba(13, 148, 136, 0.16);
  z-index: 1;
  animation: sg-arch-travel 18s linear infinite;
}}
@keyframes sg-arch-travel {{
  0% {{ top: 0.2rem; opacity: 0; }}
  4% {{ opacity: 1; }}
  96% {{ opacity: 1; }}
  100% {{ top: calc(100% - 1.3rem); opacity: 0; }}
}}
.sg-arch-step {{
  padding: 0.85rem 1rem 0.95rem;
  animation: sg-arch-wake 18s ease-in-out infinite;
}}
.sg-arch-step:nth-child(2) {{ animation-delay: 0s; }}
.sg-arch-step:nth-child(3) {{ animation-delay: 2.7s; }}
.sg-arch-step:nth-child(4) {{ animation-delay: 5.4s; }}
.sg-arch-step:nth-child(5) {{ animation-delay: 8.1s; }}
.sg-arch-step:nth-child(6) {{ animation-delay: 10.8s; }}
.sg-arch-step:nth-child(7) {{ animation-delay: 13.5s; }}
@keyframes sg-arch-wake {{
  0%, 7% {{
    border-color: {ACCENT};
    box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12), {SHADOW};
  }}
  16%, 100% {{
    border-color: {LINE};
    box-shadow: {SHADOW};
  }}
}}
.sg-arch-step-h {{
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 0.35rem;
}}
.sg-arch-step-h strong {{ margin: 0; }}
.sg-arch-n {{
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.72rem;
  font-weight: 600;
  color: {OBSERVED};
  background: #F0FDFA;
  border-radius: 999px;
  padding: 0.14rem 0.48rem;
}}
.sg-arch-mono {{
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.78rem;
  color: {TEXT};
}}
.sg-arch-checks {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.5rem;
  margin-top: 0.75rem;
}}
.sg-arch-check {{
  border: 1px solid {LINE};
  border-radius: 8px;
  background: {CANVAS};
  padding: 0.55rem 0.7rem;
  animation: sg-arch-check 4.8s ease-in-out infinite;
}}
.sg-arch-check:nth-child(2) {{ animation-delay: 1.6s; }}
.sg-arch-check:nth-child(3) {{ animation-delay: 3.2s; }}
.sg-arch-check b {{
  display: block;
  color: {TEXT};
  font-size: 0.82rem;
  margin-bottom: 0.15rem;
}}
.sg-arch-check span {{
  color: {MUTED};
  font-size: 0.75rem;
  line-height: 1.35;
}}
@keyframes sg-arch-check {{
  0%, 100% {{ border-color: {LINE}; background: {CANVAS}; }}
  16%, 42% {{ border-color: {ACCENT}; background: #F0FDFA; }}
}}
.sg-arch-queue {{
  margin: 0.7rem 0 0;
  color: {MUTED};
  font-size: 0.8rem;
}}
.sg-arch-queue span {{
  display: inline-block;
  margin-right: 0.4rem;
  padding: 0.08rem 0.48rem;
  border: 1px dashed {SLATE};
  border-radius: 999px;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.72rem;
  letter-spacing: 0.04em;
  color: {SLATE};
  animation: sg-arch-queue 2.4s ease-in-out infinite;
}}
@keyframes sg-arch-queue {{
  0%, 100% {{ opacity: 0.4; }}
  50% {{ opacity: 1; }}
}}
.sg-arch-poll {{
  display: inline-block;
  margin-right: 0.35rem;
  padding: 0.08rem 0.42rem;
  border-radius: 999px;
  background: #F0FDFA;
  color: {OBSERVED};
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.72rem;
  font-weight: 600;
  animation: sg-arch-poll 1s steps(2, end) infinite;
}}
@keyframes sg-arch-poll {{
  0%, 100% {{ opacity: 1; }}
  50% {{ opacity: 0.35; }}
}}
.sg-arch-outs {{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.75rem;
}}
.sg-arch-out {{
  border-top: 3px solid var(--c);
  padding: 0.9rem 1rem 1rem;
  animation: sg-arch-float 5.6s ease-in-out infinite;
}}
.sg-arch-out:nth-child(2) {{ animation-delay: 0.35s; }}
.sg-arch-out:nth-child(3) {{ animation-delay: 0.7s; }}
.sg-arch-out:nth-child(4) {{ animation-delay: 1.05s; }}
@keyframes sg-arch-float {{
  0%, 100% {{ transform: translateY(0); }}
  50% {{ transform: translateY(-4px); }}
}}
.sg-arch-pair {{
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 0.75rem;
  align-items: stretch;
}}
.sg-arch-set {{ padding: 1rem 1.1rem 1.05rem; }}
.sg-arch-join-mark {{
  align-self: center;
  color: {ACCENT};
  font-size: 1.35rem;
  font-weight: 600;
  line-height: 1;
}}
.sg-arch-pills {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.75rem;
}}
.sg-arch-pill {{
  border: 1px solid {LINE};
  background: {CANVAS};
  border-radius: 999px;
  padding: 0.28rem 0.65rem;
  font-size: 0.8rem;
  font-weight: 600;
  color: {TEXT};
}}
.sg-arch-pill-in {{
  background: #F0FDFA;
  border-color: #99F6E4;
  animation: sg-arch-arrive 2.8s ease-in-out infinite;
}}
.sg-arch-pill-in:nth-child(2) {{ animation-delay: 0.25s; }}
.sg-arch-pill-in:nth-child(3) {{ animation-delay: 0.5s; }}
.sg-arch-pill-in:nth-child(4) {{ animation-delay: 0.75s; }}
@keyframes sg-arch-arrive {{
  0%, 100% {{ box-shadow: 0 0 0 0 rgba(13, 148, 136, 0); }}
  35% {{ box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.18); }}
}}
.sg-arch-foot {{
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 0.75rem;
}}
.sg-arch-note {{ padding: 1rem 1.1rem 1.05rem; }}
.sg-arch-note strong {{ font-size: 1rem; }}

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

/* Decision trace — three tiers, one scored hour */
.sg-trace {{
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  margin: 0.25rem 0 0.85rem 0;
}}
.sg-trace-step {{
  display: grid;
  grid-template-columns: 2.2rem 1fr;
  gap: 0.75rem;
  padding: 0.8rem 0.95rem;
  border: 1px solid {LINE};
  border-radius: 12px;
  background: {CARD};
  box-shadow: {SHADOW};
}}
.sg-trace-n {{
  width: 2rem;
  height: 2rem;
  border-radius: 999px;
  border: 2px solid {LINE};
  font-weight: 700;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  display: flex;
  align-items: center;
  justify-content: center;
  background: {CANVAS};
}}
.sg-trace-body {{ min-width: 0; }}
.sg-trace-head {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
}}
.sg-trace-title {{
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: {MUTED};
}}
.sg-trace-line {{
  color: {TEXT};
  font-weight: 600;
  font-size: 0.95rem;
  margin-top: 0.3rem;
}}
.sg-trace-detail {{
  color: {MUTED};
  font-size: 0.84rem;
  line-height: 1.45;
  margin-top: 0.2rem;
}}

/* Neighbor agreement table */
.sg-neighbor {{ margin: 0 0 0.85rem 0; }}
.sg-table {{
  width: 100%;
  border-collapse: collapse;
  margin-top: 0.55rem;
  font-size: 0.86rem;
}}
.sg-table th {{
  text-align: left;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: {MUTED};
  padding: 0.35rem 0.5rem;
  border-bottom: 1px solid {LINE};
}}
.sg-table td {{
  padding: 0.45rem 0.5rem;
  border-bottom: 1px solid {LINE};
  color: {TEXT};
  vertical-align: middle;
}}
.sg-table tr:last-child td {{ border-bottom: none; }}
.sg-mono {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 0.82rem; }}

/* Verdict ribbon under the charts */
.sg-ribbon {{
  background: {CARD};
  border: 1px solid {LINE};
  border-radius: 12px;
  box-shadow: {SHADOW};
  padding: 0.85rem 1.1rem;
  margin: 0.25rem 0 0.85rem 0;
}}
.sg-ribbon-row {{
  display: grid;
  grid-template-columns: repeat(24, minmax(0, 1fr));
  gap: 0.22rem;
}}
.sg-ribbon-cell {{
  display: block;
  height: 0.9rem;
  border-radius: 4px;
  box-sizing: border-box;
}}
.sg-ribbon-focus {{
  outline: 2px solid {TEXT};
  outline-offset: 1px;
}}

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
  .sg-kpis, .sg-kpis-4, .sg-kpis-5 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .sg-readings {{ grid-template-columns: 1fr; }}
  .sg-identity {{ flex-direction: column; }}
  .sg-preview-dl div {{ grid-template-columns: 1fr; gap: 0.15rem; }}
  .sg-alert-legend {{ grid-template-columns: 1fr; }}
  .sg-arch-sources, .sg-arch-outs, .sg-arch-checks, .sg-arch-foot {{
    grid-template-columns: 1fr;
  }}
  .sg-arch-pair {{ grid-template-columns: 1fr; }}
  .sg-arch-join-mark {{ display: none; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .sg-arch-packet,
  .sg-arch-step,
  .sg-arch-check,
  .sg-arch-out,
  .sg-arch-pill-in,
  .sg-arch-merge span::after,
  .sg-arch-queue span,
  .sg-arch-poll {{
    animation: none;
  }}
}}
</style>
"""
