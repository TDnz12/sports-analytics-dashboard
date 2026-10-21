"""
Agrégation par saison (plan, 4.3) : tables brutes d'une compétition et d'une saison -> une ligne
par joueur, même contrat que la NBA (COMMON_COLUMNS) plus les colonnes propres au rugby.

- Totaux : sommes sur les matchs de la période ("all" : saison complète, phases finales incluses ;
  "regular" : phase régulière seule). Une stat absente de la source reste NaN (somme min_count=1).
- Par 80 minutes : total / minutes x 80, stat par stat, numérateur et dénominateur sur les MÊMES
  matchs : ceux où les minutes sont connues et > 0 et où la stat est connue (décisions B.3 et C4
  de l'audit). Les totaux gardent toutes les lignes (0 minute avec des stats comprises).
- Club (team, team_uid) : celui où il a joué le plus de minutes ; égalité : plus de matchs joués,
  puis le plus récent. clubs_detail : JSON [[team_uid, nom source, matchs joués], ...] des clubs
  où il a joué au moins un match, dans l'ordre chronologique (affiché par stats.py).
- Pourcentages toujours depuis les sommes, jamais en moyenne de pourcentages par match. Drops
  exclus du % au pied (numérateur et tentatives). Les pourcentages ajustés (padding, NC) sont
  calculés au moment du radar (lot 6), avec les seuils fixés par la calibration.
- Poste : calculé sur la saison complète (positions.py), identique pour les deux périodes.
- Disponibilité : matchs sur la feuille / matchs de son équipe entre son premier et son dernier
  match sur la feuille (somme par club s'il en a changé en cours de saison, et par saison sur une
  fenêtre de plusieurs saisons).
- Fenêtre de plusieurs saisons (mode 3 saisons du radar, aggregate_window) : tables brutes des
  saisons mises bout à bout, mêmes calculs (sommes puis division, poste et club principal sur la
  fenêtre), plus le détail saison par saison.
- Âge, taille, poids : NaN en Top 14 et Pro D2 (profils InCrowd abandonnés, décision 11).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import schema
from .positions import assign_positions

# Stats sans version par 80 minutes : cartons (affichés en totaux dans la carte et le tableau).
NO_PER80 = {"yellow_cards", "red_cards"}
PER80_STATS = [c for c in schema.PLAYER_MATCH_STAT_COLUMNS if c not in NO_PER80]

# Pourcentages et ratios : colonne -> (numérateur, dénominateur). Le dénominateur sert aussi de
# volume de tentatives pour le seuil NC du radar.
RATIOS = {
    "tackle_pct": ("tackles", "tackle_attempts"),
    "gain_line_pct": ("carries_gain_line", "carries"),
    "metres_per_carry": ("metres", "carries"),
    "goal_kick_pct": ("goals_made", "goal_attempts"),
}


def _div(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den.where(den > 0)).astype(float)


def _team_names(matches: pd.DataFrame) -> dict:
    names = pd.concat([
        matches[["home_team_uid", "home_team", "date_utc"]].set_axis(["uid", "name", "d"], axis=1),
        matches[["away_team_uid", "away_team", "date_utc"]].set_axis(["uid", "name", "d"], axis=1),
    ]).sort_values("d")
    return names.drop_duplicates("uid", keep="last").set_index("uid")["name"].to_dict()


def _team_matches_span(squad: pd.DataFrame, matches: pd.DataFrame) -> pd.Series:
    """Par joueur : nombre de matchs de son (ses) équipe(s), dans la période, entre son premier et
    son dernier match sur la feuille avec cette équipe, saison par saison : sur une fenêtre de
    plusieurs saisons, un club quitté puis retrouvé ne compte pas les matchs joués entre-temps."""
    cols = ["team_uid", "date_utc", "season"]
    team_games = pd.concat([
        matches[["home_team_uid", "date_utc", "season"]].set_axis(cols, axis=1),
        matches[["away_team_uid", "date_utc", "season"]].set_axis(cols, axis=1),
    ])
    dates = {k: np.sort(g["date_utc"].values) for k, g in team_games.groupby(["team_uid", "season"])}
    spans = (squad.groupby(["player_uid", "team_uid", "season"])["date_utc"]
             .agg(["min", "max"]).reset_index())
    spans["n"] = [
        int(np.searchsorted(dates[(t, s)], hi, side="right")
            - np.searchsorted(dates[(t, s)], lo, side="left"))
        for t, s, lo, hi in zip(spans["team_uid"], spans["season"], spans["min"].values,
                                spans["max"].values)
    ]
    return spans.groupby("player_uid")["n"].sum()


def _clubs(squad: pd.DataFrame, names: dict) -> tuple[pd.Series, pd.Series]:
    """(club principal, clubs_detail) par joueur, voir la docstring du module."""
    by_club = (squad.groupby(["player_uid", "team_uid"])
               .agg(minutes=("minutes", "sum"), games=("appeared", "sum"),
                    first=("date_utc", "min"), last=("date_utc", "max")).reset_index())
    main = (by_club.sort_values(["player_uid", "minutes", "games", "last"],
                                ascending=[True, False, False, False])
            .drop_duplicates("player_uid").set_index("player_uid")["team_uid"])
    played = by_club[by_club["games"] > 0].sort_values(["player_uid", "first"])
    detail = played.groupby("player_uid").apply(
        lambda g: json.dumps([[t, names.get(t), int(n)] for t, n in zip(g["team_uid"], g["games"])],
                             ensure_ascii=False),
        include_groups=False)
    return main, detail


def aggregate_season(tables: dict[str, pd.DataFrame], competition: str,
                     period: str = "all") -> pd.DataFrame:
    """Une ligne par joueur présent sur au moins une feuille de match de la période."""
    if period not in schema.PERIODS:
        raise ValueError(f"Période inconnue : {period!r}")
    all_matches = tables["matches"]
    season = all_matches.sort_values("date_utc")["season"].iloc[-1]   # la plus récente
    positions = assign_positions(tables["lineups"], tables["player_match"], all_matches)

    matches = all_matches if period == "all" else all_matches[all_matches["phase"] == "regular"]
    keep = set(matches["match_uid"])
    squad = (tables["lineups"][tables["lineups"]["match_uid"].isin(keep)]
             .merge(tables["player_match"], on=["match_uid", "team_uid", "player_uid"], how="left")
             .merge(matches[["match_uid", "date_utc", "season"]], on="match_uid", how="left"))
    squad["goals_made"] = squad["conversions_made"] + squad["penalty_goals_made"]
    squad["tackle_attempts"] = squad["tackles"] + squad["missed_tackles"]

    g = squad.groupby("player_uid", sort=False)
    out = pd.DataFrame({
        "games_played": g["appeared"].sum().astype(int),
        "starts": g["is_starter"].sum().astype(int),
        "matchday_squads": g.size(),
    })
    last = squad.sort_values("date_utc").drop_duplicates("player_uid", keep="last").set_index("player_uid")
    out["player"] = last["player_name"]
    out["first_name"] = last["first_name"]
    out["last_name"] = last["last_name"]
    team_names = _team_names(all_matches)
    out["team_uid"], out["clubs_detail"] = _clubs(squad, team_names)
    out["clubs_detail"] = out["clubs_detail"].fillna("[]")
    out["team"] = out["team_uid"].map(team_names)
    out["team_matches_span"] = _team_matches_span(squad, matches)
    out["availability"] = _div(out["matchday_squads"], out["team_matches_span"])

    known = squad[squad["minutes"].notna()]
    gk = known.groupby("player_uid")
    out["minutes_total"] = gk["minutes"].sum().reindex(out.index).fillna(0.0)
    out["minutes_per_game"] = _div(out["minutes_total"], out["games_played"])
    out["start_rate"] = _div(out["starts"], out["games_played"])

    extra_cols = ["goals_made", "tackle_attempts"]
    for col in schema.PLAYER_MATCH_STAT_COLUMNS + extra_cols:
        out[col] = g[col].sum(min_count=1)
    played = squad[squad["minutes"] > 0]
    for col in PER80_STATS:
        rows = played[played[col].notna()].groupby("player_uid")
        out[f"{col}_per80"] = _div(rows[col].sum().reindex(out.index),
                                   rows["minutes"].sum().reindex(out.index)) * 80
    for col, (num, den) in RATIOS.items():
        out[col] = _div(out[num], out[den])

    min_games, min_minutes = schema.SAMPLE_THRESHOLDS[schema.calibration_profile(competition, season)]
    out["low_sample_size"] = (out["games_played"] < min_games) | (out["minutes_total"] < min_minutes)
    for col in ("age", "height_cm", "weight_kg"):
        out[col] = np.nan

    out = out.reset_index().merge(positions, on="player_uid", how="left")
    dup = out["player"].duplicated(keep=False)
    out["player_label"] = out["player"].where(~dup, out["player"] + " (" + out["team"] + ")")
    out["sport"] = "rugby"
    out["competition"] = competition
    out["season"] = season

    head = ["sport", "season", "player", "team", "competition", "player_uid", "player_label",
            "first_name", "last_name",
            "team_uid", "clubs_detail", "position_group", "position_family", "position_source",
            "secondary_positions", "position_detail", "position_share", "games_played", "starts",
            "matchday_squads", "team_matches_span", "availability", "minutes_total",
            "minutes_per_game", "start_rate", "age", "height_cm", "weight_kg"]
    rest = [c for c in out.columns if c not in head and c != "low_sample_size"]
    out = out[head + rest + ["low_sample_size"]]
    return out.sort_values(["team", "player"]).reset_index(drop=True)


def aggregate_window(seasons: dict[str, dict[str, pd.DataFrame]], competition: str,
                     period: str = "all") -> pd.DataFrame:
    """Une ligne par joueur présent sur au moins une feuille de match de la fenêtre. `seasons` :
    {libellé : tables brutes de la saison}, de la plus ancienne à la plus récente (la dernière est
    la saison choisie). aggregate_season sur les tables mises bout à bout (season = la saison
    choisie), plus :
    - window_label ("2023-24 à 2025-26"), window_start, window_end ;
    - seasons_played : saisons avec au moins un match joué ;
    - season_detail : JSON [[saison, team_uid, nom source, matchs joués, minutes], ...] de ces
      saisons, dans l'ordre chronologique (club principal de la saison, même règle que _clubs) ;
    - season_position_group : poste de la saison choisie (None si absent de cette saison), pour
      signaler sur la carte un poste de fenêtre différent."""
    labels = list(seasons)
    tables = {t: pd.concat([seasons[s][t] for s in labels], ignore_index=True)
              for t in ("matches", "lineups", "player_match")}
    out = aggregate_season(tables, competition, period)
    per_season = {s: aggregate_season(seasons[s], competition, period).set_index("player_uid")
                  for s in labels}
    detail = {uid: [] for uid in out["player_uid"]}
    for s in labels:
        played = per_season[s][per_season[s]["games_played"] > 0]
        for uid, r in played.iterrows():
            detail[uid].append([s, r["team_uid"], r["team"], int(r["games_played"]),
                                int(round(r["minutes_total"]))])
    out["window_label"] = f"{labels[0]} à {labels[-1]}"
    out["window_start"], out["window_end"] = labels[0], labels[-1]
    out["seasons_played"] = out["player_uid"].map(lambda u: len(detail[u])).astype(int)
    out["season_detail"] = out["player_uid"].map(
        lambda u: json.dumps(detail[u], ensure_ascii=False))
    last = per_season[labels[-1]]["position_group"]
    out["season_position_group"] = out["player_uid"].map(last).replace({np.nan: None})
    return out
