# 2024 LSTM-only eval: spikes work, the rest does not

Seed 42 labeled eval, last-hour window labels, threshold = 2023 val window-MSE p99 (0.00605). LSTM only — no Tier 1, no buddy check.

Source: `ml/reports/` and `ml/reports/plots/`.

## Verdict

Overall F1 is 0.15 and ROC-AUC is 0.46 — worse than chance as a single hardware-vs-clean detector. That is not a failed autoencoder. It is excellent at SPIKE and STORM, blind to FREEZE and DRIFT, and the 60% clean flag rate is mostly last-hour labeling: a CLEAN last hour can still sit on a 24h window that contains injected faults.

| Metric | Value |
|---|---|
| Overall F1 | 0.15 |
| Clean flag rate (FPR) | 60% |
| SPIKE recall | 94% |
| DRIFT recall | 0.8% |

## What the plots actually show

Score histogram and boxplot: SPIKE and STORM sit to the right of the p99 line. FREEZE and DRIFT sit at or below CLEAN — a frozen or slowly drifting sensor is easier for a bottleneck AE to reconstruct than real weather.

Flag-rate bars: STORM 99.9%, SPIKE 94%, COMMUNICATION 60% (same as CLEAN), FREEZE 6%, DRIFT 1%. ROC hugs below the diagonal because freeze+drift score lower than clean and get mixed into the “hardware” class.

Plots: `flag_rate_by_label.png`, `score_hist_by_label.png`, `mse_box_by_fault.png`, `roc_pr.png`.

### Flag rate by last-hour label

Fraction of windows ≥ val p99. STORM excluded from overall F1.

| Label | Flag rate | n windows |
|---|---|---|
| CLEAN | 0.6002 | 1,098,672 |
| SPIKE | 0.9379 | 49,225 |
| FREEZE | 0.0626 | 39,596 |
| DRIFT | 0.0082 | 29,675 |
| COMMUNICATION | 0.6012 | 29,440 |
| STORM | 0.9993 | 49,245 |

### Precision / recall / F1 (hardware vs clean)

Each class vs CLEAN at the same p99 threshold. Precision is crushed by 659k clean false positives shared across every row.

Source: `ml/reports/lstm_test_2024_metrics.csv`.

| Fault | Precision | Recall | F1 |
|---|---|---|---|
| SPIKE | 0.0654 | 0.9379 | 0.1223 |
| FREEZE | 0.0037 | 0.0626 | 0.0071 |
| DRIFT | 0.0004 | 0.0082 | 0.0007 |
| COMMUNICATION | 0.0261 | 0.6012 | 0.0501 |

## Raising the threshold does not save it

Sweeping 2023 val percentiles on 2024 only trades recall for a slightly lower FPR. Precision stays stuck near 0.09. Even p99.9 still flags half of last-hour-CLEAN windows.

Plot: `threshold_sweep.png`.

| Val percentile | Precision | Recall | F1 | FPR | Threshold |
|---|---|---|---|---|---|
| p95 | 0.0996 | 0.5241 | 0.1674 | 0.638 | 0.00359 |
| p97.5 | 0.0948 | 0.4845 | 0.1586 | 0.623 | 0.00459 |
| p99 | 0.0917 | 0.4501 | 0.1524 | 0.600 | 0.00605 |
| p99.5 | 0.0907 | 0.4272 | 0.1496 | 0.577 | 0.00727 |
| p99.9 | 0.0912 | 0.3763 | 0.1468 | 0.505 | 0.01045 |

## Headline numbers

1,246,608 scored windows (clean + hardware). Storms 49,245 extra.

Source: `ml/reports/lstm_test_2024_metrics.json`.

| Slice | n pos | Recall | Precision | F1 | ROC-AUC |
|---|---|---|---|---|---|
| Overall hardware vs clean | 147,936 | 0.450 | 0.092 | 0.152 | 0.462 |
| SPIKE vs clean | 49,225 | 0.938 | 0.065 | 0.122 | 0.712 |
| FREEZE vs clean | 39,596 | 0.063 | 0.004 | 0.007 | 0.290 |
| DRIFT vs clean | 29,675 | 0.008 | 0.000 | 0.001 | 0.236 |
| COMMUNICATION vs clean | 29,440 | 0.601 | 0.026 | 0.050 | 0.502 |
| STORM (flag rate, not in F1) | 49,245 | 0.999 | — | — | — |

## Why this is not “the model didn’t train”

`recon_examples_temp.png` and `recon_worst_hardware.png` still look right: CLEAN mse≈0, a hard SPIKE is ignored by the reconstructor and flagged. Those panels pick the lowest-MSE clean window and the highest-MSE fault windows — they show the AE can reconstruct a normal day and reject a huge spike. They do not represent typical FREEZE/DRIFT.

Three structural reasons the aggregate looks bad:

1. Last-hour labels vs window MSE — faults in hours 0–22 poison CLEAN-labeled windows.
2. Freeze/drift are smooth, which this bottleneck is designed to copy.
3. 1–2h COMMUNICATION is interpolated before scoring, so many “comm” windows look like clean.

Tier 1 is supposed to catch freeze/range/step; this eval is LSTM-only on purpose.

## What not to change

Do not retune the p99 threshold on 2024 to chase F1. The useful LSTM jobs are: flag SPIKE-like unusual windows, flag STORM-like multivariate shocks for buddy check, and stay quiet on a frozen or slowly biased sensor so Tier 1 / heuristics can own those.
