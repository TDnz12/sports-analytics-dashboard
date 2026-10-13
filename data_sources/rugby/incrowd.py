"""
InCrowd (Top 14, Pro D2) : JSON de détail de match -> les 5 tables brutes du schéma commun
(matches, lineups, player_match, events, team_match). Aucun appel réseau : les JSON sont
téléchargés par scripts/rugby_download.py dans

    <schema.json_dir()>/incrowd/<compId>/<saison>/list.json.gz
    <schema.json_dir()>/incrowd/<compId>/<saison>/<match_id>.json.gz

Points vérifiés au lot 0 et appliqués ici :
- minutesPlayedTotal est en base 80, temps d'exclusion déduit : c'est la source des minutes
  (minutes_method = "source"), sauf en prolongation et quand sa somme par équipe est fausse alors
  que la reconstruction est juste (minutes reconstruites, voir choose_team_minutes) ;
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
from .minutes import reconstruct_minutes, t80_seconds, team_minutes_check
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
                "player_name": p.get("known") or p.get("name"),
                "first_name": p.get("firstName"), "last_name": p.get("lastName"), "jersey": jersey,
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
                "score_source": "source",
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


def choose_team_minutes(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Par équipe et par match, source des minutes retenue. Colonnes : match_uid, team_uid,
    extra_time, source_ok, rebuilt_ok (somme dans la tolérance, aucun joueur incohérent),
    use_rebuilt. Minutes reconstruites retenues :
    - toujours en prolongation : minutesPlayedTotal y est faux (finale du Top 14 2024-25 : environ
      20 min de trop à des remplaçants, deux jaunes oubliés, 1 557 min pour Bordeaux-Bègles,
      1 480 attendues ; reconstruction 1 481) ;
    - sinon quand la somme source sort de la tolérance ET que la reconstruction y rentre (minutes
      gonflées de Valence-Romans en Pro D2 2025-26, par exemple). Les deux hors tolérance : la
      source est gardée, et le rapport de contrôle le signale."""
    m, pm = tables["matches"], tables["player_match"]
    rebuilt = reconstruct_minutes(tables["lineups"], tables["events"], m)
    key = ["match_uid", "team_uid"]
    source = team_minutes_check(pm, rebuilt, m)
    rebuilt_check = team_minutes_check(rebuilt.rename(columns={"minutes_rebuilt": "minutes"}),
                                       rebuilt, m)
    incomplete = rebuilt["minutes_rebuilt"].isna().groupby([rebuilt[k] for k in key]).any()
    out = (source[key + ["extra_time", "ok"]].rename(columns={"ok": "source_ok"})
           .merge(rebuilt_check[key + ["ok"]].rename(columns={"ok": "rebuilt_ok"}), on=key)
           .merge(incomplete.rename("incomplete").reset_index(), on=key))
    out["rebuilt_ok"] = out["rebuilt_ok"] & ~out["incomplete"]
    out["use_rebuilt"] = out["extra_time"] | (~out["source_ok"] & out["rebuilt_ok"])
    return out.drop(columns="incomplete")


def use_rebuilt_minutes_where_better(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Remplace minutesPlayedTotal par les minutes reconstruites (minutes_method = "reconstruit")
    pour les équipes-matchs retenues par choose_team_minutes. Un joueur aux événements incohérents
    (possible seulement en prolongation) passe à NaN ("echec"), comme pour ESPN."""
    choice = choose_team_minutes(tables)
    chosen = choice.loc[choice["use_rebuilt"], ["match_uid", "team_uid"]]
    if chosen.empty:
        return tables
    key = ["match_uid", "team_uid"]
    rebuilt = reconstruct_minutes(tables["lineups"].merge(chosen, on=key), tables["events"],
                                  tables["matches"])
    pm = tables["player_match"].merge(rebuilt[key + ["player_uid", "minutes_rebuilt"]],
                                      on=key + ["player_uid"], how="left", indicator=True)
    mask = pm.pop("_merge") == "both"
    pm.loc[mask, "minutes"] = pm.loc[mask, "minutes_rebuilt"]
    pm.loc[mask, "minutes_method"] = np.where(pm.loc[mask, "minutes"].notna(), "reconstruit", "echec")
    known = mask & pm["minutes"].notna()
    pm.loc[known, "appeared"] = pm.loc[known, "minutes"] > 0
    return {**tables, "player_match": pm.drop(columns="minutes_rebuilt")}


# Points par action de score. L'essai de pénalité (7 points) revient à l'équipe, jamais à un joueur
# (vérifié : points des joueurs + 7 x essais de pénalité = score).
SCORE_POINTS = {"try": 5, "conversion": 2, "penalty_goal": 3, "drop_goal": 3}
SCORE_COLUMNS = {"try": "tries", "conversion": "conversions_made",
                 "penalty_goal": "penalty_goals_made", "drop_goal": "drop_goals_made"}
PENALTY_TRY_POINTS = 7


def official_scores(matches: pd.DataFrame) -> pd.DataFrame:
    """Score officiel de chaque équipe-match : match_uid, team_uid, score."""
    return pd.concat([
        matches[["match_uid", "home_team_uid", "home_score"]].set_axis(
            ["match_uid", "team_uid", "score"], axis=1),
        matches[["match_uid", "away_team_uid", "away_score"]].set_axis(
            ["match_uid", "team_uid", "score"], axis=1),
    ], ignore_index=True)


def score_gaps(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Par équipe-match : score officiel, points des joueurs, essais de pénalité (événements) et
    écart = score - (points des joueurs + 7 x essais de pénalité)."""
    key = ["match_uid", "team_uid"]
    ev = tables["events"]
    pt = ev[ev["type"] == "penalty_try"].groupby(key).size().rename("penalty_tries")
    players = tables["player_match"].groupby(key)["points"].sum().rename("player_points")
    out = (official_scores(tables["matches"]).merge(players.reset_index(), on=key, how="left")
           .merge(pt.reset_index(), on=key, how="left"))
    out["penalty_tries"] = out["penalty_tries"].fillna(0)
    out["gap"] = out["score"] - out["player_points"] - PENALTY_TRY_POINTS * out["penalty_tries"]
    return out


def rebuild_scoring_from_events(tables: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame],
                                                                           pd.DataFrame]:
    """Équipes-matchs où la source a perdu une partie du score (points des joueurs + 7 x essais de
    pénalité différents du score officiel ; 16 cas sur les 9 saisons, surtout en Pro D2 2023-24 et
    2024-25, où les essais et buts manquent aussi dans les stats de l'équipe alors que les
    événements sont complets) : essais, transformations, pénalités réussies, drops et points de
    chaque joueur recomptés depuis les événements (score_source = "evenements"), goal_attempts
    recalculé. Les autres stats ne changent pas. Appliqué seulement si le recomptage redonne
    EXACTEMENT le score officiel ; sinon la source est gardée. Renvoie (tables, bilan par
    équipe-match en écart : colonnes de score_gaps + recount_points, applied)."""
    key = ["match_uid", "team_uid"]
    gaps = score_gaps(tables)
    todo = gaps[gaps["gap"] != 0].copy()
    if todo.empty:
        return tables, todo.assign(recount_points=pd.Series(dtype=float),
                                   applied=pd.Series(dtype=bool))
    ev = tables["events"]
    # Seuls les événements de joueurs présents sur la feuille de leur équipe comptent : un point
    # attribué à personne fait échouer le contrôle du score, et la source est alors gardée.
    on_sheet = tables["lineups"][key + ["player_uid"]].merge(todo[key], on=key)
    scoring = ev[ev["type"].isin(list(SCORE_POINTS))].merge(on_sheet, on=key + ["player_uid"])
    if scoring.empty:
        counts = pd.DataFrame(columns=list(SCORE_POINTS), dtype=float,
                              index=pd.MultiIndex.from_arrays([[], [], []],
                                                              names=key + ["player_uid"]))
    else:
        counts = (scoring.groupby(key + ["player_uid", "type"]).size().unstack("type", fill_value=0)
                  .reindex(columns=list(SCORE_POINTS), fill_value=0))
    counts["points"] = sum(counts[t] * p for t, p in SCORE_POINTS.items())
    recount = counts.groupby(level=key)["points"].sum().rename("recount_points").reset_index()
    todo = todo.merge(recount, on=key, how="left")
    todo["recount_points"] = todo["recount_points"].fillna(0)
    todo["applied"] = (todo["recount_points"] + PENALTY_TRY_POINTS * todo["penalty_tries"]
                       == todo["score"])
    applied = todo.loc[todo["applied"], key]
    if applied.empty:
        return tables, todo

    pm = tables["player_match"].merge(applied.assign(_fix=True), on=key, how="left")
    fix = pm.pop("_fix").notna()
    new = (counts.rename(columns=SCORE_COLUMNS).reset_index()
           .merge(applied, on=key)[key + ["player_uid"] + list(SCORE_COLUMNS.values()) + ["points"]])
    pm = pm.merge(new, on=key + ["player_uid"], how="left", suffixes=("", "_ev"))
    for col in list(SCORE_COLUMNS.values()) + ["points"]:
        pm.loc[fix, col] = pm.loc[fix, f"{col}_ev"].fillna(0)
        pm = pm.drop(columns=f"{col}_ev")
    pm.loc[fix, "goal_attempts"] = (pm.loc[fix, "conversions_made"] + pm.loc[fix, "conversions_missed"]
                                    + pm.loc[fix, "penalty_goals_made"]
                                    + pm.loc[fix, "penalty_goals_missed"])
    pm.loc[fix, "score_source"] = "evenements"
    return {**tables, "player_match": pm[schema.PLAYER_MATCH_COLUMNS]}, todo


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
    tables = use_rebuilt_minutes_where_better(tables)
    return rebuild_scoring_from_events(tables)[0]
