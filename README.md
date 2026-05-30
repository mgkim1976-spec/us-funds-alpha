# US Funds Alpha — Systematic Equity Signals from US Mutual-Fund Holdings

An **open replication and honest stress-test** of the idea behind Morgan Stanley's
*"Mutual Fund Footprints — Systematic Equity Signals from US Active Manager Disclosures"*
(Quantitative Equity Research, May 2026).

Everything here is built from **free public data** — SEC EDGAR (Form N-PORT / N-CEN),
Yahoo Finance, OpenFIGI, and the Ken French data library — with strict point-in-time
discipline and full factor-adjusted (FF5 + Momentum) validation.

> ⚠️ **Not investment advice.** All results are in-sample backtests over a short window
> (2022–2026, ~15 quarters), long-only with market beta ≈ 1, and point estimates only.
> Past performance does not predict future results.

---

## TL;DR — honest findings

1. **Universe construction decides everything.** The same signal that looks like pure
   market beta on a hand-picked set of 54 famous mega-cap growth funds becomes a
   significant factor-adjusted alpha on a *systematically built, style-diverse* universe
   of ~300 active US equity funds. The earlier "it doesn't replicate" conclusion was an
   artifact of a narrow universe.
2. **Clean your holdings.** A naive *mean holding weight* signal is polluted by ETFs,
   money-market funds, and niche MLPs that a handful of specialist funds hold at huge
   weight. Excluding non-equity and requiring breadth roughly **halves** the headline
   alpha (+8.4% → +4.0%) and reveals it is **regime-dependent** (works in the 2023–26
   mega-cap regime, ~zero in 2022–24 — that early "alpha" was an energy/MLP tilt).
3. **Individual signals are regime-concentrated; an ensemble is the most robust thing
   here.** A z-score ensemble of three complementary signals is the only construct that
   is statistically significant in **both** sub-periods (t ≈ 4 full-period, both halves
   t > 2), and it beats random selection from the same universe at the 99–100th percentile.
4. **Manager *selection* does not work.** Picking funds by trailing NAV alpha or by
   trailing "signal-source skill" failed out-of-sample — skill does not persist (alpha
   decay). The edge, where it exists, is at the **stock** level, not the manager level.

See [`notes/`](notes/) for the full step-by-step research record.

---

## The signals

Each aggregates fund-level holding changes into a stock-level score, point-in-time
(by SEC filing date, so the ~56-day disclosure lag is respected).

| Key | Signal | Definition (this repo) |
|---|---|---|
| `mhw` | **Mean Holding Weight** | mean position weight across funds that hold the stock |
| `lnp` | **Large New Positions** | sum of new high-conviction initiations (≥0.5%) across funds |
| `bi`  | **Best-Ideas** (Cohen–Polk–Silli) | Σ max(0, fund weight − cross-fund mean) = active overweight |
| `ens` | **Ensemble** | z-score(mhw) + z(lnp) + z(bi), averaged |

(The MS report names nine signals; only six are public, and the dollar-flow ones —
Churn-Weighted / Concentration-Weighted Flow / Reallocation Intensity — are
*reconstructions* here since their exact definitions are not disclosed.)

## Key results (cleaned 300-fund universe, FF5+Mom alpha, Newey-West)

| Strategy | top-N | Alpha | t | Sharpe | 2022-24 | 2024-26 |
|---|---|---|---|---|---|---|
| **Ensemble (rank-weighted)** | 30 | +6.5% | **3.81** | 1.65 | t2.4 | t4.1 |
| Mean Holding Weight | 30 | +4.0% | 2.11 | 2.00 | t0.2 | t2.4 |
| Large New Positions | 30 | +6.1% | 2.54 | 1.56 | t3.8 | t0.7 |
| Best-Ideas (active OW) | 30 | +4.5% | 2.12 | 1.94 | t3.4 | t1.1 |
| S&P 500 (SPY) | – | −0.1% | – | 1.41 | | |

Transaction costs are low (~16–19% one-way quarterly turnover); net-of-cost alpha at
25 bps barely moves. Weighting matters: rank-weighting gives the best alpha/robustness,
inverse-vol the best Sharpe, equal-weight the simplest (see [`notes/weighting.md`](notes/weighting.md)).

---

## Live dashboard

A self-contained daily monitor (`dashboard/index.html`) shows, for each strategy and for
both Top-10 and Top-30, the current portfolio, weights, live performance vs SPY since the
last quarterly rebalance, the disclosure-lag distribution, and rebalance-change alerts.

```bash
cd dashboard && python3 -m http.server 8769   # then open http://localhost:8769/
```

A `launchd` agent (`scripts/daily_update.sh`) refreshes it every weekday morning:
it pulls newly-filed N-PORT incrementally (`update_filings.py`) and re-prices the live
portfolios (`dashboard_data.py`). Validation stats are precomputed by `compute_card_stats.py`.

---

## Reproduce

```bash
pip install -r requirements.txt

# 1. Build the universe (N-CEN flags + N-PORT EC% confirmation)
python3 scripts/build_master_universe.py     # → data/universe_master.parquet
python3 scripts/stage2_ecpct.py              # → data/universe_confirmed.parquet
python3 scripts/expand_validate.py           # NAV/style → data/universe_300.json + §PCA

# 2. Collect holdings & prices
python3 scripts/bulk_collect_300.py          # N-PORT bulk → data/holdings_panel_300.parquet
python3 scripts/fetch_prices_300.py          # OpenFIGI + Yahoo → data/prices_full.parquet

# 3. Validate
python3 scripts/signals_family.py            # all signals, one universe
python3 scripts/revalidate_clean.py          # cleaned signals + sub-periods + placebo
python3 scripts/ensemble_test.py             # 3-signal ensemble
python3 scripts/weighting_test.py            # weighting schemes
python3 scripts/mhw_cost.py                  # transaction-cost sensitivity

# 4. Dashboard
python3 scripts/compute_card_stats.py        # → dashboard/card_stats.json
python3 scripts/dashboard_data.py            # → dashboard/data.json
```

The large data files (parquets, SEC/price caches) are git-ignored and regenerated by the
above; small reference inputs (`data/raw/*.json`, factor CSVs, `data/universe_300.json`)
are committed.

## Repo structure

```
scripts/
  falib.py             shared library (factors, panel, signals, FF alpha) — used by all
  build_master_universe.py, stage2_ecpct.py, expand_validate.py   universe construction
  bulk_collect_300.py, fetch_prices_300.py, update_filings.py      data collection
  signals_family.py, revalidate_clean.py, ensemble_test.py,
  weighting_test.py, mhw_cost.py                                   validation
  compute_card_stats.py, dashboard_data.py, daily_update.sh        dashboard pipeline
dashboard/             self-contained HTML monitor + JSON data
notes/                 step-by-step research record (Korean)
```

## Data sources (all free)

- **SEC EDGAR** — Form N-PORT (monthly portfolio holdings) & N-CEN (fund metadata / index-fund flag),
  including the DERA structured bulk datasets.
- **Yahoo Finance** — daily adjusted prices and fund NAVs.
- **OpenFIGI** — CUSIP → ticker mapping.
- **Ken French Data Library** — Fama-French 5 factors + Momentum.

## License

[MIT](LICENSE). Research / educational use. Not investment advice.
