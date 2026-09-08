# LSTM reconstruction: smoothness is the point

Clean val 2023 · 151 stations · bottleneck LSTM-AE (24×3 → last hidden → 32-d latent).

Source: Kaggle artifacts in `ml/artifacts/`.

## Verdict

The model trained well. Smooth reconstructions against spiky observed series are expected, not a failure to learn volatility. An autoencoder for anomaly detection should learn the diurnal T/H/P manifold and leave hour-to-hour spikes in the residual. If it copied every spike, hardware faults would disappear into reconstruction error near zero.

| Metric | Value |
|---|---|
| Best val window MSE | 0.00130 |
| Val p99 window MSE | 0.00605 |
| Train vs val gap at epoch 40 | ~14% |
| Worst val window (Bilaspur 42080) | 0.0198 |

## Training actually converged

Train MSE dropped from 0.0104 to 0.00114. Val monitor MSE from 0.00262 to 0.00130 at epoch 40. After epoch ~22 the curves are flat; LR cuts at 28 and 38 only nibble the last bit. No overfitting: val stays slightly above train, which is what you want on held-out 2023.

Selected epochs (scaled-space MSE). Source: `ml/artifacts/training_history.csv`.

| Epoch | Train MSE | Val monitor MSE |
|---|---|---|
| 1 | 0.01035 | 0.00262 |
| 10 | 0.00145 | 0.00162 |
| 20 | 0.00123 | 0.00136 |
| 30 | 0.00115 | 0.00133 |
| 40 | 0.00114 | 0.00130 |

## Why reconstruction is smoother than observed

The encoder compresses 72 numbers (24 hours × 3 variables) through a single 32-d latent vector taken from the last LSTM hidden state. That vector can store “what kind of day this is” — morning rise, afternoon peak, pressure tide — not a 20 °C jump at hour 9. MSE on clean data also rewards the mean diurnal shape; high-frequency wiggles are expensive to fit and get treated as noise.

### Typical window — Canning 42812

Median val-index window, not a cherry-pick. Pressure tracks the double wave. Temperature and humidity miss the sharp hour-6 / hour-9 spikes and keep the daily envelope (roughly 28–32 °C vs observed peaks to 34 °C). That is a low-pass filter, which is the bottleneck doing its job. Canning is a Sundarbans/delta station; some of those T/RH spikes can be real convection. Tier 3 buddy check is what decides weather vs hardware at ingest — not a perfectly wiggly reconstructor.

Plots: `ml/artifacts/plots/recon_example.png`.

### Worst window — Bilaspur 42080, MSE 0.01975

Observed temperature leaping ~20→34→21→40 °C inside a few hours is not volatility the model “should have learned.” A dry-bulb sensor does not do that on a healthy station. Those jumps exceed the Tier 1 10 °C/hour step rule. This window is dirty “clean” val leaking through completeness-only QC. The smooth reconstruction (peak just under 30 °C) is the climatologically plausible day; the residual is exactly the anomaly score you want.

Plots: `ml/artifacts/plots/recon_worst_val.png`.

Pressure reconstructs best because the true signal is already smooth (semi-diurnal tide). Humidity is the hardest channel (feature p99 MSE 0.0135 vs pressure 0.0042) because RH is noisy and inverse to T. That ranking matches the plots, not a broken decoder.

## Error distribution is healthy for a detector

Linear histogram is right-skewed with mass near 0.001. log10 MSE is roughly Gaussian centered at −3.0. That is a stable “normal” cloud plus a thin tail — the tail is usable for a p99 threshold. Mean window MSE 0.00131 vs p99 0.00605 is about a 4.6× gap, which is enough headroom before you even add buddy check.

Percentiles over 439,863 clean 2023 val windows. Source: `ml/artifacts/val_error_percentiles.json`.

| Score | p50 | p90 | p95 | p99 | p99.9 |
|---|---|---|---|---|---|
| Window MSE | 0.00096 | 0.00264 | 0.00359 | 0.00605 | 0.01045 |
| Last-step MSE | 0.00038 | 0.00174 | 0.00263 | 0.00573 | 0.01367 |

### Per-variable val MSE p99 (scaled)

| Variable | p99 MSE |
|---|---|
| temp | 0.00621 |
| rhum | 0.01353 |
| pres | 0.00416 |

Humidity dominates. Source: `val_error_percentiles.json` · `feature_mse`.

## Hardest stations are coastal / noisy, not a global fail

Station-mean val MSE: median 0.00120, 75th percentile 0.00156, worst Kozhikode 0.00419. Even the “worst 20” bar chart tops out under 0.0045. Best stations (Karnal, Safdarjung, Hyderabad) sit around 0.00056–0.00063 — inland, smoother series. The high-error list is mostly coasts, islands, and a few messy hill/foothill sites. Shared bottleneck plus station-wise MinMax cannot invent a separate high-frequency model per microclimate, and it should not.

Source: `ml/artifacts/val_error_by_station.csv` joined to `data/raw/stations.csv`. 2,913 val windows per station.

| Station | Name | Mean MSE | p99 MSE | Why it is hard |
|---|---|---|---|---|
| 43314 | Kozhikode | 0.00419 | 0.01216 | Kerala coast, convective RH/T |
| 43311 | Amini Divi | 0.00366 | 0.00929 | Lakshadweep island |
| 42562 | Tikamgarh | 0.00366 | 0.00915 | 80% complete, noisier record |
| 42080 | Bilaspur | 0.00336 | 0.01307 | Worst single window; implausible T jumps |
| 42111 | Dehradun | 0.00293 | 0.01016 | Foothills, sharper diurnal |
| 42812 | Canning | 0.00176 | 0.00682 | Typical-window plot; delta climate |
| 42182 | Safdarjung | 0.00062 | 0.00293 | Best-in-class inland (100% complete) |

## What not to change

Do not widen the latent or switch to a full-sequence encoder just to make reconstruction hug the observed spikes. That would copy hardware spikes too, and `/ingest` would go blind. Keep window MSE + val p99 as the score. Let Tier 1 catch physically impossible steps (the Bilaspur window). Let Tier 3 IDW split genuine coastal weather from a single broken sensor. The plots show a detector that learned normal days, not a forecaster that failed to learn storms.
