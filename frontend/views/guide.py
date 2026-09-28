"""Guide: live 48, warm-up, and the Mumbai replay."""

from __future__ import annotations

import streamlit as st

from chrome import page_header
from theme import CLEAN, HARDWARE, SLATE, WARMING, WEATHER


def render_guide() -> None:
    page_header(
        "How QC works",
        "48 live stations. A verdict waits for 24 hours. Palam is not on this map.",
    )
    st.markdown(
        f"""
<div class="sg-guide">
<h3>The 10-second story</h3>
<p>A lone 55 °C at Santa Cruz is hardware. The same heat on Santa Cruz, Colaba, and Juhu is weather.
The raw line stays solid. A dashed correction and band appear only when the sensor is distrusted.
Network pages a technician from 7-day health. Weather never appears on that list.</p>

<h3>Live 48</h3>
<p>The map is the 48 stations the model was judged on. The camera starts on Mumbai and Safdarjung.
Palam is outside that set, so it is not on the map.</p>
<p>Safdarjung has no buddies inside the 48. A suspicious hour there stays unconfirmed.
Weather versus hardware cannot be called at that site.</p>

<h3>24-hour warm-up</h3>
<p>A station shows its raw hour as soon as it arrives. Until 24 hourly values exist, the state is
<strong>warming up</strong> — not a fault, and not a verdict. The 24th hour is the first real label.</p>

<h3>Three checks</h3>
<div class="sg-tier"><div class="sg-tier-n">1</div><div><strong>Physical rules</strong> — range, a 12-hour freeze, a missing channel, dew point.</div></div>
<div class="sg-tier"><div class="sg-tier-n">2</div><div><strong>LSTM</strong> — last 24 hours. Unusual reconstruction is a candidate, including real weather.</div></div>
<div class="sg-tier"><div class="sg-tier-n">3</div><div><strong>Buddy check</strong> — correlation-weighted neighbors, at least two. Agreement is weather (amber, health unchanged). Disagreement is hardware (rose).</div></div>

<h3>Replay</h3>
<p>Control plays the Mumbai stories through the same ingest path, ending 2024-12-31T23:00:00Z.
Hardware is Santa Cruz at 55 °C. Weather is +8 °C on Santa Cruz, Colaba, and Juhu.
Live hours and replay hours are separate timelines.</p>

<h3>Colors</h3>
<p>
<span class="sg-chip" style="border-color:{CLEAN};color:{CLEAN}">Clean</span>
<span class="sg-chip" style="border-color:{WEATHER};color:{WEATHER}">Genuine weather</span>
<span class="sg-chip" style="border-color:{HARDWARE};color:{HARDWARE}">Hardware</span>
<span class="sg-chip" style="border-color:{SLATE};color:{SLATE}">Unconfirmed</span>
<span class="sg-chip" style="border-color:{WARMING};color:{WARMING}">Warming up</span>
</p>
<p>Weather is never red. The health line is a 7-day sensor flag rate. Genuine weather does not count.
Alerts treat a storm as amber and hardware — including a thermo failure or a missing packet — as rose.
A lone spike is Watch until health drops; repeated hardware is Page.</p>

<h3>How to run</h3>
</div>
""",
        unsafe_allow_html=True,
    )
    st.code(
        "python scripts/run_api.py\n"
        "python scripts/run_dashboard.py",
        language="text",
    )
    st.caption("This dashboard polls the product API only. It does not call port 8001.")
