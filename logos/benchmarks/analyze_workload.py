#!/usr/bin/env python3
"""Workload-trace analysis for the logos benchmark dataset.

Answers two questions about the last 30 days of production logs that were
exported into ``logos/benchmarks/data/``:

1. Are request bursts of one model temporally **independent** of bursts of
   other models, or are they coupled?
2. Does each API key (= agent) exhibit a **distinctive temporal arrival
   pattern**, i.e. is the timing distribution correlated with the API-key
   identity?

Run via uv (no project-level deps required)::

    cd logos/benchmarks
    uv run --with pandas --with numpy --with scipy \
           --with matplotlib --with seaborn \
        ./analyze_workload.py

Outputs land in ``logos/benchmarks/data/analysis_output/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # must precede pyplot import; the imports below are deliberately after it
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from scipy import stats  # noqa: E402
from scipy.cluster.hierarchy import fcluster, linkage  # noqa: E402
from scipy.spatial.distance import squareform  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "analysis_output"
OUT.mkdir(parents=True, exist_ok=True)

RNG = np.random.default_rng(20260604)


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    log = pd.read_csv(
        DATA / "log_entry_30d.csv",
        parse_dates=[
            "timestamp_request",
            "timestamp_forwarding",
            "timestamp_response",
            "time_at_first_token",
        ],
    )
    models = pd.read_csv(DATA / "models.csv")
    api_keys = pd.read_csv(DATA / "api_keys.csv")
    teams = pd.read_csv(DATA / "teams.csv")
    log["model_name"] = log["model_id"].map(models.set_index("id")["name"])
    log["api_key_name"] = log["api_key_id"].map(api_keys.set_index("id")["name"])
    log = log.dropna(subset=["timestamp_request"]).sort_values("timestamp_request")
    before = len(log)
    log = log[log["result_status"] == "success"].copy()
    print(f"  filtered to result_status=success: {len(log):,} / {before:,} rows kept")
    return log, models, api_keys, teams


def model_pivot(log: pd.DataFrame, freq: str) -> pd.DataFrame:
    pivot = (
        log.dropna(subset=["model_name"])
        .set_index("timestamp_request")
        .groupby([pd.Grouper(freq=freq), "model_name"])
        .size()
        .unstack(fill_value=0)
        .sort_index()
    )
    return pivot


def model_burst_dependence(log: pd.DataFrame, freq: str = "1h") -> dict:
    pivot = model_pivot(log, freq)
    # Restrict to actively-used models (>=50 requests in the 30d window).
    totals = pivot.sum().sort_values(ascending=False)
    keep = totals[totals >= 50].index.tolist()
    if len(keep) < 2:
        keep = totals.head(8).index.tolist()
    pivot = pivot[keep]

    # Count correlations.
    corr_spearman = pivot.corr(method="spearman")
    corr_pearson = pivot.corr(method="pearson")

    # Burst definition: z-score >= 2 within the per-model time series.
    mu = pivot.mean()
    sd = pivot.std().replace(0, np.nan)
    z = (pivot - mu) / sd
    bursts = (z >= 2).fillna(False).astype(int)

    cols = bursts.columns.tolist()
    n = len(cols)
    jacc = pd.DataFrame(np.eye(n), index=cols, columns=cols, dtype=float)
    for i, a in enumerate(cols):
        for j, b in enumerate(cols):
            if i == j:
                continue
            inter = ((bursts[a] == 1) & (bursts[b] == 1)).sum()
            union = ((bursts[a] == 1) | (bursts[b] == 1)).sum()
            jacc.iat[i, j] = (inter / union) if union else np.nan

    # Permutation null for the *mean off-diagonal* Jaccard. We circularly
    # shift each column independently and recompute. Tests the null "bursts
    # of different models occur independently in time".
    n_perm = 200
    null = np.empty(n_perm)
    arr = bursts.values  # (T, n)
    T = arr.shape[0]
    for p in range(n_perm):
        shifted = np.empty_like(arr)
        for k in range(n):
            shifted[:, k] = np.roll(arr[:, k], RNG.integers(1, T))
        # mean off-diag Jaccard for shifted
        j_off = []
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                a, b = shifted[:, i], shifted[:, j]
                u = ((a == 1) | (b == 1)).sum()
                if u:
                    j_off.append(((a == 1) & (b == 1)).sum() / u)
        null[p] = float(np.mean(j_off)) if j_off else 0.0

    eye = np.eye(n, dtype=bool)
    observed_jacc = float(jacc.where(~eye).stack().mean())
    p_value = float((null >= observed_jacc).mean())

    # Cross-correlation at lags +/- 6 bins.
    lags = list(range(-6, 7))
    xcorr_rows = []
    for a in cols:
        for b in cols:
            if a >= b:
                continue
            vals = [pivot[a].corr(pivot[b].shift(k), method="pearson") for k in lags]
            best = int(np.nanargmax(np.abs(vals)))
            xcorr_rows.append(
                {
                    "a": a,
                    "b": b,
                    "lag_best": lags[best],
                    "corr_at_best": float(vals[best]),
                    "corr_at_0": float(vals[lags.index(0)]),
                }
            )
    xcorr_df = pd.DataFrame(xcorr_rows)

    return {
        "pivot": pivot,
        "corr_spearman": corr_spearman,
        "corr_pearson": corr_pearson,
        "bursts": bursts,
        "jacc": jacc,
        "observed_jacc": observed_jacc,
        "perm_null_mean": float(null.mean()),
        "perm_null_p": p_value,
        "xcorr": xcorr_df,
    }


def plot_model_dependence(res: dict) -> None:
    pivot = res["pivot"]
    corr = res["corr_spearman"]
    jacc = res["jacc"]

    plt.figure(figsize=(13, 5))
    pivot.plot(ax=plt.gca(), legend=True, alpha=0.7)
    plt.legend(fontsize=7, ncol=2)
    plt.title("Requests per model over time (hourly bins)")
    plt.ylabel("Requests / hour")
    plt.tight_layout()
    plt.savefig(OUT / "model_timeseries.png", dpi=120)
    plt.close()

    plt.figure(figsize=(10, 8))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="vlag", center=0, vmin=-1, vmax=1)
    plt.title("Spearman correlation of hourly request counts (model x model)")
    plt.tight_layout()
    plt.savefig(OUT / "model_count_correlation.png", dpi=120)
    plt.close()

    eye = np.eye(len(jacc), dtype=bool)
    vmax = float(np.nanmax(jacc.values[~eye])) if (~eye).any() else 1.0
    plt.figure(figsize=(10, 8))
    sns.heatmap(jacc, annot=True, fmt=".2f", cmap="rocket_r", vmin=0, vmax=max(vmax, 0.05))
    plt.title("Burst co-occurrence (Jaccard) — bursts = hourly z-score ≥ 2")
    plt.tight_layout()
    plt.savefig(OUT / "model_burst_jaccard.png", dpi=120)
    plt.close()


def api_key_temporal(log: pd.DataFrame, api_keys: pd.DataFrame, min_requests: int = 100) -> dict:
    log = log.dropna(subset=["api_key_id"]).copy()
    log["api_key_id"] = log["api_key_id"].astype(int)
    log["hour"] = log["timestamp_request"].dt.hour
    log["dow"] = log["timestamp_request"].dt.dayofweek

    counts = log["api_key_id"].value_counts()
    active = counts[counts >= min_requests].index
    la = log[log["api_key_id"].isin(active)].copy()

    hod = la.groupby(["api_key_id", "hour"]).size().unstack(fill_value=0).reindex(columns=range(24), fill_value=0)
    hod_norm = hod.div(hod.sum(axis=1), axis=0)

    dow = la.groupby(["api_key_id", "dow"]).size().unstack(fill_value=0).reindex(columns=range(7), fill_value=0)
    dow_norm = dow.div(dow.sum(axis=1), axis=0)

    overall_hod = log["hour"].value_counts(normalize=True).reindex(range(24), fill_value=0)
    overall_dow = log["dow"].value_counts(normalize=True).reindex(range(7), fill_value=0)

    def kl(p: np.ndarray, q: np.ndarray, eps: float = 1e-9) -> float:
        p = np.asarray(p, dtype=float) + eps
        q = np.asarray(q, dtype=float) + eps
        p /= p.sum()
        q /= q.sum()
        return float((p * np.log(p / q)).sum())

    kl_hod = hod_norm.apply(lambda r: kl(r.values, overall_hod.values), axis=1)
    kl_dow = dow_norm.apply(lambda r: kl(r.values, overall_dow.values), axis=1)

    # Global chi-square: is the joint (api_key x hour) distribution different
    # from independence (api_key indep. of hour)?  Pearson chi-square on the
    # contingency table.  Significant => api-key identity carries timing info.
    chi2_global, p_global, dof_global, _ = stats.chi2_contingency(hod.values)

    # Per-key chi-square vs the overall expected hour distribution.
    chi_rows = {}
    for k, row in hod.iterrows():
        expected = overall_hod * row.sum()
        mask = expected > 5
        if mask.sum() < 5:
            chi_rows[k] = (np.nan, np.nan)
            continue
        obs = row[mask].values.astype(float)
        exp = expected[mask].values.astype(float)
        # chisquare requires sum(obs) == sum(exp); after masking they may
        # differ slightly. Rescale exp to match the kept observed sum.
        if exp.sum() > 0:
            exp = exp * (obs.sum() / exp.sum())
        c2, p = stats.chisquare(obs, f_exp=exp)
        chi_rows[k] = (float(c2), float(p))
    chi_df = pd.DataFrame.from_dict(chi_rows, orient="index", columns=["chi2_hod", "p_hod"])

    # Inter-arrival statistics per key.
    la_sorted = la.sort_values(["api_key_id", "timestamp_request"])
    la_sorted["ia_s"] = la_sorted.groupby("api_key_id")["timestamp_request"].diff().dt.total_seconds()
    bs = (
        la_sorted.groupby("api_key_id")["ia_s"]
        .agg(["count", "mean", "std", "median"])
        .rename(columns={"mean": "ia_mean_s", "std": "ia_std_s", "median": "ia_median_s"})
    )
    bs["ia_cv"] = bs["ia_std_s"] / bs["ia_mean_s"]

    # Pairwise hourly-count correlation between keys.
    pivot_hour = (
        la.set_index("timestamp_request")
        .groupby([pd.Grouper(freq="1h"), "api_key_id"])
        .size()
        .unstack(fill_value=0)
        .sort_index()
    )
    pairs_corr = pivot_hour.corr(method="spearman")

    name_map = api_keys.set_index("id")["name"]
    summary = (
        pd.DataFrame(
            {
                "requests": counts.loc[active],
                "kl_hod": kl_hod,
                "kl_dow": kl_dow,
            }
        )
        .join(bs[["ia_mean_s", "ia_std_s", "ia_median_s", "ia_cv"]])
        .join(chi_df)
    )
    summary["api_key_name"] = summary.index.map(name_map)
    summary = summary.sort_values("kl_hod", ascending=False)

    return {
        "hod_norm": hod_norm,
        "dow_norm": dow_norm,
        "summary": summary,
        "pairs_corr": pairs_corr,
        "chi2_global": float(chi2_global),
        "p_global": float(p_global),
        "dof_global": int(dof_global),
    }


def plot_api_key(res: dict, api_keys: pd.DataFrame) -> None:
    hod_norm = res["hod_norm"].copy()
    summary = res["summary"]
    pairs_corr = res["pairs_corr"]
    name_map = api_keys.set_index("id")["name"]
    hod_norm.index = [f"{i} ({name_map.get(i, '?')})" for i in hod_norm.index]

    plt.figure(figsize=(14, max(5, len(hod_norm) * 0.35)))
    sns.heatmap(hod_norm, cmap="mako", cbar_kws={"label": "fraction"})
    plt.xlabel("Hour of day (UTC)")
    plt.ylabel("API key")
    plt.title("Per-API-key hour-of-day distribution (normalized)")
    plt.tight_layout()
    plt.savefig(OUT / "apikey_hour_of_day.png", dpi=120)
    plt.close()

    s = summary.copy()
    s["label"] = s.index.astype(str) + " " + s["api_key_name"].fillna("?")
    fig, ax = plt.subplots(1, 2, figsize=(14, max(4, len(s) * 0.32)))
    sns.barplot(data=s, y="label", x="kl_hod", ax=ax[0], color="steelblue")
    ax[0].set_title("KL divergence vs. overall hour-of-day distribution")
    sns.barplot(
        data=s.sort_values("ia_cv", ascending=False),
        y="label",
        x="ia_cv",
        ax=ax[1],
        color="indianred",
    )
    ax[1].set_title("Inter-arrival CV (burstiness)")
    plt.tight_layout()
    plt.savefig(OUT / "apikey_summary_bars.png", dpi=120)
    plt.close()

    if len(pairs_corr) > 1:
        pc = pairs_corr.fillna(0).values
        # symmetric distance for clustering
        dist = 1 - pc
        np.fill_diagonal(dist, 0.0)
        dist = (dist + dist.T) / 2
        condensed = squareform(dist, checks=False)
        Z = linkage(condensed, method="average")
        order = np.argsort(fcluster(Z, t=max(2, len(pairs_corr) // 4), criterion="maxclust"))
        pcs = pairs_corr.iloc[order, :].iloc[:, order]
        labels = [f"{i} {name_map.get(i, '?')}" for i in pcs.index]
        pcs.index = labels
        pcs.columns = labels
        plt.figure(figsize=(11, 9))
        sns.heatmap(pcs, cmap="vlag", center=0, vmin=-1, vmax=1)
        plt.title("Spearman correlation between API keys (hourly request counts)")
        plt.tight_layout()
        plt.savefig(OUT / "apikey_pairwise_corr.png", dpi=120)
        plt.close()


def main() -> None:
    log, models, api_keys, teams = load()
    print(f"Loaded {len(log):,} log entries")
    print(f"  span : {log['timestamp_request'].min()} → {log['timestamp_request'].max()}")
    print(f"  models in slice  : {log['model_id'].nunique()}")
    print(f"  api_keys in slice: {log['api_key_id'].nunique()}")
    print(f"  teams in slice   : {log['team_id'].nunique()}")

    print("\n=== Q1: model-burst dependence ===")
    res1 = model_burst_dependence(log, freq="1h")
    plot_model_dependence(res1)
    res1["corr_spearman"].to_csv(OUT / "model_count_correlation.csv")
    res1["jacc"].to_csv(OUT / "model_burst_jaccard.csv")
    res1["xcorr"].to_csv(OUT / "model_xcorr.csv", index=False)

    corr = res1["corr_spearman"]
    eye = np.eye(len(corr), dtype=bool)
    off = corr.where(~eye).stack()
    print(f"models analysed         : {list(corr.columns)}")
    print(f"mean off-diag Spearman  : {off.mean():.3f}")
    print(f"median off-diag Spearman: {off.median():.3f}")
    print(f"|rho| > 0.5 pairs       : {int((off.abs() > 0.5).sum() / 2)}")
    print(f"|rho| > 0.7 pairs       : {int((off.abs() > 0.7).sum() / 2)}")
    print(f"observed mean burst Jaccard : {res1['observed_jacc']:.3f}")
    print(f"null (shift-permuted) mean  : {res1['perm_null_mean']:.3f}")
    print(f"permutation p-value         : {res1['perm_null_p']:.3f}")

    jacc = res1["jacc"]
    # Upper triangle only (avoid duplicate (a,b)/(b,a)).
    upper = pd.DataFrame(np.triu(jacc.values, k=1), index=jacc.index, columns=jacc.columns)
    off_j = upper.stack().replace(0, np.nan).dropna().sort_values(ascending=False).head(10)
    print("\nTop burst-coincident model pairs (Jaccard):")
    print(off_j.round(3).to_string())

    xc = res1["xcorr"].sort_values("corr_at_best", key=lambda s: s.abs(), ascending=False)
    print("\nStrongest cross-correlations (any lag, hourly):")
    print(xc.head(10).to_string(index=False))

    print("\n=== Q2: API-key temporal distinctiveness ===")
    res2 = api_key_temporal(log, api_keys, min_requests=100)
    plot_api_key(res2, api_keys)
    res2["summary"].to_csv(OUT / "apikey_temporal_summary.csv")
    res2["pairs_corr"].to_csv(OUT / "apikey_pairwise_corr.csv")

    print(
        f"global chi-square (api_key × hour-of-day): "
        f"chi2={res2['chi2_global']:.1f}, dof={res2['dof_global']}, p={res2['p_global']:.3e}"
    )
    s = res2["summary"]
    print(f"# active keys (≥100 requests): {len(s)}")
    print(f"keys with chi-square p<0.001 vs overall hour-distribution: " f"{int((s['p_hod'] < 1e-3).sum())} / {len(s)}")
    print(
        f"inter-arrival CV: min={s['ia_cv'].min():.2f}, "
        f"median={s['ia_cv'].median():.2f}, max={s['ia_cv'].max():.2f}"
    )
    cols = ["api_key_name", "requests", "kl_hod", "kl_dow", "ia_cv", "p_hod"]
    print("\nTop-10 keys by KL divergence vs. global hour-of-day distribution:")
    print(s[cols].head(10).to_string())
    print("\nBottom-5 (closest to global):")
    print(s[cols].tail(5).to_string())

    out_json = {
        "n_logs": int(len(log)),
        "n_models_in_slice": int(log["model_id"].nunique()),
        "n_api_keys_in_slice": int(log["api_key_id"].nunique()),
        "q1_model_pair_mean_spearman": float(off.mean()),
        "q1_model_pair_median_spearman": float(off.median()),
        "q1_pairs_abs_rho_gt_0p5": int((off.abs() > 0.5).sum() / 2),
        "q1_pairs_abs_rho_gt_0p7": int((off.abs() > 0.7).sum() / 2),
        "q1_observed_burst_jaccard": res1["observed_jacc"],
        "q1_null_burst_jaccard": res1["perm_null_mean"],
        "q1_burst_perm_p": res1["perm_null_p"],
        "q2_chi2_global": res2["chi2_global"],
        "q2_p_global": res2["p_global"],
        "q2_dof_global": res2["dof_global"],
        "q2_n_keys": int(len(s)),
        "q2_keys_significant_vs_overall": int((s["p_hod"] < 1e-3).sum()),
    }
    (OUT / "summary.json").write_text(json.dumps(out_json, indent=2, default=str))
    print(f"\nWrote outputs to {OUT}")


if __name__ == "__main__":
    main()
