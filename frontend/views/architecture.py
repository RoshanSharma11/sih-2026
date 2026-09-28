"""Architecture: one animated page of the live hour."""

from __future__ import annotations

import streamlit as st

from chrome import page_header, render_html
from theme import CLEAN, HARDWARE, SLATE, WEATHER
from v2_metrics import load_v2_metrics, metrics_html, overlay_figure, reconstruction_figure


def architecture_html() -> str:
    return f"""
<div class="sg-arch">
  <p class="sg-arch-band">Where an hour starts</p>
  <div class="sg-arch-sources">
    <article class="sg-arch-node">
      <div class="sg-arch-kicker">Live</div>
      <strong>IMD poller</strong>
      <p>A token, then the state snapshot. The station <span class="sg-arch-mono">ID</span> matches <span class="sg-arch-mono">aws_id</span>. The same hour is not posted twice.</p>
    </article>
    <article class="sg-arch-node">
      <div class="sg-arch-kicker">Demo</div>
      <strong>Replay and inject</strong>
      <p>Control plays a Mumbai story, or arms a custom overlay. The change lands on the next ingested hour, before QC.</p>
    </article>
    <article class="sg-arch-node">
      <div class="sg-arch-kicker">Clean</div>
      <strong>Streamer</strong>
      <p>Clean hours only. It posts the stations on screen plus their one-hop buddies.</p>
    </article>
  </div>
  <div class="sg-arch-merge" aria-hidden="true"><span></span><span></span><span></span></div>

  <p class="sg-arch-band">One hour inside the API</p>
  <div class="sg-arch-flow">
    <div class="sg-arch-packet" aria-hidden="true"></div>

    <article class="sg-arch-step">
      <div class="sg-arch-step-h"><span class="sg-arch-n">01</span><strong>Arrive</strong></div>
      <p><span class="sg-arch-mono">POST /ingest</span> with <span class="sg-arch-mono">temp_c</span>, <span class="sg-arch-mono">pres_hpa</span>, and <span class="sg-arch-mono">rhum_pct</span>. An unknown station is 404. No training scaler is 400. The same hour twice is 409.</p>
    </article>

    <article class="sg-arch-step">
      <div class="sg-arch-step-h"><span class="sg-arch-n">02</span><strong>Mutate only when armed</strong></div>
      <p><span class="sg-arch-mono">inject.py</span> changes this hour before any model sees it. A live hour with nothing armed stays as it arrived.</p>
    </article>

    <article class="sg-arch-step">
      <div class="sg-arch-step-h"><span class="sg-arch-n">03</span><strong>Write the raw hour</strong></div>
      <p>Observed temperature, pressure, and humidity are stored as they arrived. A later correction is a separate column. The raw values stay.</p>
    </article>

    <article class="sg-arch-step">
      <div class="sg-arch-step-h"><span class="sg-arch-n">04</span><strong>Warm up, or score</strong></div>
      <p>Under 24 hourly rows the state is warming up. The raw hour is shown, the label is empty, and v2 is not called. The 24th hour is the first verdict.</p>
    </article>

    <article class="sg-arch-step">
      <div class="sg-arch-step-h"><span class="sg-arch-n">05</span><strong>QC in this process</strong></div>
      <p>The adapter renames the fields and calls <span class="sg-arch-mono">v2.engine.process_aws_data</span>. The graph model stays off. The window and the neighbors' hours go in together.</p>
      <div class="sg-arch-checks">
        <div class="sg-arch-check"><b>1 · Physical rules</b><span>Range, a stuck sensor, a missing channel, dew point.</span></div>
        <div class="sg-arch-check"><b>2 · LSTM</b><span>The last 24 hours. An odd reconstruction is only a candidate.</span></div>
        <div class="sg-arch-check"><b>3 · Buddies</b><span>Correlation-weighted neighbors. At least two. Agreement is weather. Disagreement is hardware.</span></div>
      </div>
      <p class="sg-arch-queue"><span>TIMING</span> queued beside the score. The sentence shows up later on Station. Ingest does not wait.</p>
    </article>

    <article class="sg-arch-step">
      <div class="sg-arch-step-h"><span class="sg-arch-n">06</span><strong>Store the overlay, then the console reads</strong></div>
      <p>Predicted values, the band, and the reason sit beside the raw hour. An alert is written when the label is not clean. Seven-day health ignores weather. <span class="sg-arch-poll">GET</span> Network, Station, and Alerts poll about once a second.</p>
    </article>
  </div>

  <p class="sg-arch-band">How a scored hour lands</p>
  <div class="sg-arch-outs">
    <article class="sg-arch-out" style="--c:{CLEAN}">
      <div class="sg-arch-kicker">Clean</div>
      <strong>Trusted hour</strong>
      <p>The observation stands. No alert. Health is unchanged.</p>
    </article>
    <article class="sg-arch-out" style="--c:{WEATHER}">
      <div class="sg-arch-kicker">Weather</div>
      <strong>Neighbors agree</strong>
      <p>The same extreme shows up nearby. Amber on the map. Health does not move.</p>
    </article>
    <article class="sg-arch-out" style="--c:{HARDWARE}">
      <div class="sg-arch-kicker">Hardware</div>
      <strong>The sensor is the outlier</strong>
      <p>A physical fault, or the model and the neighbors disagree. Rose. Health counts it.</p>
    </article>
    <article class="sg-arch-out" style="--c:{SLATE}">
      <div class="sg-arch-kicker">Unconfirmed</div>
      <strong>Not enough buddies</strong>
      <p>Flagged, with fewer than two usable neighbors. Safdarjung is the isolate inside the 48.</p>
    </article>
  </div>

  <p class="sg-arch-band">The map and the stream</p>
  <div class="sg-arch-pair">
    <article class="sg-arch-set">
      <div class="sg-arch-kicker">View</div>
      <strong>What the page is looking at</strong>
      <p>Santa Cruz on its own is a view of one station.</p>
      <div class="sg-arch-pills"><span class="sg-arch-pill">Santa Cruz</span></div>
    </article>
    <div class="sg-arch-join-mark" aria-hidden="true">→</div>
    <article class="sg-arch-set">
      <div class="sg-arch-kicker">Ingest</div>
      <strong>What actually gets posted</strong>
      <p>One-hop buddies come along, so the third check has neighbors.</p>
      <div class="sg-arch-pills">
        <span class="sg-arch-pill">Santa Cruz</span>
        <span class="sg-arch-pill sg-arch-pill-in">Juhu</span>
        <span class="sg-arch-pill sg-arch-pill-in">Colaba</span>
        <span class="sg-arch-pill sg-arch-pill-in">Alibag</span>
      </div>
    </article>
  </div>

  <div class="sg-arch-foot">
    <article class="sg-arch-note">
      <strong>QC runs in the API process</strong>
      <p>Production QC is <span class="sg-arch-mono">v2.engine.process_aws_data</span>, called in-process with the graph model off. The console only reads. It does not score an hour.</p>
    </article>
    <article class="sg-arch-note">
      <strong>The live catalog is the 48</strong>
      <p>Palam is outside that set, so it is not on the map. A station with fewer than 24 hours stays on the warming-up path and never reaches the four labels above.</p>
    </article>
  </div>
</div>
"""


def render_architecture() -> None:
    page_header(
        "Architecture",
        "One hour moves from the sky, through QC in this process, onto the map.",
        show_status=False,
    )
    render_html(architecture_html())
    st.caption("The dot is one hour. It loops. Warming up leaves before the model.")
    _render_v2_metrics()


def _render_v2_metrics() -> None:
    metrics = load_v2_metrics()
    if metrics is None:
        return
    render_html(metrics_html(metrics))
    recon = reconstruction_figure(metrics)
    overlay = overlay_figure(metrics)
    if recon is None and overlay is None:
        return
    if recon is not None and overlay is not None:
        left, right = st.columns(2)
        with left:
            st.plotly_chart(recon, theme=None, width="stretch")
        with right:
            st.plotly_chart(overlay, theme=None, width="stretch")
        return
    st.plotly_chart(recon or overlay, theme=None, width="stretch")
