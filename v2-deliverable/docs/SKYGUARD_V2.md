# SkyGuard V2 — full briefing

Read this once and you should be able to explain the problem, the product, the numbers, the plots, the files, what is done, what is not, and where it is weak.

The I/O contract for backend/frontend is a **different** file: [`CONTRACT.md`](CONTRACT.md). This file is the story.

| | |
|---|---|
| Name | SkyGuard AI |
| Problem | SIH 2026 **PS 26073** |
| Org | Ministry of Earth Sciences / India Meteorological Department |
| Category | **Software** (not hardware / ESP32) |
| Theme | Disaster management |
| What it is | Real-time QC for Automatic Weather Stations using **only** T (°C), P (hPa), H (%) |
| What it is not | A weather forecast, a Palam-only demo, or a rewrite of raw observations |

---

## 1. The problem, in full

AWS stations stream temperature, pressure, and humidity into forecasts, aviation, agriculture, and disaster systems. Those streams are dirty: sensor faults, frozen values, comms gaps, calibration drift, power glitches, corruption. A 55 °C reading can be a broken probe **or** a heatwave. Thresholds cannot tell those apart.

**PS 26073 asks for an AI/ML system that:**

- Detects anomalies in real time on T / P / H only.
- Finds spikes, frozen sensors, communication errors, (and ideally drift).
- Learns temporal / seasonal normality.
- Checks multivariate consistency among T, P, H.
- Distinguishes **genuine weather** from **sensor/data faults**.
- Emits confidence, explainable reasoning, sensor health / maintenance hint.
- Optionally suggests a corrected last hour.
- Scales across a large network.
- Is evaluated on **anomaly-injected** data.

**Official example (this is the whole product):** an AWS reports 55 °C, wild humidity and pressure; neighbors are normal. The system must call that **hardware**, alert, and suggest a correction — not call it a heatwave.

**Grand challenge line:** a self-aware, self-healing observation network that stays trustworthy under all conditions.

**Expected outputs:** real-time alerts, severity/confidence, root-cause class, dashboard, sensor health, optional corrected values.

**Suggested tech we did not blindly copy:** SHAP/LIME (preferable, not mandatory); ESP32 edge AI (wrong category — this is **software**). Energy score here is **CPU ingest milliseconds**, not milliwatts on a microcontroller.

**Inputs allowed:** historical AWS, **simulated anomalies**, or streams. We use 151-station hourly Meteostat 2020–2024, inject faults with the official-style seed-**42** recipe, and report on the **48** stations that have a live IMD AWS/ARG within 5 km.

---

## 2. The constraint that decided the architecture

The historical hours are **clean**. There are almost no real sensor faults in 2020–2023. Official scoring is **injected**. So:

| Data | What it can teach | What it cannot teach |
|---|---|---|
| Clean 2020–2022 | Diurnal/seasonal climatology, T–RH–P physics, typical neighbor agreement | Weather vs hardware |
| Injected 2020–2022 (train) / 2023 (freeze) | Spatial consensus, overlay under known fault types | Must not touch 2024 |
| Injected 2024, **48 live-mapped stations only** | The number we report | Never used to pick thresholds |

That is why:

- A **physics-informed LSTM autoencoder** is the right model for “does this 24×3 window look like this station’s climate?”
- A GAT trained to **reconstruct** a clean primary from neighbors is useless (neighbors already agree; val MSE stuck ~0.0107 at random init).
- **CSDI / DDIM** can fit a noise net and still fail at sampling (last-hour MAE 4.7–8.5 in scaled [0,1]). A complete 24×3 window is the wrong place for 50-step diffusion.
- Weather vs hardware has to be a **spatial consensus** problem (do neighbors share the shock?), taught on **injected** spatial labels or implemented as CW-IDW — not as reconstruction.

We kept three models. We changed what they are trained to do. Failed checkpoints stay off `/ingest`.

---

## 3. What Version 2 actually does

One function:

```text
process_aws_data(payload) → JSON
```

Each hour, for one station, given the last 24 hours and neighbor windows, it returns:

1. A **five-way label**
2. Whether that hour is anomalous
3. A **fault type** when anomalous
4. A **confidence** in [0, 1]
5. A one-sentence **reason**
6. Physics card (Magnus dew point)
7. Tier 1 / 2 / 3 diagnostics
8. A **predicted** last hour and optional **90% band**
9. A 7-day **health** index (weather does not count)
10. `"timing": null` on this call; TIMING is polled afterwards

### 3.1 The five labels (locked)

| Label | Meaning | Color | Lowers 7-day health? | Overlay |
|---|---|---|---|---|
| `CLEAN` | Last-hour-weighted LSTM score under the frozen 2023 p99 | teal `#0D9488` | no | none — predicted copies observed |
| `PHYSICAL_FAULT` | Hard physical rule: missing, freeze, thermo, (sometimes range) | rose `#E11D48` | **yes** | dashed + band if imputable |
| `HARDWARE_ANOMALY` | LSTM (or soft step/range) suspicious **and neighbors disagree** | rose `#E11D48` | **yes** | dashed + band |
| `GENUINE_WEATHER_EVENT` | Suspicious **and neighbors agree** | amber `#D97706` | **no** | **none** |
| `UNCONFIRMED_ANOMALY` | Suspicious but Tier 3 could not run (<2 buddies, bad window) | slate `#64748B` | **yes** | LSTM last step, **no band** |

**Weather is never red.** `is_anomaly` is still true for weather (it is unusual). Those two facts must not be collapsed into one badge.

`fault_type`: `SPIKE` | `FREEZE` | `DRIFT` | `COMMUNICATION` | `THERMO` | `STORM` | `UNCONFIRMED`.

### 3.2 The three tiers

```text
24h T/P/H + buddy windows (±1 h, 100 km)
        │
        ▼
[T1] Hard QC
        missing → COMMUNICATION
        range / step (WMO-style)
        freeze: 12 h one channel, or 6 h on two channels
        Magnus Td > T + 0.1 °C → THERMO
        STEP/RANGE is “soft”: still ask neighbors (the 55 °C story)
        hard fail (freeze / comms / thermo) → PHYSICAL_FAULT, confidence 1
        ▼
[T2] PIML LSTM-AE  (24×3 → hidden 64 → latent 32 → recon)
        score s = 0.7 · MSE(last 3 h) + 0.3 · MSE(24 h)
        threshold = 2023 p99 of s = 0.008487  (never fit on 2024)
        s below → CLEAN
        ▼
[T3] Spatial consensus  (product ingest = CW-IDW)
        w ∝ exp(corr / 0.35) / d²
        agree if |ΔT|<3 °C, |ΔRH|<8 %, |ΔP|<2 hPa; min 2 buddies
        agree → GENUINE_WEATHER_EVENT
        disagree → HARDWARE_ANOMALY
        <2 usable → UNCONFIRMED_ANOMALY
        ▼
Overlay  only HARDWARE / PHYSICAL
        last-hour Gaussian μ ± 1.64σ (90%)
        CLEAN / WEATHER: predicted = observed, band null
```

**Self-healing** means: keep the raw row; draw a corrected last hour **only when we distrust the sensor**. We do not invent a different climate for a real storm.

### 3.3 Stations

| Set | Count | Role |
|---|---|---|
| Train / val scalers | **151** | 2020–2022 train, 2023 val |
| Live map + reported eval | **48** IMD-mapped (`stations_judge48.csv`) | Palam `42181` is **out**; Safdarjung `42182` is **in** |
| Demo cluster | Mumbai `43003, 43057, 43002, 43058` + `42182` | Stories 1–6 |

Unknown `station_id` (no scaler) → refuse. HTTP **400**. We do not borrow Palam’s scaler for a mystery id.

`42182` has **zero buddies inside the live 48**. If you only ingest the 48, Safdarjung cannot do weather vs hardware (Tier 3 skips). Freeze/comms still work as physical faults. **Ingest the Mumbai four together** or stories 2 vs 3 become unconfirmed.

### 3.4 GAT vs CW-IDW (explicit)

| Path | Tier 3 | Why |
|---|---|---|
| Product ingest / seed-42 eval / `POST /ingest` | **CW-IDW** | Official SPIKE injector: GAT recall **41%**, CW-IDW **98.5%** |
| `python -m v2.demo_engine` | **GAT** (`method: stgnn`) | Trained on +8 °C singleton vs shared shock; 2023 gates passed; Mumbai 2 vs 3 is that story |

GAT is not “failed.” It is **the wrong expert for the official SPIKE recipe**. Shipping it on ingest would hurt the number judges score. The demo still uses it because that is the spatial decision it was trained for.

---

## 4. How it is used

### 4.1 Operator (what the dashboard is for)

Every hour a station ticks:

- **Teal** — believe the sensor.
- **Amber** — unusual weather; keep the observation; do not page maintenance.
- **Rose** — do not believe the sensor; look at the dashed overlay (~25 °C when the probe said 55); schedule maintenance if 7-day health drops.
- **Slate** — we refused to guess (not enough neighbors or no 24 h window).

Solid line is always raw. Dashed line and band exist only on hardware/physical.

### 4.2 Backend

1. Write the raw row first (including nulls). Never overwrite it.
2. Build 24 h `window` + buddy `window`s from SQLite.
3. `from v2.engine import process_aws_data` (canonical) or `POST http://127.0.0.1:8001/ingest`.
4. Store ML JSON in **other** columns.
5. If `is_anomaly`, poll `GET /stations/{id}/timing?ts=` and attach.
6. Optional IMD warning chip on amber — **after** ML, never as a feature.

Exact JSON: [`CONTRACT.md`](CONTRACT.md). Captured files: [`examples/`](examples/).

### 4.3 Demo / video

```text
cd v2-deliverable
pip install -r requirements.txt
python -m v2.demo_engine          # six stories, GAT on, TIMING poll
uvicorn v2.main:app --port 8001   # optional HTTP, CW-IDW
```

No 151-station raw dump is required. `v2/data/demo_windows.json` holds 24 aligned hours ending **2024-12-31T23:00:00** for the five demo ids.

### 4.4 Stories to play (must match the PS)

| # | What you send | What you must see |
|---|---|---|
| 1 | Clean Mumbai Santa Cruz `43003` | `CLEAN`, no overlay |
| 2 | Last hour 55 °C / 95% / 980 hPa on `43003` only; Colaba/Juhu/Juhu-airport **normal** | `HARDWARE_ANOMALY`, dashed ~**25.2 °C**, band ~24.1–26.2, TIMING hour **22** mostly temp |
| 3 | Same +8 °C on Santa Cruz **and** Colaba **and** Juhu | `GENUINE_WEATHER_EVENT`, **no** overlay, weather **does not** lower health |
| 4 | Temperature frozen **12 h** | `PHYSICAL_FAULT` / `FREEZE` |
| 5 | `temp: null` | `PHYSICAL_FAULT` / `COMMUNICATION` |
| 6 | Repeat hardware hours | `health.state` leaves `HEALTHY` |
| 7 | Station `99999` | refused (no scaler) |

If 2 and 3 look the same, buddies were not ingested.

---

## 5. Judges’ criteria — what we claim, with evidence

| Criterion | Weight | What “winning” looks like here | What we actually have | What we refuse to fake |
|---|---|---|---|---|
| Innovation | 25% | Physics in the net + spatial consensus that matches the 55 °C story + honest GAT | Magnus/Clausius penalty (λ=0.1); CW-IDW; task-GAT for demo 2 vs 3; Gaussian overlay not DDIM | A reconstruction GAT that does not move val MSE |
| Accuracy | 20% | Freeze/comms in rules; spike vs storm in spatial; FPR not 60% | Table in §6 | Calling 32.5% FPR “solved”; claiming drift is solved |
| Real-time | 15% | Fast CPU ingest, no diffusion | p50 **13.6 ms**, p95 **39 ms** | CSDI 16-step on the hot path |
| Explainability | 10% | Operator English + physics + neighbors + when | `reason`, Td−T, bars, mix/corr, TIMING | SHAP as the product |
| Scalability | 10% | Many stations, live subset honest | 151 scalers, **48 live**, unknown id 400 | “We monitor Palam” |
| Deployability | 10% | One in-process call, CPU | this folder + CONTRACT | ESP32 / TFLite |
| Visualization | 5% | Raw vs overlay, weather amber | CONTRACT §5–7; frontend still must build it | Overlaying weather |
| Energy | 5% | Software category → measure CPU | p95 39 ms | An ESP32 slide |

**Talk track (true sentences):**

- Clean archives teach **physics and climatology**. Faults are **injected**, as IMD specified for evaluation.
- The autoencoder cannot sit above the dew-point wall (`frac_recon_mean_Td_gt_T = 0` on val).
- Spatial AI is the decision **“do neighbors share the shock?”** Ingest uses CW-IDW because that is what wins on the **official** injector. GAT is shown on the Mumbai story it was trained for.
- Corrected values are a **one-hour posterior** for a distrusted sensor, never a rewrite of a monsoon.
- Live set is **IMD-mapped 48**. Palam is not in it. Isolates abstain.

---

## 6. Numbers (locked — put these on slides)

**Do not retune anything on 2024.** Threshold `operating_score` = **0.008487**, 2023 p99 of \(s\), n = 220 007 windows, stride 6.

### 6.1 LSTM (clean reconstruction, 2023 val)

| | |
|---|---|
| Stations trained | 151 |
| Train windows | 1 041 283 |
| Val windows | 439 863 |
| Best epoch | 36 |
| Parameters | 45 027 |
| Val MSE p50 | 0.001017 |
| Val MSE p99 (window) | 0.006181 |
| Physics: fraction of recon with Td > T | **0** |
| λ physics | 0.1 |

Window-MSE p99 is **not** the ingest threshold. Ingest uses last-hour-weighted \(s\). Window p99 vs V1 (0.00605) is the same detector; do not claim we “beat V1 MSE.”

### 6.2 V1 vs V2 on injected 2024 (same family)

V1 was LSTM-only (F1 ~0.15). A bottleneck AE **reconstructs a frozen sensor** better than real weather — that is why freeze was 6%.

| | V1 LSTM-only | **V2** (48 stations, seed 42, stride 24, 16 798 windows, CW-IDW) |
|---|---|---|
| SPIKE | 94% | **98.5%** |
| STORM as weather | ~99.9% (LSTM flags; no spatial split) | **89.7%** labeled weather |
| FREEZE | **6%** | **100%** |
| COMMUNICATION | — | **100%** |
| DRIFT | 0.8% | **2.7%** (still a miss) |
| Clean FPR | **60%** | **32.5%** |
| Ingest p95 | — | **39 ms** |
| Ingest p50 | — | **14 ms** |

Clean confusion (14 834 clean hours): 10 012 CLEAN, 3 204 called weather, 975 unconfirmed, 492 hardware, 151 physical. Most remaining FPR is **calling clean hours weather** when LSTM is twitchy and neighbors still agree — not rose false hardware.

SPIKE confusion (645 hours): 543 hardware, 92 physical, 10 unconfirmed. Almost none called weather.

GAT **on that same eval**: SPIKE **41%**. That is why ingest is CW-IDW.

### 6.3 Overlay Gaussian (2023 val)

| Channel | Scaled MAE | Gate | 90% coverage |
|---|---|---|---|
| T | 0.0175 | < 0.03 | 0.923 |
| RH | 0.0345 | < 0.05 | 0.909 |
| P | 0.0106 | < 0.03 | 0.916 |

CSDI DDIM last-hour MAE was **4.7–8.5** scaled. We did not ship it.

**55 °C story (captured):** observed 55 / 95 / 980; predicted **25.24 / 69.07 / 1013.29**; band T **24.20–26.28**. Neighbor mix T **24.40** (n=3). TIMING: hour **22 / 23**, temp share **0.50**.

### 6.4 Task GAT (2023 inject gates — not the official SPIKE recipe)

| | Value | Gate |
|---|---|---|
| Hardware disagree | 0.998 | ≥ 0.85 |
| Weather agree | 0.998 | ≥ 0.85 |
| Clean agree | 0.966 | ≥ 0.90 |
| Agree threshold | 0.875 | frozen on 2023 |

These gates **passed**. They do **not** transfer to official seed-42 SPIKE. Say that out loud if asked.

---

## 7. Plots for video and PPT

All files below live in [`assets/`](assets/) (and a copy under `v2/artifacts/plots/`).

| File | What it is | Put it on | What you say |
|---|---|---|---|
| `judge_slide_card.png` | 151 stations, window counts, p50/p99, physics | Opening numbers | “Trained on 151, live map is 48, physics wall held.” |
| `recon_judge_grid.png` | Mumbai + Safdarjung, raw vs recon | Architecture / LSTM | “The AE learns the station’s climate, not faults.” |
| `physics_td_minus_t.png` | Magnus Td − T | Innovation | “Reconstructions do not sit above dew point.” |
| `loss_curve.png` | MSE vs physics penalty by epoch | Training | “Physics is a wall, not a claim we beat V1 MSE.” |
| `val_error_hist.png` | Error histogram + operating point | Threshold | “p99 frozen on **2023**. 2024 never used.” |
| `overlay_slide_card.png` | Overlay MAE gates | Self-healing | “One forward pass, not 50-step DDIM.” |
| `overlay_mae_gates.png` | Per-channel MAE vs gates | Same | T/RH/P all inside gates. |
| `overlay_loss.png` | Overlay train curve | Appendix | Optional; training moved even if the PNG looks flat. |
| `stgnn_task_slide_card.png` | GAT agree threshold / gates | Spatial AI | “Trained on weather vs hardware, **not** recon.” |
| `stgnn_task_threshold.png` | Threshold sweep | Same | Frozen 0.875 on 2023 inject. |
| `stgnn_task_loss.png` | GAT train curve | Appendix | — |

**Live demo to record (more important than extra plots):**

1. Map: Mumbai four teal. **Not Palam.**
2. Story 2: one rose marker; station chart solid 55 °C, dashed ~25 °C, band on; reason sentence; neighbor table disagree.
3. Story 3: amber cluster; solid = dashed; **no band**; health not punished for weather.
4. Root-cause: bars + Td−T + TIMING “hour 22, mostly temp.”
5. Story 4 freeze / story 5 missing temp.
6. Health after repeated hardware → not HEALTHY.

**Do not show:** CSDI samples, recon-GAT val MSE stuck at 0.0107 (except as a “what we refused” appendix), Palam as live.

Per-station recon PNGs (`recon_43003.png` etc.) still live in the **research** tree `v2/artifacts/`, not this pack, to keep the zip small. The grid is the judge visual.

---

## 8. Every file in this pack — what it does, how it connects

```text
v2-deliverable/
  README.md                 one-page scorecard + run
  requirements.txt          torch, fastapi, pandas, numpy
  docs/
    SKYGUARD_V2.md          this briefing
    CONTRACT.md             exact JSON / UI rules
    examples/               captured ingest + TIMING JSON
    assets/                 plots above
  v2/                       importable package
```

### 8.1 Docs

| File | Role |
|---|---|
| `README.md` | Start here if you only have 3 minutes |
| `docs/SKYGUARD_V2.md` | This file — full briefing |
| `docs/CONTRACT.md` | Backend/frontend must-implement |
| `docs/examples/ingest_request_clean.json` | Full 24-row request |
| `docs/examples/ingest_response_clean.json` | CLEAN, overlay off |
| `docs/examples/ingest_response_hardware.json` | 55 °C, CW-IDW, band on |
| `docs/examples/ingest_response_weather.json` | +8 °C shared, overlay off |
| `docs/examples/timing_response.json` | Poll result for that 55 °C hour |

### 8.2 Runtime (call graph)

```text
demo_engine.py / main.py
        │
        ▼
   engine.py  process_aws_data
        │
        ├── physical_rules.py     T1
        ├── lstm_inference.py     T2  ← lstm_autoencoder.pt, scalers.json, val_error_percentiles.json
        ├── buddy_check.py        T3 CW-IDW  ← buddy_edges.csv
        ├── stgnn_inference.py    T3 GAT (demo only) ← stgnn.pt
        ├── overlay_inference.py  last-hour Gaussian ← overlay.pt
        ├── timing.py             async IG
        ├── root_cause.py         reason, fault_type, health
        └── catalog.py            stations.csv
```

| File | What it does |
|---|---|
| `v2/__init__.py` | Import **torch before numpy** (Windows `c10.dll`) |
| `v2/config.py` | Paths, WMO-style bounds, freeze 12 h / 6 h×2, CW-IDW τ=0.35, `STGNN_ON_INGEST=False` |
| `v2/engine.py` | Orchestrator; `timing` always null on return; queues TIMING if `timing_async` |
| `v2/physical_rules.py` | Missing, range, step, freeze, Magnus Td |
| `v2/lstm_inference.py` | AE + score \(s\) + last-hour contributions |
| `v2/buddy_check.py` | Correlation-weighted IDW, agree bands |
| `v2/stgnn_inference.py` | SpatialAgreeGAT; ignored unless `use_stgnn=True` |
| `v2/overlay_inference.py` | Loads overlay **only if** `gates_passed` |
| `v2/timing.py` | Daemon IG; poll cache |
| `v2/root_cause.py` | Sentence, fault heuristic, 7-day health |
| `v2/catalog.py` | 151 ids + 100 km graph |
| `v2/main.py` | FastAPI 8001: `/ingest`, `/healthz`, `/buddy-map`, `/timing` |
| `v2/demo_engine.py` | Stories 1–7; GAT on; fixture `demo_windows.json` |

`get_engine()` (API/demo singleton): TIMING on, GAT **off** unless `use_stgnn=True`.  
`DetectionEngine()` (eval): TIMING off, GAT off. Seed-42 must stay that way.

### 8.3 Weights

| File | What |
|---|---|
| `lstm_autoencoder.pt` | PIML AE (~45k params). Always on. |
| `scalers.json` | Per-station min/max for T, RH, P (151 keys). |
| `val_error_percentiles.json` | `operating_score` 0.008487 is the ingest threshold. |
| `model_metadata.json` | Train/val years, λ, architecture. |
| `overlay.pt` + `overlay_metadata.json` | Gaussian; ingest uses it because `gates_passed: true`. |
| `stgnn.pt` + `stgnn_metadata.json` | Task GAT; demo only. `gates_passed: true` for **its** injector, not official SPIKE. |

### 8.4 Data

| File | What |
|---|---|
| `stations.csv` | 151 catalog (lat/lon/name). |
| `stations_judge48.csv` | Live 48 + IMD join distance. Palam absent. `42182` buddy_count_in_judge48 = **0**. |
| `buddy_edges.csv` | 100 km edges among 151. |
| `demo_windows.json` | 24 h × 5 stations, aligned end 2024-12-31T23:00:00. |

---

## 9. What is built vs what more to build

### Done (ML)

- Three-tier engine with frozen 2023 threshold
- CW-IDW ingest + seed-42 48-station report
- Gaussian overlay on hardware/physical
- TIMING off-path + poll API
- Demo stories including 55 °C vs shared +8 °C
- This pack (runtime, weights, catalogs, fixture, contract)

### Not done (product — backend / frontend)

This is the remaining SIH demo, not more Kaggle:

1. Persist **raw** in SQLite; never update that row.
2. Product `/ingest` on the existing API that **embeds** `process_aws_data` (do not make the UI talk to 8001 in production).
3. Map of **48**, default Mumbai + Safdarjung, **not Palam**.
4. Station chart: solid raw, dashed overlay, band only if `imputed_interval` non-null.
5. Alerts: amber vs rose in the same list.
6. Root-cause page: reason, physics, bars, neighbors, TIMING line.
7. Health gauge; weather excluded.
8. Playback of the six stories through **their** `/ingest`, Mumbai four ingested together.
9. Optional IMD chip on amber (JWT is backend; ML does not call IMD).

### Not done (ML, optional — do not block the demo)

- Drift detector that actually recalls the official DRIFT injector (~2.7% today) — **v2 now has a residual CUSUM** (`v2.drift`); unit tests cover the +0.1/h injector over 24 h. Re-run the 2024 seed-42 table before quoting a new recall.
- Retrain GAT on the **official** SPIKE recipe if you want GAT on ingest
- Full stride-1 2024 eval (current report is stride 24 — still 16k windows)
- Climatology p99.9 card (`climatology.temp_p999_train` is **null** in the JSON)
- Synthetic Td > T demo story (engine has THERMO; demo story 5 is **missing temp** instead)
- SHAP (we chose operational XAI + TIMING)

---

## 10. Flaws and downsides (say these before you are asked)

**Accuracy**

- **Drift is a residual CUSUM, not the AE.** Last-hour \(s\) still barely moves on a +0.1/h bias. `v2.drift.detect_drift` watches `observed − mix` instead. Do not quote a 2024 recall until `simulate_corruption_eval.py` is re-run. Isolates still cannot see drift.
- **Clean FPR is 32.5%, not 5%.** Better than V1’s 60%, still a lot of CLEAN hours called `GENUINE_WEATHER_EVENT`. The LSTM is twitchy; neighbors often still agree, so we amber instead of rose. That is the honest residual.
- **Eval is stride 24**, last-hour labels vs a 24 h window. It is the official injector on the 48, not a full hourly census.
- **STORM recall 89.7%** means ~10% of injected storms are hardware/unconfirmed. Neighborhood ingest gaps and agree bands both contribute.

**GAT**

- Task GAT **crushes its own +8 °C injector** and **fails official SPIKE** (41%). If a judge asks “why isn’t GAT on ingest?”, the answer is that number, not “we ran out of time.”

**Rules**

- Freeze is **12 h** one channel (or 6 h two channels). A 6 h ε=0.01 freeze tagged calm integer nights. The PS example of “frozen values” is still caught; short freezes are not.
- STEP 10 °C makes 55 °C a **soft** T1 (neighbors still decide). That is intentional for the official example.

**Overlay / XAI**

- Overlay is **last hour only**, not a 24 h repaired series.
- `climatology` keys are placeholders (null).
- TIMING is IG of the LSTM score from a **zero-in-scaled-space** baseline, not a learned climatology path. It is useful for “when,” not a publication-grade attribution paper.
- Sequential demo hours share one `HealthTracker`; a weather hour after a hardware hour will show a **dirty** health index. Product health must follow **labels over calendar time**, excluding weather.

**Network honesty**

- Live 48 is not a complete graph. **Safdarjung is an isolate** among the 48. Isolates cannot get weather vs hardware.
- Palam has a **train scaler** (it was in the 151) but is **not live**. The engine will QC it if you POST it. The **UI must not default to it**.

**What we threw away, and why that is a feature**

- Unsupervised recon GAT: wrong loss.
- CSDI DDIM: unusable last-hour MAE.
- ESP32: software category.
- Fitting threshold on 2024: would be cheating on the stated eval.

**What Version 1 still is**

- `ml/` in the research repo is the old demo. Do not call it from the new dashboard.

---

## 11. How the pieces connect (one paragraph)

An hour arrives. Backend stores T/P/H as-is. ML looks at 24 hours: physical impossibility first (missing, freeze, Td > T), then “does this station’s LSTM think the last hours are off-climate?”, then “do correlated nearby stations agree?” Agreement is weather (amber, keep the number, no overlay). Disagreement is hardware (rose, dashed repair, band, health). Not enough neighbors is slate. TIMING then answers which hour in the window carried the reconstruction error, without slowing ingest. The dashboard’s only jobs are to paint those labels, never overwrite raw, ingest the Mumbai cluster as a cluster, and not pretend Palam is an IMD live station.

---

## 12. If you only remember five numbers

1. Freeze **6% → 100%**
2. Clean FPR **60% → 32.5%**
3. Official SPIKE **98.5%** (GAT on ingest: **41%** — do not do that)
4. Overlay on 55 °C → **~25 °C** with a ~2 °C band
5. Ingest **p95 39 ms** on CPU · live **48** stations · Palam **out**
