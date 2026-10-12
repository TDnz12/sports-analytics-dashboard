"""
Agrégation par saison (plan, 4.3) : tables brutes d'une compétition et d'une saison -> une ligne
par joueur, même contrat que la NBA (COMMON_COLUMNS) plus les colonnes propres au rugby.

- Totaux : sommes sur les matchs de la période ("all" : saison complète, phases finales incluses ;
  "regular" : phase régulière seule). Une stat absente de la source reste NaN (somme min_count=1).
- Par 80 minutes : total / minutes x 80, numérateur et dénominateur sur les MÊMES matchs (ceux où
  les minutes sont connues).
- Pourcentages toujours depuis les sommes, jamais en moyenne de pourcentages par match. Drops
  exclus du % au pied (numérateur et tentatives). Les pourcentages ajustés (padding, NC) sont
  calculés au moment du radar (lot 6), avec les seuils fixés par la calibration.
- Poste : calculé sur la saison complète (positions.py), identique pour les deux périodes.
- Disponibilité : matchs sur la feuille / matchs de son équipe entre son premier et son dernier
  match sur la feuille (somme par club s'il en a changé en cours de saison).
- Âge, taille, poids : NaN en Top 14 et Pro D2 (profils InCrowd abandonnés, décision 11).
"""

from __future__ import annotations

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
    son dernier match sur la feuille avec cette équipe."""
    team_games = pd.concat([
        matches[["home_team_uid", "date_utc"]].set_axis(["team_uid", "date_utc"], axis=1),
        matches[["away_team_uid", "date_utc"]].set_axis(["team_uid", "date_utc"], axis=1),
    ])
    dates_by_team = {t: np.sort(g["date_utc"].values) for t, g in team_games.groupby("team_uid")}
    spans = squad.groupby(["player_uid", "team_uid"])["date_utc"].agg(["min", "max"]).reset_index()
    spans["n"] = [
        int(np.searchsorted(dates_by_team[t], hi, side="right")
            - np.searchsorted(dates_by_team[t], lo, side="left"))
        for t, lo, hi in zip(spans["team_uid"], spans["min"].values, spans["max"].values)
    ]
    return spans.groupby("player_uid")["n"].sum()


def aggregate_season(tables: dict[str, pd.DataFrame], competition: str,
                     period: str = "all") -> pd.DataFrame:
    """Une ligne par joueur présent sur au moins une feuille de match de la période."""
    if period not in schema.PERIODS:
        raise ValueError(f"Période inconnue : {period!r}")
    spec = schema.COMPETITION_SPECS[competition]
    all_matches = tables["matches"]
    positions = assign_positions(tables["lineups"], tables["player_match"], all_matches)

    matches = all_matches if period == "all" else all_matches[all_matches["phase"] == "regular"]
    keep = set(matches["match_uid"])
    squad = (tables["lineups"][tables["lineups"]["match_uid"].isin(keep)]
             .merge(tables["player_match"], on=["match_uid", "team_uid", "player_uid"], how="left")
             .merge(matches[["match_uid", "date_utc"]], on="match_uid", how="left"))
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
    out["team_uid"] = last["team_uid"]
    out["team"] = out["team_uid"].map(_team_names(all_matches))
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
    for col in PER80_STATS:
        num = gk[col].sum(min_count=1).reindex(out.index)
        out[f"{col}_per80"] = _div(num, out["minutes_total"]) * 80
    for col, (num, den) in RATIOS.items():
        out[col] = _div(out[num], out[den])

    min_games, min_minutes = schema.SAMPLE_THRESHOLDS[spec.mode]
    out["low_sample_size"] = (out["games_played"] < min_games) | (out["minutes_total"] < min_minutes)
    for col in ("age", "height_cm", "weight_kg"):
        out[col] = np.nan

    out = out.reset_index().merge(positions, on="player_uid", how="left")
    dup = out["player"].duplicated(keep=False)
    out["player_label"] = out["player"].where(~dup, out["player"] + " (" + out["team"] + ")")
    out["sport"] = "rugby"
    out["competition"] = competition
    out["season"] = all_matches["season"].iloc[0]

    head = ["sport", "season", "player", "team", "competition", "player_uid", "player_label",
            "team_uid", "position_group", "position_family", "position_source",
            "secondary_positions", "position_detail", "games_played", "starts",
            "matchday_squads", "team_matches_span", "availability", "minutes_total",
            "minutes_per_game", "start_rate", "age", "height_cm", "weight_kg"]
    rest = [c for c in out.columns if c not in head and c != "low_sample_size"]
    out = out[head + rest + ["low_sample_size"]]
    return out.sort_values(["team", "player"]).reset_index(drop=True)
