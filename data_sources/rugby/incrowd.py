"""
InCrowd (Top 14, Pro D2) : JSON de détail de match -> les 5 tables brutes du schéma commun
(matches, lineups, player_match, events, team_match). Aucun appel réseau : les JSON sont
téléchargés par scripts/rugby_download.py dans

    <schema.json_dir()>/incrowd/<compId>/<saison>/list.json.gz
    <schema.json_dir()>/incrowd/<compId>/<saison>/<match_id>.json.gz

Points vérifiés au lot 0 et appliqués ici :
- minutesPlayedTotal est en base 80, temps d'exclusion déduit : c'est la source des minutes
  (minutes_method = "source"), sauf en prolongation où il est faux (minutes reconstruites, voir
  use_rebuilt_minutes_in_extra_time) ;
- lineoutsWon compte le SAUTEUR chez InCrowd -> lineouts_won_jumper ;
- les pénalités manquées par joueur ne sont que dans les événements ("Missed penalty") ;
- phase finale = journée au-delà de regular_rounds de la compétition, jamais roundTypeId (les
  phases finales du Top 14 2021-22 sont en roundTypeId=1) ;
- tous les identifiants passent par schema.make_uid ("icw:...").
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import schema
from .minutes import reconstruct_minutes, t80_seconds
from .schema import SOURCE_INCROWD, make_uid

# Stats joueur : colonne du schéma -> champ InCrowd. Les colonnes de PLAYER_MATCH_STAT_COLUMNS
# absentes d'ici sont NaN (try_assists vide côté joueur, lancers en touche inexistants) ou
# calculées (penalty_goals_missed, goal_attempts).
PLAYER_STAT_FIELDS = {
    "tackles": "tackles", "missed_tackles": "missedTackles", "carries": "carries",
    "carries_gain_line": "carriesCrossedGainLine", "metres": "metres",
    "clean_breaks": "cleanBreaks", "defenders_beaten": "defendersBeaten", "tries": "tries",
    "passes": "passes", "offloads": "offload", "turnovers_conceded": "turnoversConceded",
    "turnovers_won": "turnoverWon", "penalties_conceded": "penaltiesConceded",
    "yellow_cards": "yellowCards", "red_cards": "redCards", "kicks_from_hand": "kicksFromHand",
    "kick_metres": "kickFromHandMetres", "lineouts_won_jumper": "lineoutsWon",
    "lineout_steals": "lineoutSteals", "conversions_made": "conversionGoals",
    "conversions_missed": "missedConversionGoals", "penalty_goals_made": "penaltyGoals",
    "drop_goals_made": "dropGoalsConverted", "points": "points",
}

# Stats équipe : colonne du schéma -> champ InCrowd (bloc stats de homeTeam / awayTeam).
TEAM_STAT_FIELDS = {
    "points": "points", "tries": "tries", "penalty_tries": "penaltyTries",
    "conversions_made": "conversionGoals", "conversions_missed": "missedConversionGoals",
    "penalty_goals_made": "penaltyGoals", "penalty_goals_missed": "missedPenaltyGoals",
    "drop_goals_made": "dropGoalsConverted", "drop_goals_missed": "dropGoalMissed",
    "lineouts_won": "lineoutsWon", "total_lineouts": "totalLineouts", "scrums_won": "scrumsWon",
    "scrums_lost": "scrumsLost", "possession": "possession", "territory": "territory",
    "tackles": "tackles", "missed_tackles": "missedTackles", "carries": "carries",
    "metres": "metres", "penalties_conceded": "penaltiesConceded",
    "turnovers_conceded": "turnoversConceded", "turnovers_won": "turnoversWon",
    "yellow_cards": "yellowCards", "red_cards": "redCards",
}

# Types d'événements InCrowd -> types normalisés (schema.EVENT_TYPES). Liste complète des types vus
# sur les 9 saisons téléchargées ; un type inconnu lève une erreur plutôt que d'être perdu.
EVENT_TYPE_MAP = {
    "Sub On": "sub_on", "Sub Off": "sub_off", "Yellow card": "yellow", "Red card": "red",
    "Try": "try", "Penalty Try": "penalty_try", "Conversion": "conversion",
    "Missed conversion": "conversion_missed", "Penalty": "penalty_goal",
    "Missed penalty": "penalty_missed", "Drop goal": "drop_goal",
    "Missed drop goal": "drop_missed", "First Half Start": "period_start",
    "Second Half Start": "period_start", "First Half End": "period_end",
    "Second Half End": "period_end",
}
IGNORED_EVENT_TYPES = {"End"}   # fin du match (période "Post Game"), redondant

# Périodes InCrowd -> numéro (échelle de minutes.PERIOD_BOUNDS_S). "Post Game" : hors temps de jeu.
PERIOD_NUMBERS = {
    "First Half": 1, "Second Half": 2, "First Half Extra Time": 3, "Second Half Extra Time": 4,
    "Post Game": None,
}


def read_json_gz(path: Path) -> dict | None:
    """Contenu d'un JSON compressé, ou None s'il est absent ou illisible (même règle que
    scripts/rugby_download.py, que le paquet ne peut pas importer)."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, EOFError, ValueError):
        return None


def season_dir(competition: str, season_id: int, json_root: Path | None = None) -> Path:
    spec = schema.COMPETITION_SPECS[competition]
    root = schema.json_dir() if json_root is None else Path(json_root)
    return root / "incrowd" / str(spec.native_id) / str(season_id)


def _num(value) -> float:
    return np.nan if value is None else float(value)


def has_extra_time(data: dict) -> bool:
    """Prolongation : score de fin de prolongation renseigné ou événement en période de
    prolongation (finale du Top 14 2024-25, seul cas sur les 9 saisons téléchargées)."""
    if any((data.get(side) or {}).get("extraFTScore") is not None
           for side in ("homeTeam", "awayTeam")):
        return True
    return any("Extra" in (e.get("period") or "") for e in data.get("events") or [])


def extract_match(payload: dict, competition: str) -> dict[str, pd.DataFrame]:
    """Un détail de match InCrowd -> dict {table: DataFrame} aux colonnes du schéma."""
    spec = schema.COMPETITION_SPECS[competition]
    d = payload["data"]
    if d.get("compId") != spec.native_id:
        raise ValueError(f"Match {d.get('id')} : compId {d.get('compId')} au lieu de "
                         f"{spec.native_id} ({spec.label})")
    match_uid = make_uid(SOURCE_INCROWD, d["id"])
    extra = has_extra_time(d)
    home, away = d["homeTeam"], d["awayTeam"]

    match_row = {
        "match_uid": match_uid, "source": SOURCE_INCROWD, "competition": competition,
        "season": schema.season_label(competition, d["season"]), "season_id": d["season"],
        "date_utc": pd.Timestamp(d["date"]), "round": d["round"],
        "phase": "final" if d["round"] > spec.regular_rounds else "regular",
        "extra_time": extra, "duration_min": 100 if extra else 80,
        "home_team_uid": make_uid(SOURCE_INCROWD, home["id"]), "home_team": home["name"],
        "away_team_uid": make_uid(SOURCE_INCROWD, away["id"]), "away_team": away["name"],
        "home_score": home.get("score"), "away_score": away.get("score"),
        "status": d.get("status"), "coverage_level": d.get("coverageLevel"),
        "venue": (d.get("venue") or {}).get("name"),
    }

    events_rows = []
    for e in d.get("events") or []:
        if e["type"] in IGNORED_EVENT_TYPES:
            continue
        if e["type"] not in EVENT_TYPE_MAP:
            raise ValueError(f"Match {d['id']} : type d'événement inconnu {e['type']!r}")
        if e.get("period") not in PERIOD_NUMBERS:
            raise ValueError(f"Match {d['id']} : période inconnue {e.get('period')!r}")
        period = PERIOD_NUMBERS[e["period"]]
        clock = e["minute"] * 60 + e["second"]
        events_rows.append({
            "match_uid": match_uid,
            "team_uid": make_uid(SOURCE_INCROWD, e["teamId"]) if e.get("teamId") else None,
            "player_uid": make_uid(SOURCE_INCROWD, e["playerId"]) if e.get("playerId") else None,
            "type": EVENT_TYPE_MAP[e["type"]], "period": period, "clock_raw_s": float(clock),
            "t80_s": t80_seconds(period, clock),
        })
    events = pd.DataFrame(events_rows, columns=schema.EVENT_COLUMNS)
    missed_pens = events[events["type"] == "penalty_missed"]["player_uid"].value_counts()

    lineup_rows, pm_rows, team_rows = [], [], []
    for side, is_home in ((home, True), (away, False)):
        team_uid = make_uid(SOURCE_INCROWD, side["id"])
        for p in side["players"]:
            player_uid = make_uid(SOURCE_INCROWD, p["id"])
            jersey = int(p["positionId"])
            lineup_rows.append({
                "match_uid": match_uid, "team_uid": team_uid, "player_uid": player_uid,
                "player_name": p.get("known") or p.get("name"), "jersey": jersey,
                "is_starter": jersey <= 15, "captain": bool(p.get("captain")),
                "source_position_label": p.get("position"),
            })
            s = p.get("stats") or {}
            minutes = _num(s.get("minutesPlayedTotal"))
            row = {
                "match_uid": match_uid, "team_uid": team_uid, "player_uid": player_uid,
                "minutes": minutes,
                "minutes_method": "source" if not np.isnan(minutes) else "echec",
                "appeared": bool(minutes > 0) if not np.isnan(minutes) else False,
            }
            row.update({col: _num(s.get(field)) for col, field in PLAYER_STAT_FIELDS.items()})
            row["penalty_goals_missed"] = float(missed_pens.get(player_uid, 0))
            row["goal_attempts"] = (row["conversions_made"] + row["conversions_missed"]
                                    + row["penalty_goals_made"] + row["penalty_goals_missed"])
            pm_rows.append(row)

        ts = side.get("stats") or {}
        team_row = {"match_uid": match_uid, "team_uid": team_uid, "team": side["name"],
                    "is_home": is_home}
        team_row.update({col: _num(ts.get(field)) for col, field in TEAM_STAT_FIELDS.items()})
        team_row["goal_attempts"] = (team_row["conversions_made"] + team_row["conversions_missed"]
                                     + team_row["penalty_goals_made"]
                                     + team_row["penalty_goals_missed"])
        team_rows.append(team_row)

    return {
        "matches": pd.DataFrame([match_row], columns=schema.MATCH_COLUMNS),
        "lineups": pd.DataFrame(lineup_rows, columns=schema.LINEUP_COLUMNS),
        # Colonnes absentes de la source (try_assists, lineout_throws...) créées à NaN.
        "player_match": pd.DataFrame(pm_rows).reindex(columns=schema.PLAYER_MATCH_COLUMNS),
        "events": events,
        "team_match": pd.DataFrame(team_rows, columns=schema.TEAM_MATCH_COLUMNS),
    }


def match_problem(payload: dict | None) -> str | None:
    """Raison pour laquelle un détail est inutilisable, ou None (mêmes critères que le
    téléchargement : lisible, statut "result", composition des deux équipes)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return "JSON absent ou illisible"
    data = payload["data"]
    if data.get("status") != "result":
        return f"statut {data.get('status')!r}"
    for side in ("homeTeam", "awayTeam"):
        if not (data.get(side) or {}).get("players"):
            return f"composition absente ({side})"
    return None


def use_rebuilt_minutes_in_extra_time(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Matchs avec prolongation : minutes reconstruites depuis les événements à la place de
    minutesPlayedTotal (minutes_method = "reconstruit"). Seul cas des 9 saisons, la finale du Top 14
    2024-25 : la source y crédite environ 20 min de trop à des remplaçants et oublie deux jaunes
    (1 557 min pour Bordeaux-Bègles, 1 480 attendues ; reconstruction 1 481). Un joueur aux
    événements incohérents passe à NaN ("echec"), comme pour ESPN."""
    extra = tables["matches"].loc[tables["matches"]["extra_time"], "match_uid"]
    if extra.empty:
        return tables
    lineups = tables["lineups"][tables["lineups"]["match_uid"].isin(extra)]
    rebuilt = reconstruct_minutes(lineups, tables["events"], tables["matches"])
    pm = tables["player_match"].merge(
        rebuilt[["match_uid", "player_uid", "minutes_rebuilt"]], on=["match_uid", "player_uid"],
        how="left")
    mask = pm["match_uid"].isin(extra)
    pm.loc[mask, "minutes"] = pm.loc[mask, "minutes_rebuilt"]
    pm.loc[mask, "minutes_method"] = np.where(pm.loc[mask, "minutes"].notna(), "reconstruit", "echec")
    known = mask & pm["minutes"].notna()
    pm.loc[known, "appeared"] = pm.loc[known, "minutes"] > 0
    return {**tables, "player_match": pm.drop(columns="minutes_rebuilt")}


def extract_season(competition: str, season_id: int,
                   json_root: Path | None = None) -> dict[str, pd.DataFrame]:
    """Toute une saison : les matchs "result" de list.json.gz, chacun lu dans son fichier de
    détail. Un détail absent ou invalide lève une erreur qui les liste tous : on ne construit
    jamais une saison incomplète sans le savoir."""
    if schema.COMPETITION_SPECS[competition].source != SOURCE_INCROWD:
        raise ValueError(f"{competition} n'est pas une compétition InCrowd")
    folder = season_dir(competition, season_id, json_root)
    listing = read_json_gz(folder / "list.json.gz")
    if not isinstance(listing, dict) or not isinstance(listing.get("data"), list):
        raise FileNotFoundError(f"Liste des matchs absente ou illisible : {folder / 'list.json.gz'}")
    match_ids = [m["id"] for m in listing["data"] if m.get("status") == "result"]

    parts: dict[str, list[pd.DataFrame]] = {name: [] for name in schema.RAW_TABLES}
    problems = []
    for match_id in match_ids:
        payload = read_json_gz(folder / f"{match_id}.json.gz")
        problem = match_problem(payload)
        if problem:
            problems.append(f"{match_id} : {problem}")
            continue
        for name, df in extract_match(payload, competition).items():
            parts[name].append(df)
    if problems:
        raise ValueError(f"{len(problems)} détail(s) de match inutilisable(s) dans {folder} :\n  "
                         + "\n  ".join(problems))
    if not match_ids:
        raise ValueError(f"Aucun match au statut result dans {folder / 'list.json.gz'}")

    tables = {name: pd.concat(dfs, ignore_index=True) for name, dfs in parts.items()}
    order = tables["matches"].sort_values(["date_utc", "match_uid"])["match_uid"].tolist()
    rank = {uid: i for i, uid in enumerate(order)}
    for name, df in tables.items():
        tables[name] = (df.assign(_o=df["match_uid"].map(rank))
                          .sort_values("_o", kind="stable").drop(columns="_o")
                          .reset_index(drop=True))
    return use_rebuilt_minutes_in_extra_time(tables)
