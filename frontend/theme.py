CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap');

html, body, [class*="css"] {
  font-family: "IBM Plex Sans", system-ui, sans-serif;
}

.stApp { background: #070b14; }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, .stAppDeployButton { visibility: hidden; height: 0; }
div[data-testid="stToolbar"] { visibility: hidden; }
.block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1320px; }

h1, h2, h3 { letter-spacing: -0.02em; }
.sg-kicker {
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #2dd4bf;
  margin-bottom: 0.15rem;
}
.sg-sub {
  color: #8b9bb4;
  margin-top: -0.4rem;
  margin-bottom: 0.8rem;
}
.sg-chip {
  display: inline-block;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  margin-right: 0.35rem;
}
.sg-chip-ok { background: #12352f; color: #2dd4bf; }
.sg-chip-bad { background: #3a1520; color: #fda4af; }
.sg-chip-idle { background: #1b2436; color: #8b9bb4; }

.sg-verdict {
  border: 1px solid #1e2a3f;
  border-left-width: 4px;
  border-radius: 12px;
  padding: 1rem 1.15rem;
  background: #101827;
  margin: 0.25rem 0 0.75rem 0;
}
.sg-verdict-weather { border-left-color: #f5b942; }
.sg-verdict-hardware { border-left-color: #f43f5e; }
.sg-verdict-unknown { border-left-color: #94a3b8; }
.sg-verdict-clean { border-left-color: #2dd4bf; }
.sg-verdict-kicker {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #8b9bb4;
  margin-bottom: 0.35rem;
}
.sg-verdict-text {
  font-size: 1.15rem;
  font-weight: 600;
  color: #e8eef7;
  line-height: 1.4;
}
.sg-verdict-meta {
  margin-top: 0.45rem;
  color: #8b9bb4;
  font-size: 0.85rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}

.sg-overlay {
  display: inline-block;
  margin: 0.15rem 0.35rem 0.15rem 0;
  padding: 0.28rem 0.65rem;
  border-radius: 8px;
  background: #18233a;
  color: #f5b942;
  font-size: 0.8rem;
  font-weight: 600;
}

.sg-legend span {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin-right: 1rem;
  color: #8b9bb4;
  font-size: 0.8rem;
}
.sg-dot {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 999px;
  display: inline-block;
}

div[data-testid="stMetric"] {
  background: #101827;
  border: 1px solid #1e2a3f;
  border-radius: 12px;
  padding: 0.65rem 0.85rem;
}
</style>
"""
