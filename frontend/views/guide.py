"""Guide: three-tier QC, view vs ingest, neighborhood vs spike."""

from __future__ import annotations

import streamlit as st

from chrome import page_header
from theme import CLEAN, HARDWARE, SLATE, WEATHER


def render_guide() -> None:
    page_header(
        "How QC works",
        "Physical rules, then LSTM, then a two-buddy check. Delhi does not validate Mumbai.",
    )
    st.markdown(
        f"""
<div class="sg-guide">
<h3>The 10-second story</h3>
<p>A judge should leave able to say: <strong>a storm around Palam is not a broken sensor</strong>.
Raw temperature, pressure, and humidity stay on the chart. The dashed line is a reconstruction overlay, not a rewrite.</p>

<h3>Three tiers (one engine)</h3>
<ol>
<li><strong>Physical rules</strong> — impossible range, stuck values, missing channels. Hard fail is a physical fault.</li>
<li><strong>LSTM autoencoder</strong> — last 24 hours. Unusual reconstruction error is a candidate anomaly, including real weather.</li>
<li><strong>Buddy check</strong> — inverse-distance weights on the ML graph, not NORTH/WEST. Needs <strong>two</strong> usable neighbors at the same hour. If they agree, it is genuine weather (amber, health unchanged). If they disagree, it is hardware (rose).</li>
</ol>
<p>Isolates and one-buddy hours skip tier 3 and land <strong>unconfirmed</strong> (slate). Honesty over a fake spatial call.</p>

<h3>View set vs ingest set</h3>
<p>The map and charts show the <strong>view set</strong> you pick on Network. The streamer POSTs the <strong>ingest set</strong>: those stations plus each one’s 1-hop buddies, so Palam can still be checked against Safdarjung even if you only wanted Palam on screen.</p>
<p>If you started the streamer with <code>--stations</code>, that CLI list wins over the dashboard picker.</p>

<h3>Judge script</h3>
<ol>
<li><strong>Network</strong> — calm teal on Palam, Safdarjung, 42139, and Santacruz.</li>
<li><strong>Control → Storm around Palam</strong> — Palam and its buddies go amber; Santacruz stays teal.</li>
<li><strong>Reset</strong>, then <strong>Break Palam temperature</strong> — only Palam goes rose; Safdarjung stays teal.</li>
<li><strong>Station</strong> on Palam — solid observed series still there; dashed overlay; verdict text; contribution names the channel.</li>
</ol>

<h3>Colors</h3>
<p>
<span class="sg-chip" style="border-color:{CLEAN};color:{CLEAN}">Clean</span>
<span class="sg-chip" style="border-color:{WEATHER};color:{WEATHER}">Genuine weather</span>
<span class="sg-chip" style="border-color:{HARDWARE};color:{HARDWARE}">Hardware</span>
<span class="sg-chip" style="border-color:{SLATE};color:{SLATE}">Unconfirmed</span>
</p>
<p>Weather is never red. Health is a 7-day maintenance index and ignores weather alerts.</p>

<h3>How to run</h3>
</div>
""",
        unsafe_allow_html=True,
    )
    st.code(
        "python scripts/run_api.py\n"
        "python -m skyguard.data.stream --api http://127.0.0.1:8000 --ms 200 "
        "--start 2024-07-01T00:00:00Z --stations 42181 --with-buddies\n"
        "python scripts/run_dashboard.py",
        language="text",
    )
    st.caption("Do not point this dashboard at the ML eval server on port 8001. Field names differ.")
