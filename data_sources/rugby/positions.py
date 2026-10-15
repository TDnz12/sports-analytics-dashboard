"""
Postes des joueurs, par compétition et par saison (plan, 4.2 et P5), calculés sur la saison
complète : un joueur a le même poste en "Saison complète" et en "Phase régulière".

- Poste principal : groupe le plus porté comme titulaire (maillots 1 à 15). Égalité : groupe avec
  le plus de minutes, puis le plus récent. position_source = "titulaire".
- Postes secondaires : autres groupes portés comme titulaire, avec leur part des titularisations
  ("Centre 30 %"). position_share : part du poste principal (badge "poste mixte" sous
  MIXED_POSITION_SHARE, à l'affichage). Le détail par numéro va dans position_detail ("Pilier : 1 (70 %), 3 (30 %)").
- Joueur jamais titulaire : maillot de banc le plus porté (égalité : plus de minutes, puis le plus
  récent). 16 = talonneur, 17 et 18 = piliers (règle de remplacement de la première ligne) :
  position_source = "banc". 19 à 23 : pas de repli (bancs en 5/3 ou 6/2), "Indéterminé", hors
  population de référence du radar. Le libellé texte InCrowd ("sub 1" à "sub 8") n'apporte rien.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PROP, HOOKER, LOCK, FLANKER, NUMBER_8 = (
    "Pilier", "Talonneur", "Deuxième ligne", "Troisième ligne aile", "Troisième ligne centre")
SCRUM_HALF, FLY_HALF, CENTRE, WING, FULLBACK = (
    "Demi de mêlée", "Demi d'ouverture", "Centre", "Ailier", "Arrière")
UNDETERMINED = "Indéterminé"

POSITION_GROUPS = [PROP, HOOKER, LOCK, FLANKER, NUMBER_8,
                   SCRUM_HALF, FLY_HALF, CENTRE, WING, FULLBACK]
FORWARDS, BACKS = "Avants", "Arrières"
GROUP_FAMILY = {g: FORWARDS for g in POSITION_GROUPS[:5]} | {g: BACKS for g in POSITION_GROUPS[5:]}

JERSEY_GROUP = {
    1: PROP, 2: HOOKER, 3: PROP, 4: LOCK, 5: LOCK, 6: FLANKER, 7: FLANKER, 8: NUMBER_8,
    9: SCRUM_HALF, 10: FLY_HALF, 11: WING, 12: CENTRE, 13: CENTRE, 14: WING, 15: FULLBACK,
}
BENCH_FALLBACK = {16: HOOKER, 17: PROP, 18: PROP}

SOURCE_STARTER, SOURCE_BENCH = "titulaire", "banc"
POSITION_COLUMNS = ["player_uid", "position_group", "position_family", "position_source",
                    "secondary_positions", "position_detail", "position_share"]
# Poste principal sous 60 % des titularisations : "poste mixte" (décision B.1 de l'audit ; 20 à 36
# joueurs par saison parmi les titulaires d'au moins 5 matchs).
MIXED_POSITION_SHARE = 0.6


def _pct(x: float) -> str:
    return f"{round(100 * x)} %"


def _pick(df: pd.DataFrame, key: str) -> pd.Series:
    """Par joueur, la valeur de `key` la plus fréquente ; égalité : plus de minutes, puis date la
    plus récente. `df` : une ligne par (joueur, key) avec n, minutes, last_date."""
    best = df.sort_values(["player_uid", "n", "minutes", "last_date"],
                          ascending=[True, False, False, False])
    return best.drop_duplicates("player_uid").set_index("player_uid")[key]


def assign_positions(lineups: pd.DataFrame, player_match: pd.DataFrame,
                     matches: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par joueur présent sur au moins une feuille de match (colonnes POSITION_COLUMNS)."""
    df = (lineups[["match_uid", "player_uid", "jersey", "is_starter"]]
          .merge(player_match[["match_uid", "player_uid", "minutes"]],
                 on=["match_uid", "player_uid"], how="left")
          .merge(matches[["match_uid", "date_utc"]], on="match_uid", how="left"))
    df["minutes"] = df["minutes"].fillna(0)
    players = pd.Index(df["player_uid"].unique(), name="player_uid")
    out = pd.DataFrame(index=players, columns=POSITION_COLUMNS[1:], dtype=object)

    starts = df[df["is_starter"]].copy()
    starts["group"] = starts["jersey"].map(JERSEY_GROUP)
    if len(starts):
        by_group = (starts.groupby(["player_uid", "group"])
                    .agg(n=("match_uid", "size"), minutes=("minutes", "sum"),
                         last_date=("date_utc", "max")).reset_index())
        main = _pick(by_group, "group")
        out.loc[main.index, "position_group"] = main
        out.loc[main.index, "position_source"] = SOURCE_STARTER

        total = by_group.groupby("player_uid")["n"].transform("sum")
        by_group["share"] = by_group["n"] / total
        by_jersey = starts.groupby(["player_uid", "group", "jersey"]).size().rename("n").reset_index()
        for uid, g in by_group.groupby("player_uid"):
            g = g.sort_values(["share", "minutes"], ascending=False)
            others = g[g["group"] != main[uid]]
            out.at[uid, "position_share"] = float(g.loc[g["group"] == main[uid], "share"].iloc[0])
            out.at[uid, "secondary_positions"] = (
                ", ".join(f"{r.group} {_pct(r.share)}" for r in others.itertuples()) or None)
            details = []
            for r in g.itertuples():
                j = by_jersey[(by_jersey["player_uid"] == uid) & (by_jersey["group"] == r.group)]
                j = j.sort_values(["n", "jersey"], ascending=[False, True])
                nums = ", ".join(f"{int(x.jersey)} ({_pct(x.n / r.n)})" for x in j.itertuples())
                details.append(f"{r.group} : {nums}")
            out.at[uid, "position_detail"] = " ; ".join(details)

    never_started = players.difference(starts["player_uid"].unique())
    bench = df[df["player_uid"].isin(never_started)]
    if len(bench):
        by_jersey = (bench.groupby(["player_uid", "jersey"])
                     .agg(n=("match_uid", "size"), minutes=("minutes", "sum"),
                          last_date=("date_utc", "max")).reset_index())
        jersey = _pick(by_jersey, "jersey")
        group = jersey.map(BENCH_FALLBACK)
        known = group.dropna()
        out.loc[known.index, "position_group"] = known
        out.loc[known.index, "position_source"] = SOURCE_BENCH
        out.loc[known.index, "position_detail"] = [
            f"{g} : banc, n° {int(jersey[uid])} le plus porté" for uid, g in known.items()]

    out["position_group"] = out["position_group"].fillna(UNDETERMINED)
    out["position_family"] = out["position_group"].map(GROUP_FAMILY)
    share = out.pop("position_share").astype(float)
    out = out.replace({np.nan: None})
    out["position_share"] = share
    return out.reset_index()[POSITION_COLUMNS]
