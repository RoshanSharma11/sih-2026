# SIH idea submission — PS 26073

Paste the blocks below into the portal. Counts were checked against the form limits (title 100, description 50,000, abstract 10,000).

Leave **YouTube** empty until a public demo link exists. The jury must be able to open it without a login.

**Technology bucket:** Disaster Management.

Problem statement **26073**, Ministry of Earth Sciences / India Meteorological Department, category **Software**. SkyGuard is a quality-control service for Automatic Weather Stations. It is not a weather forecast and not an on-device hardware build.

Fill team name, college, and member details on the downloaded template cover. Those are not in this repository.

---

## Idea title

```
SkyGuard AI: Real-Time Quality Control for Indian Weather Stations
```

---

## Technology bucket

```
Disaster Management
```

---

## YouTube link

Leave blank.

---

## Abstract / Summary

```
Automatic Weather Stations across India report temperature, pressure, and humidity every hour. Forecasts, aviation, agriculture, and disaster response all depend on those three numbers. A station that reports 55 °C may be a broken thermometer or the edge of a heatwave. A value that does not move for half a day may be calm weather or a frozen sensor. A missing packet is a gap, not a number. Minimum and maximum gates miss the cases that matter: a slow calibration drift stays inside the legal band, a frozen but plausible reading looks stable, and a real storm looks like a multi-channel fault when only one station is examined.

SkyGuard AI is a software quality-control service for this network. Each hour, for each station, it uses only temperature, pressure, and humidity and answers five questions. Can this hour be trusted? If not, is the cause genuine weather or a faulty instrument? Which channel is responsible? How confident is the call? What would the hour have been if the sensor were sound? The original reading stays on the record. A corrected value is stored beside it only when the instrument is the problem. A seven-day health score records how often that sensor has been wrong. Shared weather does not reduce the score, so a storm does not send a technician.

The check runs in three stages. Physical rules, in the spirit of WMO practice, catch impossible ranges, frozen channels, missing packets, and thermodynamic inconsistencies such as a dew point warmer than the air. A physics-informed LSTM autoencoder, trained on each station’s own clean hourly history, then asks whether the last day resembles that station’s climate. Recent hours weigh more than the rest of the day. The decision threshold was frozen on 2023 validation and was not fitted on the 2024 evaluation year. When an hour looks unusual, a spatial check compares it with at least two neighboring stations, weighted by distance and by how those neighbors usually move together. Neighbors that share the shock mark the hour as genuine weather, and the raw value stands. A station that is alone is a hardware anomaly, and a one-hour reconstruction with a 90 percent band is the value offered downstream. Fewer than two usable neighbors, or less than a full day of history, produces an unconfirmed call. SkyGuard would rather abstain than invent a neighbor.

On the problem statement’s own example — 55 °C with extreme humidity and pressure at one station, neighbors normal — SkyGuard labels the hour a hardware anomaly, keeps 55 °C on the record, and reconstructs a temperature near 25 °C. The same shock shared across the neighborhood is genuine weather: no invented correction, and no penalty to sensor health.

Evaluation follows the problem statement: faults are injected into historical hours, and thresholds are not tuned on the evaluation year. On 48 stations that map to live IMD sites, spikes are recovered as hardware or physical faults at 98.5 percent, frozen sensors and missing packets at 100 percent, and shared storms as weather at 89.7 percent. A lone spike is almost never called weather. Median scoring time on CPU is about 14 milliseconds, and the 95th percentile is about 39 milliseconds. The live service polls IMD each hour, scores this 48-station catalog in process, and gives an operator a network map, the raw series beside any correction, an alert inbox with acknowledgement, and a view of how completely each station is reporting.
```

---

## Idea description

```
Problem statement 26073 asks for a real-time AI system that keeps India’s Automatic Weather Station network trustworthy. The network reports three channels only: temperature in degrees Celsius, atmospheric pressure in hectopascals, and relative humidity in percent. Those streams feed forecasts, aviation, agriculture, and disaster decisions. They also decide whether someone is sent to repair a station. The same three numbers must support both decisions, and they often look alike when they should not.

A single station at 55 °C, with humidity and pressure far from its neighbors, is the official example. That pattern is a broken probe. The same heat shared across a neighborhood is weather. A sensor that repeats one plausible value for many hours is frozen, not “stable.” A null packet is a communication failure. A slow bias over a day or two can sit inside every min/max gate and still poison a forecast. The grand challenge in the statement is a self-aware, self-healing observation network: the system should know when it believes a reading, should say why, and should offer a usable value without destroying the observation that actually arrived.

SkyGuard is that service. It does not forecast the next hour. It decides whether the hour that just arrived can be trusted.

What the operator receives

For every station and every hour, SkyGuard returns a verdict, a confidence, a plain-language reason, the channel that drove the call, and a seven-day sensor-health score. Five verdicts cover the operational cases.

A clean hour is one that matches the station’s own recent climate. It is trusted, and the value passed on is the value received.

A physical fault is a hard failure: a missing packet, a frozen channel, or a thermodynamic impossibility. Confidence is full, and the station’s health can fall.

A hardware anomaly is an unusual hour that the station’s neighbors do not share. The instrument is the problem. Health can fall. A reconstructed last hour, with a 90 percent band, sits beside the raw reading so a downstream user can see both the report and the estimate.

A genuine weather event is an unusual hour that the neighbors do share. The raw reading stands. No substitute climate is invented for a real storm. Health does not move, because the sensor told the truth about bad weather.

An unconfirmed anomaly is an unusual hour that cannot be checked spatially, because fewer than two neighbors are usable or the station does not yet have a full day of hours. The hour is stored. SkyGuard does not pretend to know whether it was weather.

Health is a seven-day rate of sensor faults. Weather hours are excluded from the numerator. A station that has been unhealthy for days is the one that needs a technician. A station that failed once this hour, and is otherwise healthy, is watched. A wide weather event never appears on the maintenance list.

How the decision is made

Stage one is physical quality control. Missing values are communication errors. A channel that does not change for twelve hours, or two channels that do not change for six, is a freeze. A dew point warmer than the air temperature, from the Magnus relation, is thermodynamically inconsistent. Extreme steps and ranges are noted and then still shown to the neighbors, because the 55 °C story is exactly an extreme step that might, in another case, be shared weather. Hard physical failures stop here with a physical-fault label.

Stage two learns what “normal” means at that station. A physics-informed LSTM autoencoder reads a 24-hour window of the three channels and reconstructs it. The training loss penalises reconstructions that cross the dew-point wall, so the network cannot “repair” an hour by breaking the physics of moist air. The score emphasises the last three hours inside the day, which is what an operator needs for the hour that just arrived. The operating threshold is the 99th percentile of this score on 2023 validation, across about 220,000 windows. It was locked before any look at 2024. The model was trained on 151 Indian stations, 2020–2022, a little over one million windows, and validated on 2023. Clean archives teach climate and the joint behaviour of temperature, humidity, and pressure. They do not contain a labelled catalogue of broken sensors, so faults used in evaluation are injected, which is what the problem statement asks for.

Stage three is the spatial split the threshold cannot make. Neighbors come from a buddy graph of stations that actually sit near one another. Delhi is not asked to validate Mumbai. Each neighbor is weighted by inverse distance squared and by how strongly its recent series moves with the station under test. Agreement is tight and explicit: about 3 °C, 8 percent relative humidity, and 2 hPa, and at least two neighbors must be present. Agreement on a real shock is weather. Disagreement is hardware. Too few neighbors is unconfirmed.

The reconstruction offered to the operator is a single forward estimate of the distrusted hour, with a 90 percent band. On the 55 °C example the stored reading remains 55 °C, 95 percent, 980 hPa, and the estimate is about 25.2 °C, with a temperature band of roughly 24.2 to 26.3 °C. Clean hours and weather hours copy the observation. There is nothing to “heal” when the sensor is believed.

Self-healing, in this product, means the raw row is immutable and a corrected last hour is attached only when the sensor is distrusted. Forecast and archive consumers can keep the original for audit and use the overlay when the instrument is the fault.

What we measured

The reported evaluation is the injected 2024 set on the 48 stations that have a live IMD site within range, stride 24 hours, 16,798 windows, threshold untouched. Spikes are called hardware or physical faults 98.5 percent of the time, and almost none of them are called weather. Frozen sensors and missing packets are caught completely by the physical rules. Shared storms are labeled weather 89.7 percent of the time. A previous LSTM-only version caught freezes only about 6 percent of the time and flagged clean hours about 60 percent of the time, because a reconstruction model is good at copying a stuck sensor and is twitchy on ordinary days. Putting freeze in the rules, weighting the latest hours, and asking the neighbors brought the clean-hour false-positive rate to 32.5 percent. Most of what remains is a clean hour labeled weather, which does not dispatch maintenance. False hardware on quiet hours is the smaller share.

Slow drift is the hard family. A bias of a tenth of a degree per hour still looks like climate to an autoencoder, so last-hour reconstruction error barely moves. A cumulative residual of the station against its neighbor blend is what watches for that bias. We treat drift as a separate check for that reason, and we do not quote spike-level recall for it.

Scoring stays on CPU. Median time is about 14 milliseconds per hour and the 95th percentile is about 39 milliseconds, which is the right energy figure for a software entry: work done per observation, not milliwatts on a microcontroller.

What is running

The live catalog is those 48 IMD-mapped stations. Models and per-station scalers load when the service starts. Each hour the service can poll IMD, store the hour, and score it once 24 hours are in hand. Until that day is complete the hour is stored and no verdict is forced. An unknown station with no scaler is refused. Stations with no neighbors inside the catalog, such as an isolate, still receive physical checks and otherwise stay unconfirmed.

The operator console is a map of the current hour, a station page with the raw series and any dashed correction, an alert inbox (acknowledge and resolve, without deleting the reading), and a reliability page for how much of the week actually arrived. Silence across many stations is treated as a feed problem, not as forty broken thermometers. A technician opening a rose alert sees the channel, the neighbor table, and the sentence that named the fault.

Why this design

A min/max gate cannot see drift, freeze, or the difference between one hot station and a hot city. A forecast model answers a different question. A reconstruction network alone cannot tell a storm from a broken probe, because both are unusual, and it reconstructs a frozen sensor too faithfully to be a freeze detector. A graph network trained only to rebuild a station from its neighbors has little to learn on clean data, where neighbors already agree. The spatial question that matches the problem statement is narrower: did the neighbors share this shock? That question is answered with the correlation-weighted distance blend on the live path, because that is what separates the official injected spike from a shared storm.

Explainability is the sentence, the physics card (dew point against temperature), the channel contributions, and the neighbor comparison. An operator can see why the hour was rose or amber without a separate interpretation toolkit on the ingest path.

Scale is the 151-station training set and the 48-station live map, with the same code path for each hour. Deployment is one in-process scoring call behind a small service and a console that only reads that service. No special accelerator is required.

Who it helps

IMD and the agencies that consume AWS hours get a trusted flag, a reason, and an optional corrected hour before a bad value enters a forecast or a warning. Field maintenance gets a health score that ignores the weather, so crews are sent to instruments that are lying, not to cities that are hot. Disaster managers keep extreme but corroborated weather in the record, which is the observation they most need. The archive stays auditable because the raw hour is never overwritten.

SkyGuard is built to the constraint the statement imposes: three channels, real time, injected-fault evaluation, a distinction between weather and hardware, a confidence and a reason, a health signal, and a correction that does not erase the observation.
```

---

## Idea template (paste into the downloaded deck, then export PDF)

Use the official template from **Download Template**. Keep its slide order and logos. Replace the placeholder text with the blocks below. Export to PDF, under 10 MB.

### Cover

- Title: SkyGuard AI: Real-Time Quality Control for Indian Weather Stations
- PS ID: 26073
- Organisation: Ministry of Earth Sciences / India Meteorological Department
- Category: Software
- Theme / technology bucket: Disaster Management
- Team name, college, leader: fill from your registration

### The problem, as we understand it

India’s Automatic Weather Stations report temperature, pressure, and humidity every hour into forecasts, aviation, agriculture, and disaster response. The same stream decides whether a technician is sent. A reading of 55 °C with wild humidity and pressure, while neighbors are normal, is a hardware fault, not a heatwave. A frozen plausible value looks like calm weather. A slow drift stays inside min/max limits. A real storm, seen at one station only, looks like a multi-channel failure. The statement allows only these three channels, asks for real-time detection, a weather-versus-fault split, confidence, an explanation, sensor health, and an optional corrected hour, and it evaluates on injected anomalies. The aim is a network that knows when it trusts itself.

### Proposed solution

SkyGuard scores every station-hour and returns one of five verdicts: trusted, physical fault, hardware anomaly, genuine weather, or unconfirmed. The raw hour is kept. A corrected hour and a 90 percent band are attached only for physical and hardware faults. Weather keeps the observation and does not lower a seven-day health score. Fewer than two neighbors, or fewer than 24 hours of history, yields no spatial guess.

The official example is the acceptance test. One station at 55 °C, 95 percent, 980 hPa, neighbors normal: hardware, raw value kept, reconstruction near 25 °C. The same shock on the station and its neighbors: weather, no overlay, health unchanged.

### Technical approach

1. Physical rules: missing packet, freeze (12 h on one channel or 6 h on two), range and step, Magnus dew point above air temperature.
2. Physics-informed LSTM autoencoder on a 24×3 window (hidden 64, latent 32). Score = 0.7 × error on the last 3 hours + 0.3 × error on the day. Threshold = 2023 99th percentile (0.008487), not fitted on 2024. Trained on 151 stations, 2020–2022.
3. Spatial check against at least two buddies, weighted by inverse distance squared and series correlation. Agree within 3 °C, 8 percent humidity, 2 hPa: weather. Disagree: hardware. Otherwise unconfirmed.
4. One-pass Gaussian estimate of a distrusted hour. CPU time about 14 ms median, 39 ms at the 95th percentile.

Stack: Python, PyTorch, FastAPI, SQLite, Streamlit. Live hours can be polled from IMD for the 48-station catalog. The console maps the hour, shows raw against correction, and tracks alerts and reporting completeness.

### Evidence

Injected 2024, 48 live-mapped stations, 16,798 windows, frozen threshold:

- Spike recovered as hardware or physical fault: 98.5 percent
- Freeze: 100 percent
- Missing packet: 100 percent
- Shared storm labeled weather: 89.7 percent
- Clean-hour false-positive rate: 32.5 percent, down from about 60 percent for an LSTM-only baseline; most of the remainder is a weather label, which does not send a crew

On the 55 °C story the overlay is about 25.2 °C (band about 24.2–26.3 °C). Slow drift is handled as a cumulative residual against neighbors, because reconstruction error barely sees a tenth-of-a-degree hourly bias. We do not claim spike-level recall for drift.

### Feasibility

The scoring path, the 48-station catalog, the operator console, and the IMD hourly poll are implemented. An unknown station is refused. An isolate is not given a fake neighbor. The service runs on CPU. The idea round can be demonstrated with the live map and with two scripted hours: a single-station 55 °C fault, and the same heat shared across a Mumbai neighborhood.

### Impact

Bad hours are stopped before they enter a forecast or a warning, with the original retained for audit. Maintenance is aimed at instruments that disagree with their neighbors, not at cities that are genuinely hot. Disaster managers keep corroborated extremes. The network becomes self-aware hour by hour: trust the reading, name the fault and the channel, or say that the evidence is not enough to decide.

### References

- Problem statement 26073, Smart India Hackathon, Ministry of Earth Sciences / India Meteorological Department.
- WMO guidance on quality control of surface observations (range, step, internal consistency), used as the spirit of the physical rules.
- Magnus formula for saturation vapour pressure, used as the dew-point constraint inside the autoencoder loss.
