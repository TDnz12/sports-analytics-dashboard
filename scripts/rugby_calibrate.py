"""Calibration des seuils du radar rugby (plan, 4.5) sur les caches club (Top 14, Pro D2). Aucun
accès réseau, aucune écriture dans data_cache/ : lit les parquet construits par rugby_build.py et
écrit un rapport Markdown (par défaut rugby_notes/calibration_v1.md, à côté du dépôt).

Méthode (validée avant écriture) :
1. Stabilité des stats par 80 minutes : pour un volume m, les matchs de chaque joueur-saison sont
   répartis au hasard en deux moitiés d'au moins m minutes ; corrélation A/B entre joueurs, à
   l'intérieur d'un poste (valeurs centrées par compétition, saison et poste), moyenne sur
   N_DRAWS tirages. Ajustement r(m) = m / (m + M). r(m) est la fiabilité d'un échantillon de
   m minutes : pour une saison de T minutes, fiabilité T / (T + M), donc r = 0,6 pour T = 1,5 x M.
2. Population de référence : grille de seuils (matchs, minutes), joueurs gardés et part des
   minutes couvertes par compétition, saison et poste.
3. Padding P des pourcentages : même split-half en tentatives, r(n) = n / (n + P), contrôlé par
   un modèle bêta-binomial (méthode des moments). Un seul P par stat ; P par poste montré à part.
4. Seuils NC : part des joueurs de référence classés NC selon le seuil, buteurs qualifiés par
   équipe pour le % au pied.
5. Fiabilité de chaque axe par 80 dans chaque poste au seuil retenu, et contrôle du radar par
   poste de schema.py (règle : au moins 0,4 pour le poste).
La synthèse en tête du rapport compare les valeurs calculées aux constantes de schema.py.

Usage :
    PYTHONPATH=. python scripts/rugby_calibrate.py
    PYTHONPATH=. python scripts/rugby_calibrate.py --draws 5 --out /tmp/essai.md
"""
from __future__ import annotations

import argparse
import math
import warnings
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_sources.rugby import schema  # noqa: E402
from data_sources.rugby.positions import (  # noqa: E402
    CENTRE, FLANKER, FLY_HALF, FULLBACK, HOOKER, LOCK, NUMBER_8, POSITION_GROUPS, PROP,
    SCRUM_HALF, UNDETERMINED, WING,
)

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "rugby_notes" / "calibration_v1.md"
COMPS = ("top14", "prod2")
SCOPES = ("top14", "prod2", "club")  # "club" = Top 14 et Pro D2 ensemble
SEED = 20261012
N_DRAWS = 20
MIN_PAIRS = 30            # joueurs minimum pour retenir une corrélation dans l'ajustement
TARGET_R = 0.6            # fiabilité visée sur la saison du joueur
SEASON_FACTOR = TARGET_R / (1 - TARGET_R)   # T = 1,5 x M pour r = 0,6
MIN_PLAYERS_CELL = 12     # joueurs de référence minimum par poste et par saison
MIN_COVERAGE = 0.70       # part minimum des minutes jouées couvertes par la référence

FORWARDS = [PROP, HOOKER, LOCK, FLANKER, NUMBER_8]
BACKS = [SCRUM_HALF, FLY_HALF, CENTRE, WING, FULLBACK]

# Axes par 80 minutes du radar (plan, 4.6) : colonne -> (libellé, postes concernés, socle ?).
PER80_AXES = {
    "tackles": ("Plaquages", POSITION_GROUPS, True),
    "metres": ("Mètres", POSITION_GROUPS, True),
    "penalties_conceded": ("Pénalités concédées", POSITION_GROUPS, True),
    "turnovers_conceded": ("Ballons perdus", POSITION_GROUPS, True),
    "carries": ("Courses", FORWARDS, False),
    "turnovers_won": ("Grattages", FORWARDS, False),
    "clean_breaks": ("Franchissements", BACKS, False),
    "defenders_beaten": ("Défenseurs battus", BACKS + [FLANKER, NUMBER_8], False),
    "offloads": ("Offloads", [PROP, NUMBER_8, CENTRE], False),
    "passes": ("Passes", [SCRUM_HALF, FLY_HALF, CENTRE], False),
    "kick_metres": ("Mètres au pied", [SCRUM_HALF, FLY_HALF, FULLBACK], False),
    "tries": ("Essais", [HOOKER, WING, FULLBACK], False),
    "lineouts_won_jumper": ("Touches gagnées", [LOCK, FLANKER], False),
    "lineout_steals": ("Touches volées", [LOCK], False),
}
# Section 5 : tous les axes par 80 disponibles en club, mesurés dans chaque poste (règle des 0,4).
ALL_PER80 = {
    "tackles": "Plaquages", "metres": "Mètres", "carries": "Courses", "turnovers_won": "Grattages",
    "defenders_beaten": "Défenseurs battus", "passes": "Passes", "offloads": "Offloads",
    "kick_metres": "Mètres au pied", "kicks_from_hand": "Coups de pied",
    "lineouts_won_jumper": "Touches gagnées", "lineout_steals": "Touches volées",
    "carries_gain_line": "Courses au-delà de la ligne d'avantage",
    "clean_breaks": "Franchissements", "tries": "Essais", "points": "Points",
    "missed_tackles": "Plaquages manqués", "penalties_conceded": "Pénalités concédées",
    "turnovers_conceded": "Ballons perdus",
}
SOCLE = [c for c, (_, _, socle) in PER80_AXES.items() if socle]
MINUTE_HALVES = (60, 120, 180, 240, 320, 400, 480)

# Pourcentages : clé -> (libellé, réussis, tentatives, centrage par poste ?, volumes par moitié,
# seuils NC candidats, postes affichés pour le NC).
PCT_STATS = {
    "tackle_pct": ("% plaquages", "tackles", "tackle_attempts", True,
                   (10, 20, 30, 40, 60, 80), (10, 15, 20, 30, 40), POSITION_GROUPS),
    "gain_line_pct": ("% gain de ligne", "carries_gain_line", "carries", True,
                      (10, 20, 30, 40, 60), (10, 15, 20, 30, 40), POSITION_GROUPS),
    "goal_kick_pct": ("% au pied", "goals_made", "goal_attempts", False,
                      (5, 10, 15, 20, 30, 40), (10, 15, 20, 30), None),
}
NC_WEIGHT = 0.2          # poids du joueur dans son % ajusté au seuil NC (voir section 4)
BETA_MIN_ATTEMPTS = {"tackle_pct": 20, "gain_line_pct": 15, "goal_kick_pct": 10}

GAMES_GRID = (3, 4, 5, 6, 7, 8)
T_STEP = 20
T_SEARCH = tuple(range(120, 1201, T_STEP))   # seuils de minutes testés
DISPLAY_T = (240, 320, 400, 480, 560, 640, 720, 800)
BEFORE = {  # valeurs du plan (4.5) avant la calibration, pour comparaison
    "games": 5, "minutes": 240, "P_tackle_pct": 40, "P_gain_line_pct": 30, "P_goal_kick_pct": 40,
    "NC_tackle_pct": 20, "NC_gain_line_pct": 15, "NC_goal_kick_pct": 20,
}


# --- Chargement ---------------------------------------------------------------
def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(matchs joués, une ligne par joueur et par match ; joueurs-saisons, période "all")."""
    rows, players = [], []
    for comp in COMPS:
        for season in sorted(schema.season_labels(comp)):
            pm = pd.read_parquet(schema.raw_table_path(comp, season, "player_match"))
            proc = pd.read_parquet(schema.processed_path(comp, season))
            proc = proc.assign(comp=comp, season=season)
            players.append(proc)
            pm = pm[pm["appeared"] & (pm["minutes"] > 0)].copy()
            pm["tackle_attempts"] = pm["tackles"] + pm["missed_tackles"]
            pm["goals_made"] = pm["conversions_made"] + pm["penalty_goals_made"]
            pm = pm.merge(proc[["player_uid", "position_group"]], on="player_uid", how="left")
            pm["comp"], pm["season"] = comp, season
            rows.append(pm)
    pm = pd.concat(rows, ignore_index=True)
    pm["key"] = pm["comp"] + "|" + pm["season"] + "|" + pm["player_uid"]
    return pm, pd.concat(players, ignore_index=True)


# --- Split-half -----------------------------------------------------------------
def split_halves(rows: pd.DataFrame, vol_col: str, target: float, cols: list[str],
                 rng: np.random.Generator) -> pd.DataFrame:
    """Matchs de chaque joueur-saison mélangés, moitié A = premiers matchs jusqu'à atteindre
    `target` (en `vol_col`), moitié B = matchs suivants jusqu'à `target`. Retourne une ligne par
    joueur-saison dont les deux moitiés atteignent `target`, colonnes "<col>_A" / "<col>_B"."""
    r = rows.assign(_u=rng.random(len(rows))).sort_values(["key", "_u"])
    before = r.groupby("key", sort=False)[vol_col].cumsum() - r[vol_col]
    in_a = before < target
    a_tot = r[vol_col].where(in_a, 0).groupby(r["key"], sort=False).transform("sum")
    in_b = ~in_a & (before - a_tot < target)
    r = r.assign(half=np.where(in_a, "A", np.where(in_b, "B", "")))
    r = r[r["half"] != ""]
    sums = r.groupby(["key", "half"])[cols + [vol_col]].sum().unstack("half")
    sums.columns = [f"{c}_{h}" for c, h in sums.columns]
    sums = sums.dropna(subset=[f"{vol_col}_A", f"{vol_col}_B"])
    sums = sums[(sums[f"{vol_col}_A"] >= target) & (sums[f"{vol_col}_B"] >= target)]
    meta = rows.drop_duplicates("key").set_index("key")[["comp", "season", "position_group"]]
    return sums.join(meta)


def centered_r(a: pd.Series, b: pd.Series, groups: pd.Series) -> tuple[float, int]:
    """Corrélation de Pearson après centrage de chaque moitié dans son groupe (groupes d'au moins
    3 joueurs)."""
    df = pd.DataFrame({"a": a, "b": b, "g": groups}).dropna()
    df = df[df.groupby("g")["a"].transform("size") >= 3]
    if len(df) < 3:
        return float("nan"), len(df)
    ca = df["a"] - df.groupby("g")["a"].transform("mean")
    cb = df["b"] - df.groupby("g")["b"].transform("mean")
    if ca.std() == 0 or cb.std() == 0:
        return float("nan"), len(df)
    return float(np.corrcoef(ca, cb)[0, 1]), len(df)


def fit_constant(vols: np.ndarray, rs: np.ndarray, weights: np.ndarray) -> float:
    """C de r(v) = v / (v + C) aux moindres carrés pondérés (grille logarithmique)."""
    ok = np.isfinite(rs) & np.isfinite(vols)
    if ok.sum() < 2:
        return float("nan")
    v, r, w = vols[ok], rs[ok], weights[ok]
    grid = np.geomspace(0.5, 1e5, 6000)
    pred = v[None, :] / (v[None, :] + grid[:, None])
    err = ((pred - r[None, :]) ** 2 * w[None, :]).sum(axis=1)
    return float(grid[err.argmin()])


def stability_per80(pm: pd.DataFrame, draws: int, axes: dict | None = None) -> pd.DataFrame:
    """Une ligne par (stat, périmètre, poste ou "tous", m) : r moyen, joueurs, minutes réelles par
    moitié."""
    axes = PER80_AXES if axes is None else axes
    rng = np.random.default_rng(SEED)
    cols = list(axes)
    acc: dict[tuple, list] = {}
    for m in MINUTE_HALVES:
        for _ in range(draws):
            h = split_halves(pm, "minutes", m, cols, rng)
            vol = (h["minutes_A"] + h["minutes_B"]) / 2
            group = h["comp"] + "|" + h["season"] + "|" + h["position_group"]
            for col, (_, positions, _) in axes.items():
                a = h[f"{col}_A"] / h["minutes_A"] * 80
                b = h[f"{col}_B"] / h["minutes_B"] * 80
                for scope in SCOPES:
                    in_scope = h["comp"].isin(COMPS if scope == "club" else [scope])
                    for pos in ["tous"] + positions:
                        sel = in_scope & (h["position_group"].isin(positions) if pos == "tous"
                                          else h["position_group"] == pos)
                        r, n = centered_r(a[sel], b[sel], group[sel])
                        acc.setdefault((col, scope, pos, m), []).append((r, n, vol[sel].mean()))
    out = []
    for (col, scope, pos, m), vals in acc.items():
        arr = np.array(vals, dtype=float)
        out.append({"stat": col, "scope": scope, "pos": pos, "m": m,
                    "r": np.nanmean(arr[:, 0]), "n": arr[:, 1].mean(), "vol": np.nanmean(arr[:, 2])})
    return pd.DataFrame(out)


def stability_pct(pm: pd.DataFrame, draws: int) -> pd.DataFrame:
    rng = np.random.default_rng(SEED + 1)
    acc: dict[tuple, list] = {}
    for key, (_, made, att, by_pos, halves, _, _) in PCT_STATS.items():
        rows = pm[pm[att] > 0]
        for n_half in halves:
            for _ in range(draws):
                h = split_halves(rows, att, n_half, [made], rng)
                a, b = h[f"{made}_A"] / h[f"{att}_A"], h[f"{made}_B"] / h[f"{att}_B"]
                vol = (h[f"{att}_A"] + h[f"{att}_B"]) / 2
                group = h["comp"] + "|" + h["season"]
                if by_pos:
                    group = group + "|" + h["position_group"]
                positions = ["tous"] + (POSITION_GROUPS if by_pos else [])
                for scope in SCOPES:
                    in_scope = h["comp"].isin(COMPS if scope == "club" else [scope])
                    for pos in positions:
                        sel = in_scope & h["position_group"].ne(UNDETERMINED) & (
                            True if pos == "tous" else h["position_group"] == pos)
                        r, n = centered_r(a[sel], b[sel], group[sel])
                        acc.setdefault((key, scope, pos, n_half), []).append((r, n, vol[sel].mean()))
    out = []
    for (key, scope, pos, n_half), vals in acc.items():
        arr = np.array(vals, dtype=float)
        out.append({"stat": key, "scope": scope, "pos": pos, "m": n_half,
                    "r": np.nanmean(arr[:, 0]), "n": arr[:, 1].mean(), "vol": np.nanmean(arr[:, 2])})
    return pd.DataFrame(out)


def fits(stab: pd.DataFrame) -> pd.DataFrame:
    """Constante ajustée (M en minutes, ou P en tentatives) par (stat, périmètre, poste)."""
    out = []
    for (stat, scope, pos), g in stab.groupby(["stat", "scope", "pos"], sort=False):
        g = g[g["n"] >= MIN_PAIRS]
        out.append({"stat": stat, "scope": scope, "pos": pos,
                    "C": fit_constant(g["vol"].to_numpy(), g["r"].to_numpy(), g["n"].to_numpy()),
                    "points": len(g)})
    return pd.DataFrame(out)


def beta_binomial(players: pd.DataFrame, key: str) -> pd.DataFrame:
    """P = p(1-p) / variance réelle - 1, variance réelle = variance observée (résidus centrés par
    groupe, ddof par groupe) - bruit binomial moyen. Par périmètre et par poste."""
    _, made, att, by_pos, *_ = PCT_STATS[key]
    df = players[(players[att] >= BETA_MIN_ATTEMPTS[key])
                 & players["position_group"].ne(UNDETERMINED)].copy()
    df["p"] = df[made] / df[att]
    out = []
    positions = ["tous"] + (POSITION_GROUPS if by_pos else [])
    for scope in SCOPES:
        s = df[df["comp"].isin(COMPS if scope == "club" else [scope])]
        for pos in positions:
            d = s if pos == "tous" else s[s["position_group"] == pos]
            gcols = ["comp", "season"] + (["position_group"] if by_pos else [])
            grp = d.groupby(gcols)
            pbar = grp[made].transform("sum") / grp[att].transform("sum")
            resid = d["p"] - pbar
            dof = len(d) - grp.ngroups
            if dof < 10:
                out.append({"stat": key, "scope": scope, "pos": pos, "P": np.nan, "n": len(d)})
                continue
            var_obs = float((resid ** 2).sum() / dof)
            noise = float((pbar * (1 - pbar) / d[att]).mean())
            var_true = var_obs - noise
            pq = float((pbar * (1 - pbar)).mean())
            p_val = pq / var_true - 1 if var_true > 0 else np.inf
            out.append({"stat": key, "scope": scope, "pos": pos, "P": p_val, "n": len(d)})
    return pd.DataFrame(out)


# --- Population de référence ------------------------------------------------------
def reference_grid(players: pd.DataFrame, minutes_grid=T_SEARCH) -> pd.DataFrame:
    """Une ligne par (matchs, minutes, compétition, saison, poste) : joueurs gardés, exclus, part
    des minutes du poste couvertes."""
    known = players[players["position_group"].ne(UNDETERMINED)]
    out = []
    for g_min in GAMES_GRID:
        for t_min in minutes_grid:
            kept = (known["games_played"] >= g_min) & (known["minutes_total"] >= t_min)
            d = known.assign(kept=kept, kept_min=known["minutes_total"].where(kept, 0))
            agg = d.groupby(["comp", "season", "position_group"]).agg(
                kept=("kept", "sum"), total=("kept", "size"),
                kept_min=("kept_min", "sum"), all_min=("minutes_total", "sum")).reset_index()
            agg["games"], agg["minutes"] = g_min, t_min
            out.append(agg)
    return pd.concat(out, ignore_index=True)


# --- Mise en forme ------------------------------------------------------------------
def fr(x, d: int = 0) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "infini" if isinstance(x, float) and math.isinf(x) else "n.d."
    s = f"{x:,.{d}f}".replace(",", " ").replace(".", ",")
    return s


def pct(x, d: int = 0) -> str:
    return fr(100 * x, d) + " %"


def table(header: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return lines


def round_up(x: float, step: int) -> int:
    return int(math.ceil(x / step) * step)


# --- Rapport --------------------------------------------------------------------------
def build_report(pm, players, st80, fit80, stp, fitp, betas, grid, fit_all, draws) -> tuple[list[str], dict]:
    L: list[str] = []
    add = L.append
    proposals: dict = {}
    seasons = {c: sorted(schema.season_labels(c)) for c in COMPS}
    add("# Calibration V1 : seuils du radar rugby (club)")
    add("")
    add("Généré par `scripts/rugby_calibrate.py` (sans réseau, graine fixe "
        f"{SEED}, {draws} tirages par point). Données : Top 14 {seasons['top14'][0]} à "
        f"{seasons['top14'][-1]}, Pro D2 {seasons['prod2'][0]} à {seasons['prod2'][-1]}, période "
        "« saison complète ». Unité : joueur-saison. Six Nations non calibré (données au lot 7).")
    add("")
    add(f"Volume : {fr(players.shape[0])} joueurs-saisons, {fr(len(pm))} lignes joueur-match "
        "jouées (minutes > 0).")
    add("")
    add("## À lire d'abord : moitié et saison")
    add("")
    add("Le r(m) mesuré en split-half compare deux moitiés de **m minutes chacune** : c'est la "
        "fiabilité d'un échantillon de m minutes, pas celle d'une saison de 2 x m minutes. "
        "On ajuste r(m) = m / (m + M). Pour un joueur qui a joué **T minutes sur la saison**, la "
        "fiabilité de sa stat par 80 est T / (T + M). Le seuil r = 0,6 correspond donc à "
        "**T = 1,5 x M** (T / (T + M) = 0,6 donne T = 0,6 / 0,4 x M). Même lecture pour les "
        "pourcentages : n tentatives sur la saison donnent une fiabilité n / (n + P), et P est le "
        "padding (volume auquel la moitié de l'écart observé entre joueurs est du bruit).")
    add("")
    add("Les corrélations sont calculées à l'intérieur d'un poste (valeurs centrées par "
        "compétition, saison et poste), comme le z-score du radar.")
    add("")
    synth_at = len(L)

    # 1. Stabilité par 80
    add("## 1. Stabilité des stats par 80 minutes")
    add("")
    add("### 1.1 Corrélation split-half selon les minutes par moitié (Top 14 + Pro D2, postes concernés)")
    add("")
    club = st80[(st80["scope"] == "club") & (st80["pos"] == "tous")]
    hdr = ["Axe"] + [f"m = {m}" for m in MINUTE_HALVES]
    rows = []
    for col, (label, _, socle) in PER80_AXES.items():
        g = club[club["stat"] == col].set_index("m")
        rows.append([label + (" (socle)" if socle else "")]
                    + [f"{fr(g.loc[m, 'r'], 2)} ({fr(g.loc[m, 'n'])})" if g.loc[m, "n"] >= MIN_PAIRS
                       else f"({fr(g.loc[m, 'n'])})" for m in MINUTE_HALVES])
    L += table(hdr, rows)
    add("")
    add("Entre parenthèses : nombre moyen de joueurs-saisons ayant deux moitiés de m minutes. "
        f"Corrélation non retenue sous {MIN_PAIRS} joueurs.")
    add("")
    add("### 1.2 Constante M ajustée et minutes de saison pour r = 0,6 (T = 1,5 x M)")
    add("")
    rows = []
    for col, (label, _, socle) in PER80_AXES.items():
        cells = [label + (" (socle)" if socle else "")]
        for scope in SCOPES:
            m_val = fit80.query("stat == @col and scope == @scope and pos == 'tous'")["C"].iloc[0]
            cells += [fr(m_val), fr(SEASON_FACTOR * m_val)]
        rows.append(cells)
    L += table(["Axe", "M Top 14", "T Top 14", "M Pro D2", "T Pro D2", "M club", "T club"], rows)
    add("")

    def socle_threshold(scope: str) -> float:
        ms = np.array([fit80.query("stat == @c and scope == @scope and pos == 'tous'")["C"].iloc[0]
                       for c in SOCLE])
        ts = np.arange(20, 5001, 1)
        rel = ts[:, None] / (ts[:, None] + ms[None, :])
        ok = np.median(rel, axis=1) >= TARGET_R
        return float(ts[ok.argmax()]) if ok.any() else float("nan")

    t_star = {s: socle_threshold(s) for s in SCOPES}
    add("Seuil du plan (4.5) : minutes de saison où la **fiabilité médiane des 4 axes du socle** "
        f"atteint {fr(TARGET_R, 1)} : Top 14 {fr(t_star['top14'])} min, Pro D2 "
        f"{fr(t_star['prod2'])} min, club {fr(t_star['club'])} min.")
    add("")
    rel_rows = []
    for t in (160, 240, 320, 400, 480, 600):
        cells = [f"{t} min"]
        for c in SOCLE:
            m_val = fit80.query("stat == @c and scope == 'club' and pos == 'tous'")["C"].iloc[0]
            cells.append(fr(t / (t + m_val), 2))
        rel_rows.append(cells)
    add("Fiabilité T / (T + M) des axes du socle selon les minutes de la saison (club) :")
    add("")
    L += table(["Saison de"] + [PER80_AXES[c][0] for c in SOCLE], rel_rows)
    add("")

    add("### 1.3 M par poste, axes du socle (club), dont les arrières")
    add("")
    rows = []
    for pos in POSITION_GROUPS:
        cells = [f"**{pos}**" if pos == FULLBACK else pos]
        for c in SOCLE:
            cells.append(fr(fit80.query("stat == @c and scope == 'club' and pos == @pos")["C"].iloc[0]))
        n = st80.query("stat == 'tackles' and scope == 'club' and pos == @pos and m == 120")["n"]
        cells.append(fr(n.iloc[0]))
        rows.append(cells)
    L += table(["Poste"] + [f"M {PER80_AXES[c][0]}" for c in SOCLE] + ["Joueurs à m = 120"], rows)
    add("")
    add("M par poste repose sur moins de joueurs (une trentaine d'arrières par saison et par "
        "compétition) : il est plus bruité que le M global, qui sert au seuil.")
    add("")

    # 2. Population de référence
    known = players[players["position_group"].ne(UNDETERMINED)]
    g_prop = BEFORE["games"]
    grid = grid.assign(cov=grid["kept_min"] / grid["all_min"])
    grid = grid.assign(ok=(grid["kept"] >= MIN_PLAYERS_CELL) & (grid["cov"] >= MIN_COVERAGE))

    def t_cap(scope: str) -> int:
        """Plus grand T (pas de T_STEP) tel que toutes les cellules respectent les deux critères
        de population pour tout seuil inférieur ou égal."""
        g = grid[(grid["games"] == g_prop) & grid["comp"].isin(COMPS if scope == "club" else [scope])]
        ok = g.groupby("minutes")["ok"].all()
        bad = ok[~ok]
        return int(bad.index.min() - T_STEP) if len(bad) else int(ok.index.max())

    caps = {s: t_cap(s) for s in SCOPES}
    t_rel = round_up(t_star["club"], T_STEP)
    t_prop = t_rel if t_rel <= caps["club"] else caps["club"]
    proposals["games"], proposals["minutes"] = g_prop, t_prop
    m_club = {c: fit80.query("stat == @c and scope == 'club' and pos == 'tous'")["C"].iloc[0]
              for c in SOCLE}
    t_stable = round_up(SEASON_FACTOR * max(m_club["tackles"], m_club["metres"]), T_STEP)
    failing = grid[(grid["games"] == g_prop) & (grid["minutes"] == caps["club"] + T_STEP) & ~grid["ok"]]
    proposals["_why_minutes"] = (t_rel, caps, failing, m_club, t_stable)

    add("## 2. Population de référence (matchs et minutes)")
    add("")
    add(f"Critères : au moins {MIN_PLAYERS_CELL} joueurs de référence et au moins "
        f"{pct(MIN_COVERAGE)} des minutes jouées couvertes, **dans chaque cellule** (un poste dans "
        "une compétition-saison : 10 postes x 9 saisons = 90 cellules), plus la fiabilité du "
        "socle (section 1). La couverture est vérifiée poste par poste et non sur toutes les "
        "minutes de la saison : sur l'ensemble, elle resterait au-dessus de 70 % bien après que "
        "les piliers, qui jouent le moins de minutes par match, sont passés en dessous. Les "
        "« Indéterminé » sont hors référence par construction.")
    add("")
    add("### 2.1 Règle et résultat")
    add("")
    add(f"- Fiabilité médiane du socle à {fr(TARGET_R, 1)} : **{fr(t_rel)} minutes** de saison "
        "(section 1.2). Deux des quatre axes du socle (pénalités concédées, ballons perdus) sont "
        "des événements rares : ils n'atteignent 0,6 qu'au-delà de 2 000 minutes, et la médiane "
        "de 4 axes est la moyenne des 2e et 3e, donc tirée par l'un d'eux.")
    add(f"- Plaquages et mètres seuls à {fr(TARGET_R, 1)} : {fr(t_stable)} minutes.")
    add(f"- Plus grand seuil qui respecte les critères de population ({g_prop} matchs) : Top 14 "
        f"{fr(caps['top14'])} min, Pro D2 {fr(caps['prod2'])} min, club **{fr(caps['club'])} min**. "
        f"Cellules qui échouent à {fr(caps['club'] + T_STEP)} min : "
        + " ; ".join(f"{r.position_group} {schema.COMPETITION_SPECS[r.comp].label} {r.season} "
                    f"({r.kept} joueurs, {pct(r.cov)} des minutes)"
                    for r in failing.itertuples()) + ".")
    add(f"- Seuil retenu : le seuil de fiabilité s'il respecte les critères de population, sinon "
        f"le plus grand seuil qui les respecte : **{fr(t_prop)} minutes**.")
    add("")
    rows = []
    for c in SOCLE:
        rows.append([PER80_AXES[c][0], fr(m_club[c]),
                     fr(BEFORE["minutes"] / (BEFORE["minutes"] + m_club[c]), 2),
                     fr(t_prop / (t_prop + m_club[c]), 2)])
    add("Fiabilité T / (T + M) du socle à l'ancien seuil et au seuil retenu (club) :")
    add("")
    L += table(["Axe", "M", f"à {BEFORE['minutes']} min (avant)", f"à {t_prop} min (retenu)"], rows)
    add("")

    add(f"### 2.2 Joueurs gardés et couverture par poste selon le seuil de minutes ({g_prop} matchs)")
    add("")
    add("Chaque case : joueurs de la plus petite cellule du poste / plus petite part des minutes du "
        "poste couverte, sur les 9 compétitions-saisons.")
    add("")
    rows = []
    for pos in POSITION_GROUPS:
        cells = [f"**{pos}**" if pos == FULLBACK else pos]
        for tm in DISPLAY_T:
            d = grid.query("games == @g_prop and minutes == @tm and position_group == @pos")
            cells.append(f"{fr(d['kept'].min())} / {pct(d['cov'].min())}")
        rows.append(cells)
    L += table(["Poste"] + [f"{t} min" for t in DISPLAY_T], rows)
    add("")
    med = known[known["games_played"] >= g_prop].groupby("position_group")["minutes_per_game"].median()
    add("Minutes par match (médiane, joueurs d'au moins "
        f"{g_prop} matchs) : " + ", ".join(f"{p} {fr(med[p])}" for p in POSITION_GROUPS) + ".")
    add("")

    add(f"### 2.3 Seuil de matchs à {t_prop} minutes")
    add("")
    add("Joueurs-saisons qui ont les minutes mais pas les matchs (exclus par le seul seuil de "
        "matchs) :")
    add("")
    rows = []
    has_t = known["minutes_total"] >= t_prop
    for gm in GAMES_GRID:
        excl = known[has_t & (known["games_played"] < gm)]
        rows.append([f"{gm} matchs", fr(len(excl)), pct(len(excl) / has_t.sum(), 1)])
    L += table(["Seuil", "Exclus par les matchs seuls", f"Part des joueurs ≥ {t_prop} min"], rows)
    add("")
    add(f"À {t_prop} minutes, il faut au moins {math.ceil(t_prop / 80)} matchs (80 minutes au "
        f"plus par match hors prolongation) : tout seuil de matchs inférieur ou égal ne change "
        f"rien. On garde la valeur du plan, {g_prop} matchs, qui reste utile pour le badge "
        "« échantillon court » si le seuil de minutes est abaissé plus tard.")
    add("")

    add(f"### 2.4 Détail au seuil retenu ({g_prop} matchs et {t_prop} minutes) et à l'ancien seuil "
        f"({BEFORE['games']} matchs et {BEFORE['minutes']} minutes)")
    add("")
    rows = []
    for pos in POSITION_GROUPS:
        cells = [f"**{pos}**" if pos == FULLBACK else pos]
        for gm, tm in ((g_prop, t_prop), (BEFORE["games"], BEFORE["minutes"])):
            for comp in COMPS:
                d = grid.query("games == @gm and minutes == @tm and comp == @comp "
                               "and position_group == @pos")
                cells.append(f"{fr(d['kept'].min())} à {fr(d['kept'].max())} "
                             f"({pct((d['kept_min'] / d['all_min']).min())})")
        rows.append(cells)
    L += table(["Poste", "Retenu Top 14", "Retenu Pro D2", "Avant Top 14", "Avant Pro D2"], rows)
    add("")
    add("Chaque case : joueurs de référence par saison (minimum à maximum sur les saisons) et, "
        "entre parenthèses, la plus petite part des minutes du poste couverte sur une saison.")
    add("")
    add("### 2.5 Arrières, saison par saison")
    add("")
    rows = []
    for comp in COMPS:
        for season in seasons[comp]:
            cells = [schema.COMPETITION_SPECS[comp].label, season]
            tot = known.query("comp == @comp and season == @season and position_group == @FULLBACK")
            cells.append(fr(len(tot)))
            for gm, tm in ((g_prop, t_prop), (BEFORE["games"], BEFORE["minutes"])):
                d = grid.query("games == @gm and minutes == @tm and comp == @comp "
                               "and season == @season and position_group == @FULLBACK").iloc[0]
                cells.append(f"{fr(d['kept'])} ({pct(d['cov'])})")
            rows.append(cells)
    L += table(["Compétition", "Saison", "Arrières (tous)", f"Gardés {g_prop} m. / {t_prop} min",
                f"Gardés {BEFORE['games']} m. / {BEFORE['minutes']} min"], rows)
    add("")
    add("### 2.6 Joueurs « Indéterminé » qui passeraient le seuil (P5)")
    add("")
    und = players[players["position_group"].eq(UNDETERMINED)]
    rows = []
    for comp in COMPS:
        for season in seasons[comp]:
            d = und.query("comp == @comp and season == @season")
            n_prop = int(((d["games_played"] >= g_prop) & (d["minutes_total"] >= t_prop)).sum())
            n_plan = int(((d["games_played"] >= BEFORE["games"])
                          & (d["minutes_total"] >= BEFORE["minutes"])).sum())
            rows.append([schema.COMPETITION_SPECS[comp].label, season, fr(len(d)), n_prop, n_plan])
    L += table(["Compétition", "Saison", "Indéterminé", "Passeraient (retenu)", "Passeraient (avant)"],
               rows)
    add("")

    # 3. Padding
    add("## 3. Padding P des pourcentages")
    add("")
    add("Split-half en tentatives : r(n) = n / (n + P), n = tentatives par moitié. Contrôle par le "
        "modèle bêta-binomial (P = p(1-p) / variance réelle - 1), sur les joueurs-saisons d'au "
        f"moins {BETA_MIN_ATTEMPTS['tackle_pct']} plaquages tentés, "
        f"{BETA_MIN_ATTEMPTS['gain_line_pct']} courses ou {BETA_MIN_ATTEMPTS['goal_kick_pct']} "
        "tentatives au but. % plaquages et % gain de ligne centrés par poste ; % au pied centré "
        "par compétition et saison (référence : tous les buteurs).")
    add("")
    for key, (label, _, _, by_pos, halves, *_ ) in PCT_STATS.items():
        add(f"### {label}")
        add("")
        g = stp[(stp["stat"] == key) & (stp["scope"] == "club") & (stp["pos"] == "tous")].set_index("m")
        L += table(["n par moitié"] + [str(h) for h in halves],
                   [["r (joueurs)"] + [f"{fr(g.loc[h, 'r'], 2)} ({fr(g.loc[h, 'n'])})"
                                       if g.loc[h, "n"] >= MIN_PAIRS else f"({fr(g.loc[h, 'n'])})"
                                       for h in halves]])
        add("")
        rows = []
        for scope in SCOPES:
            p_split = fitp.query("stat == @key and scope == @scope and pos == 'tous'")["C"].iloc[0]
            p_beta = betas.query("stat == @key and scope == @scope and pos == 'tous'")["P"].iloc[0]
            rows.append([{"top14": "Top 14", "prod2": "Pro D2", "club": "Club"}[scope],
                         fr(p_split), fr(p_beta)])
        L += table(["Périmètre", "P split-half", "P bêta-binomial"], rows)
        add("")
        if by_pos:
            rows = []
            for pos in POSITION_GROUPS:
                p_split = fitp.query("stat == @key and scope == 'club' and pos == @pos")["C"].iloc[0]
                bb = betas.query("stat == @key and scope == 'club' and pos == @pos").iloc[0]
                rows.append([f"**{pos}**" if pos == FULLBACK else pos, fr(p_split), fr(bb["P"]),
                             fr(bb["n"])])
            add("Par poste (club) :")
            add("")
            L += table(["Poste", "P split-half", "P bêta-binomial", "Joueurs-saisons (bêta)"], rows)
            add("")
        p_final = fitp.query("stat == @key and scope == 'club' and pos == 'tous'")["C"].iloc[0]
        proposals[f"P_{key}"] = int(round(p_final))

    # 4. NC
    for key in PCT_STATS:
        p_val = proposals[f"P_{key}"]
        proposals[f"NC_{key}"] = max(5, round_up(p_val * NC_WEIGHT / (1 - NC_WEIGHT) - 2.5, 5))
    add("## 4. Seuils NC (tentatives minimum sur la saison)")
    add("")
    ref = known[(known["games_played"] >= g_prop) & (known["minutes_total"] >= t_prop)]
    add(f"Population : joueurs de référence au seuil retenu ({g_prop} matchs et {t_prop} minutes), "
        f"{fr(len(ref))} joueurs-saisons. Poids = n / (n + P) : part du joueur lui-même dans son "
        "% ajusté au seuil (le reste est la moyenne du poste).")
    add("")
    add(f"Règle : seuil NC = volume où le poids du joueur vaut {fr(NC_WEIGHT, 1)} (n = P / 4), "
        "arrondi à 5. C'est l'ordre de grandeur des seuils NBA : 1 tir à 3 points par match sur "
        "environ 70 matchs donne 70 / (70 + 242) = 0,22, 0,5 lancer franc par match donne "
        "35 / (35 + 156) = 0,18. En dessous, le % ajusté serait à plus de 80 % la moyenne du poste.")
    add("")
    nc_share = {}
    for key in ("tackle_pct", "gain_line_pct"):
        label, _, att, _, _, thresholds, _ = PCT_STATS[key]
        p_val, nc = proposals[f"P_{key}"], proposals[f"NC_{key}"]
        thresholds = tuple(sorted(set(thresholds) | {nc, BEFORE[f"NC_{key}"]}))
        add(f"### {label} (P = {p_val}, seuil NC retenu : {nc})")
        add("")
        rows = []
        for pos in POSITION_GROUPS + ["Tous"]:
            d = ref if pos == "Tous" else ref[ref["position_group"] == pos]
            rows.append([f"**{pos}**" if pos in (FULLBACK, "Tous") else pos]
                        + [pct((d[att] < t).mean(), 1) for t in thresholds])
        rows.append(["Poids au seuil"] + [fr(t / (t + p_val), 2) for t in thresholds])
        L += table(["Part NC"] + [f"< {t}" for t in thresholds], rows)
        add("")
        by_pos = ref.groupby("position_group")[att].apply(lambda s: (s < nc).mean())
        nc_share[key] = ((ref[att] < nc).mean(), by_pos.idxmax(), by_pos.max())
        q = ref.groupby("position_group")[att].quantile(0.05)
        add(f"5e centile des {('plaquages tentés' if key == 'tackle_pct' else 'courses')} par poste : "
            + ", ".join(f"{p} {fr(q[p])}" for p in POSITION_GROUPS) + ".")
        add("")
    p_kick, nc_kick = proposals["P_goal_kick_pct"], proposals["NC_goal_kick_pct"]
    add(f"### % au pied (P = {p_kick}, seuil NC retenu : {nc_kick})")
    add("")
    add("Tous les joueurs de la saison, sans condition de minutes (la référence du % au pied est "
        "l'ensemble des buteurs qualifiés, sans poste).")
    add("")
    rows, kick_stats = [], {}
    team_seasons = int(players.groupby(["comp", "season"])["team_uid"].nunique().sum())
    for t in sorted(set(PCT_STATS["goal_kick_pct"][5]) | {nc_kick, BEFORE["NC_goal_kick_pct"]}):
        per_season = []
        for (comp, season), d in players.groupby(["comp", "season"]):
            n_teams = d["team_uid"].nunique()
            qual = d[d["goal_attempts"] >= t]
            top = d.sort_values("goal_attempts").drop_duplicates("team_uid", keep="last")
            per_season.append((len(qual), len(qual) / n_teams, int((top["goal_attempts"] < t).sum())))
        arr = np.array(per_season, dtype=float)
        kick_stats[t] = (arr[:, 1].min(), arr[:, 1].max(), int(arr[:, 2].sum()))
        rows.append([f"≥ {t}", f"{fr(arr[:, 0].min())} à {fr(arr[:, 0].max())}",
                     f"{fr(arr[:, 1].min(), 1)} à {fr(arr[:, 1].max(), 1)}", fr(arr[:, 2].sum()),
                     fr(t / (t + p_kick), 2)])
    L += table(["Tentatives", "Buteurs qualifiés par saison", "Par équipe",
                f"Équipes-saisons dont le 1er buteur est NC (sur {team_seasons})", "Poids au seuil"],
               rows)
    add("")
    add("« 1er buteur » = joueur de l'équipe (équipe de son dernier match) avec le plus de "
        "tentatives sur la saison. Critère du plan : au moins le 1er buteur de chaque équipe, "
        "idéalement 1,5 à 2 buteurs qualifiés par équipe.")
    add("")

    # 5. Fiabilité par axe et par poste, radar final
    add(f"## 5. Fiabilité par axe et par poste à {t_prop} minutes")
    add("")
    add(f"Règle (décision du 13 octobre 2026) : un axe n'est sur le radar d'un poste que si sa "
        f"fiabilité à {t_prop} minutes atteint {fr(schema.RADAR_MIN_RELIABILITY, 1)} **pour ce "
        f"poste**. En italique : sous {fr(schema.RADAR_MIN_RELIABILITY, 1)}.")
    add("")
    add(f"- Axes par 80 minutes : fiabilité T / (T + M) avec T = {t_prop} et M ajusté par split-half "
        "à l'intérieur du poste (centrage par compétition et saison). Les M par poste reposent sur "
        "270 à 830 joueurs-saisons (section 1.3) : précision d'environ ±0,05.")
    add("- % plaquages et % gain de ligne : fiabilité n / (n + P), n = tentatives médianes des "
        f"joueurs de référence du poste ({g_prop} matchs et {t_prop} min), indiquées sous le tableau.")
    kickers = players[players["goal_attempts"] >= nc_kick]
    n_kick = float(kickers["goal_attempts"].median())
    rel_kick = n_kick / (n_kick + p_kick)
    add(f"- % au pied : buteurs qualifiés ({nc_kick} tentatives ou plus), {fr(len(kickers))} "
        f"joueurs-saisons, {fr(n_kick)} tentatives médianes, fiabilité {fr(n_kick)} / ({fr(n_kick)} "
        f"+ {p_kick}) = {fr(rel_kick, 2)}.")
    add("")
    rel = (t_prop / (t_prop + fit_all[(fit_all["scope"] == "club")]
                     .pivot(index="stat", columns="pos", values="C")))
    pct_rel, pct_n = {}, {}
    for key, att in (("tackle_pct", "tackle_attempts"), ("gain_line_pct", "carries")):
        med = ref.groupby("position_group")[att].median()
        p_val = proposals[f"P_{key}"]
        pct_n[key] = med
        pct_rel[key] = {pos: med[pos] / (med[pos] + p_val) for pos in POSITION_GROUPS}
        pct_rel[key]["tous"] = ref[att].median() / (ref[att].median() + p_val)

    def reliability(axis: str, pos: str) -> float:
        if axis in pct_rel:
            return pct_rel[axis][pos]
        return float(rel.loc[axis, pos]) if axis in rel.index and pos in rel.columns else float("nan")

    def cell(x: float) -> str:
        if not math.isfinite(x):
            return "n.d."
        return fr(x, 2) if x >= schema.RADAR_MIN_RELIABILITY else f"*{fr(x, 2)}*"

    short = {FLANKER: "3e ligne aile", NUMBER_8: "3e ligne centre", LOCK: "2e ligne"}
    rows = [[label] + [cell(reliability(axis, p)) for p in POSITION_GROUPS + ["tous"]]
            for axis, label in [("tackle_pct", "% plaquages"), ("gain_line_pct", "% gain de ligne")]
            + list(ALL_PER80.items())]
    L += table(["Axe"] + [short.get(p, p) for p in POSITION_GROUPS] + ["Tous"], rows)
    add("")
    for key, label in (("tackle_pct", "Plaquages tentés"), ("gain_line_pct", "Courses")):
        add(f"{label}, médiane par poste : "
            + ", ".join(f"{short.get(p, p)} {fr(pct_n[key][p])}" for p in POSITION_GROUPS) + ".")
        add("")
    add("Points = essais chez les avants (aucun buteur) : mêmes valeurs que la ligne Essais. "
        "« n.d. » : aucune paire exploitable.")
    add("")
    add("### Radar club par poste (`schema.RADAR_AXES_BY_POSITION`)")
    add("")
    rows, too_low = [], []
    for pos in POSITION_GROUPS:
        axes = schema.RADAR_AXES_BY_POSITION[pos]
        parts = []
        for axis in axes:
            r = reliability(axis, pos)
            parts.append(f"{schema.RADAR_AXES_CLUB[axis][0]} {cell(r)}")
            if not r >= schema.RADAR_MIN_RELIABILITY:
                too_low.append(f"{pos} : {schema.RADAR_AXES_CLUB[axis][0]}")
        rows.append([f"**{pos}**" if pos == FULLBACK else pos, ", ".join(parts), str(len(axes))])
    L += table(["Poste", "Axes (fiabilité)", "Axes"], rows)
    add("")
    add("Contrôle : " + ("tous les axes du radar atteignent le seuil." if not too_low else
                         "**axes sous le seuil** : " + " ; ".join(too_low) + "."))
    add("")
    proposals["_radar_too_low"] = too_low

    # Synthèse, insérée en tête du rapport
    t_rel, caps, failing, m_club, t_stable = proposals.pop("_why_minutes")
    min_cell = int(grid.query("games == @g_prop and minutes == @t_prop")["kept"].min())
    rel = {c: t_prop / (t_prop + m_club[c]) for c in SOCLE}
    S = ["## Synthèse", ""]
    S.append("Valeurs calculées pour le club (Top 14 et Pro D2, un seul jeu de seuils), validées le "
             "13 octobre 2026 et reportées dans `data_sources/rugby/schema.py` (contrôle sous le "
             "tableau).")
    S.append("")
    rows = [[
        "Référence : minutes de saison", str(BEFORE["minutes"]), f"**{t_prop}**",
        f"r = 0,6 médian sur le socle demanderait {fr(t_rel)} min (Top 14 {fr(t_star['top14'])}, Pro D2 "
        f"{fr(t_star['prod2'])}) : intenable. Plus grand seuil qui garde ≥ {MIN_PLAYERS_CELL} joueurs "
        f"et ≥ {pct(MIN_COVERAGE)} des minutes dans chaque poste et saison : Top 14 {caps['top14']}, "
        f"Pro D2 {caps['prod2']}, club {caps['club']} (au-delà : "
        + ", ".join(sorted({f"{r.position_group}" for r in failing.itertuples()})) + "). "
        f"Fiabilité à {t_prop} min : plaquages {fr(rel['tackles'], 2)}, mètres "
        f"{fr(rel['metres'], 2)}, pénalités {fr(rel['penalties_conceded'], 2)}, ballons perdus "
        f"{fr(rel['turnovers_conceded'], 2)} (à {BEFORE['minutes']} min : "
        f"{fr(BEFORE['minutes'] / (BEFORE['minutes'] + m_club['tackles']), 2)}, "
        f"{fr(BEFORE['minutes'] / (BEFORE['minutes'] + m_club['metres']), 2)}, "
        f"{fr(BEFORE['minutes'] / (BEFORE['minutes'] + m_club['penalties_conceded']), 2)}, "
        f"{fr(BEFORE['minutes'] / (BEFORE['minutes'] + m_club['turnovers_conceded']), 2)}). "
        f"Plus petite cellule : {min_cell} joueurs."],
        ["Référence : matchs", str(BEFORE["games"]), f"**{g_prop}**",
         f"Sans effet à {t_prop} min (il faut déjà {math.ceil(t_prop / 80)} matchs au moins) ; "
         "gardé pour la lisibilité du badge."],
        ["Badge « échantillon court »", f"{BEFORE['games']} m. / {BEFORE['minutes']} min",
         f"**{g_prop} m. / {t_prop} min**", "Mêmes valeurs que la référence, comme la NBA."],
    ]
    for key, (label, *_rest) in PCT_STATS.items():
        p_split = proposals[f"P_{key}"]
        p_beta = betas.query("stat == @key and scope == 'club' and pos == 'tous'")["P"].iloc[0]
        p_t14 = fitp.query("stat == @key and scope == 'top14' and pos == 'tous'")["C"].iloc[0]
        p_pd2 = fitp.query("stat == @key and scope == 'prod2' and pos == 'tous'")["C"].iloc[0]
        why = (f"Split-half club {p_split} (Top 14 {fr(p_t14)}, Pro D2 {fr(p_pd2)}) ; "
               f"bêta-binomial {fr(p_beta)}.")
        if PCT_STATS[key][3]:
            per_pos = fitp.query("stat == @key and scope == 'club' and pos != 'tous'").set_index("pos")["C"]
            ratio = per_pos.max() / per_pos.min()
            why += (f" Par poste de {fr(per_pos.min())} ({per_pos.idxmin()}) à {fr(per_pos.max())} "
                    f"({per_pos.idxmax()}), rapport {fr(ratio, 1)}"
                    + (" : **divergence forte**, P par poste à décider." if ratio > 2 else "."))
        rows.append([f"{label} : padding P", str(BEFORE[f'P_{key}']), f"**{p_split}**", why])
        nc = proposals[f"NC_{key}"]
        if key in nc_share:
            share, worst, worst_share = nc_share[key]
            why = (f"Poids {fr(nc / (nc + p_split), 2)} au seuil. NC chez {pct(share, 1)} des joueurs "
                   f"de référence, au plus {pct(worst_share, 1)} ({worst}).")
        else:
            lo, hi, top_nc = kick_stats[nc]
            why = (f"Poids {fr(nc / (nc + p_split), 2)} au seuil. {fr(lo, 1)} à {fr(hi, 1)} buteurs "
                   f"qualifiés par équipe et par saison ; 1er buteur NC dans {top_nc} équipes-saisons "
                   f"sur {team_seasons}.")
        rows.append([f"{label} : seuil NC (tentatives)", str(BEFORE[f'NC_{key}']), f"**{nc}**", why])
    S += table(["Seuil", "Avant calibration", "Retenu", "Justification (chiffres)"], rows)
    S.append("")
    padding = schema.PCT_PADDING[schema.CLUB]
    in_schema = dict(zip(("games", "minutes"), schema.SAMPLE_THRESHOLDS[schema.CLUB]))
    for key in PCT_STATS:
        in_schema[f"P_{key}"], in_schema[f"NC_{key}"] = padding[f"{key}_adj"][2:4]
    diff = [f"{k} ({in_schema[k]} contre {proposals[k]})" for k in in_schema
            if in_schema[k] != proposals[k]]
    S.append("Contrôle des constantes de `schema.py` : " + (
        "identiques aux valeurs calculées ici." if not diff
        else "**différentes** : " + ", ".join(diff) + "."))
    # M des stats par 80 hors radar (schema.PER80_SHRINK_M) : M club de la section 1.2, arrondi.
    m_diff = []
    for col, m_schema in schema.PER80_SHRINK_M[schema.CLUB].items():
        m_val = round(fit80.query("stat == @col and scope == 'club' and pos == 'tous'")["C"].iloc[0])
        if m_val != m_schema:
            m_diff.append(f"{col} ({m_schema} contre {m_val})")
    S.append("")
    S.append("Contrôle des M de `schema.PER80_SHRINK_M` (stats par 80 hors radar, rapprochées de la "
             "moyenne du poste) : " + ("identiques aux M club de la section 1.2." if not m_diff
                                       else "**différents** : " + ", ".join(m_diff) + "."))
    too_low = proposals.pop("_radar_too_low")
    S.append("")
    S.append(f"Radar par poste (`schema.RADAR_AXES_BY_POSITION`, section 5) : " + (
        f"tous les axes atteignent {fr(schema.RADAR_MIN_RELIABILITY, 1)} de fiabilité." if not too_low
        else "**axes sous le seuil** : " + " ; ".join(too_low) + "."))
    S.append("")
    S.append("Six Nations (2 matchs et 120 min, NC 10 plaquages et 8 tentatives au pied, mètres par "
             "course et % au lancer) : non calibré, faute de données avant le lot 7. Même méthode à ce "
             "moment-là.")
    S.append("")
    L[synth_at:synth_at] = S
    return L, proposals


def main(argv: list[str] | None = None) -> int:
    # Poste sans aucune paire à un volume donné : moyenne vide, NaN attendu.
    warnings.filterwarnings("ignore", "Mean of empty slice", RuntimeWarning)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--draws", type=int, default=N_DRAWS)
    args = parser.parse_args(argv)
    pm, players = load()
    st80 = stability_per80(pm, args.draws)
    fit80 = fits(st80)
    stp = stability_pct(pm, args.draws)
    fitp = fits(stp)
    betas = pd.concat([beta_binomial(players, k) for k in PCT_STATS], ignore_index=True)
    grid = reference_grid(players)
    fit_all = fits(stability_per80(pm, args.draws,
                                   {c: (label, POSITION_GROUPS, False) for c, label in ALL_PER80.items()}))
    lines, proposals = build_report(pm, players, st80, fit80, stp, fitp, betas, grid, fit_all,
                                    args.draws)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Rapport écrit : {args.out}")
    for k, v in proposals.items():
        print(f"  {k} = {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
