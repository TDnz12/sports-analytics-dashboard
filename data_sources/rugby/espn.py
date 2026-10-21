"""
ESPN (Top 14 2016-17 à 2020-21) : summary + plays d'un match -> les 5 tables brutes du schéma
commun (matches, lineups, player_match, events, team_match). Aucun appel réseau : les JSON ont été
téléchargés par les scripts du pilote (rugby_notes/pilote_espn/, plan_espn.md) dans

    <schema.json_dir()>/espn/<league>/<année ESPN>/events.json.gz      liste des matchs
    <schema.json_dir()>/espn/<league>/<année ESPN>/sum/<match>.json.gz  summary allégé
    <schema.json_dir()>/espn/<league>/<année ESPN>/plays/<match>.json.gz

(année ESPN = année de fin de saison : 2017 pour 2016-17). Summaries allégés : header, rosters et
boxscore seulement ; ni journée, ni stade, ni date de naissance.

Points vérifiés au pilote et au lot 0 (plan_espn.md), appliqués ici :
- aucune minute chez ESPN : minutes reconstruites depuis les plays (minutes.reconstruct_minutes),
  minutes_method = "reconstruit", NaN ("echec") pour un joueur aux événements incohérents ;
- titulaire = maillot 15 ou moins (le champ "starter" d'ESPN n'est pas fiable) ;
- stat absente du summary = NaN, jamais 0 (grattages, gain de ligne, mètres au pied, touches du
  sauteur : jamais fournis) ; lineoutsWon compte le LANCEUR chez ESPN -> lineout_throws_won ;
- pas de buts manqués par joueur : tentatives au but déduites de kickPercentSuccess (voir
  goal_attempts_from_pct) ;
- phase finale = les deux équipes ont déjà joué leurs regular_rounds matchs (assign_phases) ;
  neutralSite vaut false même pour les finales au Stade de France, inutilisable ;
- matchs exclus (audit de couverture, lot A) : liste versionnée espn_exclusions.csv, retirés des
  5 tables ; le rapport du build recalcule les critères et signale tout nouvel écart.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import schema
from .incrowd import mark_appeared, read_json_gz, score_gaps
from .minutes import reconstruct_minutes, t80_seconds, team_minutes_check
from .schema import SOURCE_ESPN, make_uid

# Matchs absents de events.json.gz mais présents chez ESPN (scoreboards par date, lot 0) :
# demi-finales et finale du Top 14 2020-21 (décision 7 de plan_espn.md).
ESPN_EXTRA_EVENTS = {("top14", 2021): (593414, 593415, 593416)}

EXCLUSIONS_CSV = Path(__file__).resolve().parent / "espn_exclusions.csv"

# Stats joueur : colonne du schéma -> stat ESPN du summary. Les colonnes de
# PLAYER_MATCH_STAT_COLUMNS absentes d'ici sont NaN (non fournies) ou calculées (goal_attempts).
PLAYER_STAT_FIELDS = {
    "tackles": "tackles", "missed_tackles": "missedTackles", "carries": "runs", "metres": "metres",
    "clean_breaks": "cleanBreaks", "defenders_beaten": "defendersBeaten", "tries": "tries",
    "try_assists": "tryAssists", "passes": "passes", "offloads": "offload",
    "turnovers_conceded": "turnoversConceded", "penalties_conceded": "penaltiesConceded",
    "yellow_cards": "yellowCards", "red_cards": "redCards", "kicks_from_hand": "kicksFromHand",
    "lineout_throws": "totalLineouts", "lineout_throws_won": "lineoutsWon",
    "conversions_made": "conversionGoals", "penalty_goals_made": "penaltyGoals",
    "drop_goals_made": "dropGoalsConverted", "points": "points",
}

# Stats équipe : colonne du schéma -> stat ESPN du boxscore. points : score du match ;
# penalty_tries, drop_goals_missed : comptés dans les plays ; drop_goals_made : somme des joueurs ;
# goal_attempts : kickPercentSuccess de l'équipe (exact, lui : il compte les échecs des buteurs qui
# ont tout raté, perdus au niveau du joueur ; 364 équipes-matchs sur 367 égales à InCrowd en
# 2022-23).
TEAM_STAT_FIELDS = {
    "tries": "tries", "conversions_made": "conversionGoals", "penalty_goals_made": "penaltyGoals",
    "lineouts_won": "lineoutsWon", "total_lineouts": "totalLineouts", "scrums_won": "scrumsWon",
    "possession": "possession", "territory": "territory", "tackles": "tackles",
    "missed_tackles": "missedTackles", "carries": "runs", "metres": "metres",
    "penalties_conceded": "penaltiesConceded", "turnovers_conceded": "turnoversConceded",
    "yellow_cards": "yellowCards", "red_cards": "redCards",
}

# Types des plays ESPN -> types normalisés (schema.EVENT_TYPES). Liste complète des types vus sur
# les 4 saisons ; un type inconnu lève une erreur plutôt que d'être perdu. "start of half" et
# "end of half" : 2 matchs de 2017-18.
EVENT_TYPE_MAP = {
    "substitute on": "sub_on", "player substituted": "sub_off", "yellow card": "yellow",
    "red card": "red", "try": "try", "penalty try": "penalty_try", "conversion": "conversion",
    "penalty goal": "penalty_goal", "drop goal": "drop_goal", "drop goal-missed": "drop_missed",
    "start of first half": "period_start", "start of second half": "period_start",
    "start of half": "period_start", "end of first half": "period_end",
    "end of second half": "period_end", "end of half": "period_end",
}

# kickPercentSuccess est une fraction arrondie à 2 décimales (0,62 pour 5 sur 8).
_PCT_ROUNDING = 0.005
_MAX_ATTEMPTS = 40


def season_dir(competition: str, season_id: int, json_root: Path | None = None) -> Path:
    root = schema.json_dir() if json_root is None else Path(json_root)
    return root / "espn" / str(schema.source_comp_id(competition, SOURCE_ESPN)) / str(season_id)


def _ref_id(ref: str | None, what: str) -> str | None:
    m = re.search(rf"{what}/(\d+)", ref or "")
    return m.group(1) if m else None


def _stats(items) -> dict:
    """{nom : valeur} d'une liste de stats ESPN ; valeur None (stat présente mais vide) -> NaN.
    Les valeurs négatives sont gardées : ce sont des corrections d'ESPN (transformation retirée
    à un joueur, 2 lignes sur les 4 saisons), sans lesquelles le total de l'équipe serait faux ;
    le rapport du build les liste."""
    return {s["name"]: (np.nan if s.get("value") is None else float(s["value"])) for s in items or []}


def goal_attempts_from_pct(goals_made: float, drops_made: float, pct: float) -> float:
    """Tentatives au but (transformations et pénalités, comme goal_attempts chez InCrowd) d'après
    kickPercentSuccess : nombre entier n de tentatives tel que réussis / n redonne pct à l'arrondi
    près. ESPN compte les drops réussis dans ce pourcentage de 2016-17 à 2020-21 (54 lignes ne
    s'expliquent pas autrement), plus en 2022-23 : drops compris d'abord (n moins les drops
    réussis), sinon buts seuls. Mesuré sur 2022-23 contre InCrowd : 8 552 lignes sur 8 597
    identiques. Aucun n possible : NaN. Rien de réussi et pct = 0 : 0 (joueur qui n'a pas tenté,
    ou buteur qui a tout raté, indiscernables : ajout B de plan_espn.md)."""
    if any(pd.isna(v) for v in (goals_made, drops_made, pct)):
        return np.nan
    if goals_made < 0 or drops_made < 0:      # correction d'ESPN (voir _stats)
        return np.nan
    for made, drops in ((goals_made + drops_made, drops_made), (goals_made, 0.0)):
        if made == 0:
            if pct == 0:
                return 0.0
            continue
        candidates = [n for n in range(int(made), _MAX_ATTEMPTS + 1)
                      if abs(made / n - pct) <= _PCT_ROUNDING + 1e-9]
        if len(candidates) == 1:
            return float(candidates[0] - drops)
    return np.nan


def match_problem(summary: dict | None, plays: dict | None) -> str | None:
    """Raison pour laquelle un match est inutilisable, ou None : summary lisible, match terminé,
    composition des deux équipes, plays lisibles."""
    if not isinstance(summary, dict) or not isinstance(summary.get("header"), dict):
        return "summary absent ou illisible"
    comp = summary["header"]["competitions"][0]
    if (comp.get("status") or {}).get("type", {}).get("completed") is False:
        return "match non terminé"
    rosters = summary.get("rosters") or []
    if len(rosters) != 2 or not all(r.get("roster") for r in rosters):
        return "composition absente"
    if not isinstance(plays, dict) or not isinstance(plays.get("items"), list):
        return "plays absents ou illisibles"
    return None


def extract_match(summary: dict, plays: dict, competition: str) -> dict[str, pd.DataFrame]:
    """Summary + plays d'un match ESPN -> dict {table: DataFrame} aux colonnes du schéma. Phase
    provisoire "regular" (assign_phases la fixe sur la saison entière) ; minutes NaN
    (reconstruites sur la saison par extract_season)."""
    comp = summary["header"]["competitions"][0]
    league = schema.source_comp_id(competition, SOURCE_ESPN)
    # League dans "slug" ("270559") ; "id" est un numéro interne d'ESPN (8005 pour le Top 14).
    if summary["header"]["league"].get("slug") != str(league):
        raise ValueError(f"Match {comp['id']} : league {summary['header']['league'].get('slug')!r} "
                         f"au lieu de {league}")
    season_id = int(summary["header"]["season"]["year"])
    match_uid = make_uid(SOURCE_ESPN, comp["id"])
    items = plays["items"]
    extra = max((p["period"]["number"] for p in items), default=2) > 2
    sides = {c["homeAway"]: c for c in comp["competitors"]}
    home, away = sides["home"], sides["away"]

    match_row = {
        "match_uid": match_uid, "source": SOURCE_ESPN, "competition": competition,
        "season": schema.season_label(competition, season_id), "season_id": season_id,
        "date_utc": pd.Timestamp(comp["date"]), "round": np.nan, "phase": "regular",
        "extra_time": extra, "duration_min": 100 if extra else 80,
        "home_team_uid": make_uid(SOURCE_ESPN, home["team"]["id"]),
        "home_team": home["team"]["displayName"],
        "away_team_uid": make_uid(SOURCE_ESPN, away["team"]["id"]),
        "away_team": away["team"]["displayName"],
        "home_score": int(home["score"]), "away_score": int(away["score"]),
        "status": "result", "coverage_level": np.nan, "venue": None,
    }

    events_rows = []
    for p in items:
        text = p["type"]["text"].lower()
        if text not in EVENT_TYPE_MAP:
            raise ValueError(f"Match {comp['id']} : type de play inconnu {p['type']['text']!r}")
        athletes = [_ref_id(q["athlete"].get("$ref"), "athletes")
                    for q in p.get("participants") or [] if "athlete" in q]
        team_id = _ref_id((p.get("team") or {}).get("$ref"), "teams")
        period, clock = p["period"]["number"], float(p["clock"]["value"])
        events_rows.append({
            "match_uid": match_uid,
            "team_uid": make_uid(SOURCE_ESPN, team_id) if team_id else None,
            "player_uid": make_uid(SOURCE_ESPN, athletes[0]) if athletes and athletes[0] else None,
            "type": EVENT_TYPE_MAP[text], "period": period, "clock_raw_s": clock,
            "t80_s": t80_seconds(period, clock),
        })
    events = pd.DataFrame(events_rows, columns=schema.EVENT_COLUMNS)
    drop_missed = events[events["type"] == "drop_missed"]

    lineup_rows, pm_rows = [], []
    for r in summary["rosters"]:
        team_uid = make_uid(SOURCE_ESPN, r["team"]["id"])
        for x in r["roster"]:
            a = x["athlete"]
            player_uid = make_uid(SOURCE_ESPN, a["id"])
            jersey = int(x["jersey"])
            full, last = a.get("fullName") or a["displayName"], a.get("lastName")
            first = full[:-len(last)].strip() if last and full.endswith(last) else None
            lineup_rows.append({
                "match_uid": match_uid, "team_uid": team_uid, "player_uid": player_uid,
                "player_name": a["displayName"], "first_name": first or None, "last_name": last,
                "jersey": jersey, "is_starter": jersey <= 15, "captain": bool(x.get("captain")),
                "source_position_label": (x.get("position") or {}).get("displayName"),
            })
            s = _stats(x.get("stats"))
            row = {"match_uid": match_uid, "team_uid": team_uid, "player_uid": player_uid,
                   "minutes": np.nan, "minutes_method": "reconstruit", "appeared": False,
                   "score_source": "source"}
            row.update({col: s.get(field, np.nan) for col, field in PLAYER_STAT_FIELDS.items()})
            row["goal_attempts"] = goal_attempts_from_pct(
                row["conversions_made"] + row["penalty_goals_made"], row["drop_goals_made"],
                s.get("kickPercentSuccess", np.nan))
            pm_rows.append(row)

    team_rows = []
    box = {t["team"]["id"]: t for t in summary["boxscore"]["teams"]}
    pen_tries = events[events["type"] == "penalty_try"].groupby("team_uid").size()
    for side, is_home in ((home, True), (away, False)):
        team_id = side["team"]["id"]
        team_uid = make_uid(SOURCE_ESPN, team_id)
        s = _stats(st for block in box[team_id]["statistics"] for st in block["stats"])
        team_row = {"match_uid": match_uid, "team_uid": team_uid,
                    "team": side["team"]["displayName"], "is_home": is_home,
                    "points": float(side["score"]),
                    "penalty_tries": float(pen_tries.get(team_uid, 0))}
        team_row.update({col: s.get(field, np.nan) for col, field in TEAM_STAT_FIELDS.items()})
        team_row["scrums_lost"] = s.get("scrumsTotal", np.nan) - s.get("scrumsWon", np.nan)
        team_row["kick_pct"] = s.get("kickPercentSuccess", np.nan)
        team_rows.append(team_row)
    tm = pd.DataFrame(team_rows)
    # Drops réussis : somme des joueurs (min_count=1 : une colonne toute vide reste vide) ;
    # manqués : plays.
    pm = pd.DataFrame(pm_rows).reindex(columns=schema.PLAYER_MATCH_COLUMNS)
    drops = pm.groupby("team_uid")["drop_goals_made"].sum(min_count=1)
    tm["drop_goals_made"] = tm["team_uid"].map(drops)
    tm["goal_attempts"] = [goal_attempts_from_pct(r.conversions_made + r.penalty_goals_made,
                                                  r.drop_goals_made, r.kick_pct)
                           for r in tm.itertuples()]
    tm = tm.reindex(columns=schema.TEAM_MATCH_COLUMNS)
    tm["drop_goals_missed"] = tm["team_uid"].map(
        drop_missed.groupby("team_uid").size()).fillna(0).astype(float)

    return {
        "matches": pd.DataFrame([match_row], columns=schema.MATCH_COLUMNS),
        "lineups": pd.DataFrame(lineup_rows, columns=schema.LINEUP_COLUMNS),
        "player_match": pm,
        "events": events,
        "team_match": tm,
    }


def read_exclusions(competition: str, season: str, path: Path = EXCLUSIONS_CSV) -> dict[int, str]:
    """{match ESPN : cause} des matchs exclus d'une saison (espn_exclusions.csv)."""
    with open(path, encoding="utf-8", newline="") as f:
        return {int(r["match"]): r["cause"] for r in csv.DictReader(f)
                if r["competition"] == competition and r["season"] == season}


def assign_phases(headers: pd.DataFrame, regular_rounds: int) -> dict[str, str]:
    """{match_uid : "regular" ou "final"} : un match est une phase finale quand ses deux équipes
    ont déjà joué leurs regular_rounds matchs, dans l'ordre des dates. `headers` : tous les matchs
    joués de la saison, exclus compris (un match exclu compte dans le parcours de ses équipes),
    colonnes match_uid, date_utc, home_team_uid, away_team_uid."""
    played: dict[str, int] = {}
    phases = {}
    for r in headers.sort_values(["date_utc", "match_uid"]).itertuples():
        teams = (r.home_team_uid, r.away_team_uid)
        phases[r.match_uid] = ("final" if all(played.get(t, 0) >= regular_rounds for t in teams)
                               else "regular")
        for t in teams:
            played[t] = played.get(t, 0) + 1
    return phases


def _header(summary: dict) -> dict | None:
    """Date et équipes d'un match joué (score non nul, statut terminé), ou None."""
    comp = summary["header"]["competitions"][0]
    if (comp.get("status") or {}).get("type", {}).get("completed") is False:
        return None
    sides = {c["homeAway"]: c for c in comp["competitors"]}
    if int(sides["home"].get("score") or 0) + int(sides["away"].get("score") or 0) == 0:
        return None
    return {"match_uid": make_uid(SOURCE_ESPN, comp["id"]), "date_utc": pd.Timestamp(comp["date"]),
            "home_team_uid": make_uid(SOURCE_ESPN, sides["home"]["team"]["id"]),
            "away_team_uid": make_uid(SOURCE_ESPN, sides["away"]["team"]["id"])}


def season_match_ids(competition: str, season_id: int, json_root: Path | None = None) -> list[int]:
    """Matchs listés dans events.json.gz, plus ESPN_EXTRA_EVENTS."""
    folder = season_dir(competition, season_id, json_root)
    listing = read_json_gz(folder / "events.json.gz")
    if not isinstance(listing, dict) or not isinstance(listing.get("items"), list):
        raise FileNotFoundError(f"Liste des matchs absente ou illisible : {folder / 'events.json.gz'}")
    ids = [int(_ref_id(i["$ref"], "events")) for i in listing["items"]]
    return ids + [e for e in ESPN_EXTRA_EVENTS.get((competition, season_id), ()) if e not in ids]


def extract_season(competition: str, season_id: int, json_root: Path | None = None,
                   exclusions_path: Path = EXCLUSIONS_CSV) -> dict[str, pd.DataFrame]:
    """Toute une saison ESPN : les matchs listés moins les exclus, chacun lu dans son summary et
    ses plays. Un match non exclu absent ou inutilisable lève une erreur qui les liste tous : on ne
    construit jamais une saison incomplète sans le savoir."""
    if season_id not in schema.source_season_ids(competition, SOURCE_ESPN):
        raise ValueError(f"{competition} {season_id} n'est pas une saison ESPN")
    spec = schema.COMPETITION_SPECS[competition]
    label = schema.season_label(competition, season_id)
    folder = season_dir(competition, season_id, json_root)
    excluded = read_exclusions(competition, label, exclusions_path)

    parts: dict[str, list[pd.DataFrame]] = {name: [] for name in schema.RAW_TABLES}
    headers, problems = [], []
    for match_id in season_match_ids(competition, season_id, json_root):
        summary = read_json_gz(folder / "sum" / f"{match_id}.json.gz")
        if isinstance(summary, dict) and isinstance(summary.get("header"), dict):
            header = _header(summary)
            if header:
                headers.append(header)
        if match_id in excluded:
            continue
        plays = read_json_gz(folder / "plays" / f"{match_id}.json.gz")
        problem = match_problem(summary, plays)
        if problem:
            problems.append(f"{match_id} : {problem}")
            continue
        for name, df in extract_match(summary, plays, competition).items():
            parts[name].append(df)
    if problems:
        raise ValueError(f"{len(problems)} match(s) inutilisable(s) dans {folder} (ni valides, ni "
                         f"dans {exclusions_path.name}) :\n  " + "\n  ".join(problems))
    if not parts["matches"]:
        raise ValueError(f"Aucun match utilisable dans {folder}")

    tables = {name: pd.concat(dfs, ignore_index=True) for name, dfs in parts.items()}
    m = tables["matches"]
    if spec.regular_rounds is not None:
        m["phase"] = m["match_uid"].map(assign_phases(pd.DataFrame(headers), spec.regular_rounds))
    order = m.sort_values(["date_utc", "match_uid"])["match_uid"].tolist()
    rank = {uid: i for i, uid in enumerate(order)}
    for name, df in tables.items():
        tables[name] = (df.assign(_o=df["match_uid"].map(rank))
                          .sort_values("_o", kind="stable").drop(columns="_o")
                          .reset_index(drop=True))

    rebuilt = reconstruct_minutes(tables["lineups"], tables["events"], tables["matches"])
    pm = tables["player_match"].drop(columns="minutes").merge(
        rebuilt[["match_uid", "player_uid", "minutes_rebuilt"]].rename(
            columns={"minutes_rebuilt": "minutes"}),
        on=["match_uid", "player_uid"], how="left")
    pm["minutes_method"] = np.where(pm["minutes"].notna(), "reconstruit", "echec")
    tables["player_match"] = pm[schema.PLAYER_MATCH_COLUMNS]
    return mark_appeared(tables)



def coverage_checks(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Critères C3 et C4 de l'audit de couverture (lot A, pilote_espn/audit_couverture.py)
    recalculés sur les tables, par match : c3 (par équipe, plaquages, courses et mètres des joueurs
    non nuls ; score - points des joueurs égal à 0 à 3 essais de pénalité de l'époque), c4
    (minutes.team_minutes_check passé pour les deux équipes), gap_points et gap_minutes (pires
    écarts des deux équipes). Un match valide au lot A passe les deux ; le rapport du build signale
    les autres sans les exclure (espn_exclusions.csv fait foi)."""
    key = ["match_uid", "team_uid"]
    pm, m = tables["player_match"], tables["matches"]
    sums = pm.groupby(key)[["tackles", "carries", "metres"]].sum()
    gaps = score_gaps(tables).set_index(key)
    gap = gaps["score"] - gaps["player_points"]
    unit = gaps["penalty_try_points"]
    team_c3 = (sums.gt(0).all(axis=1).reindex(gaps.index, fill_value=False)
               & ((gap % unit) == 0) & gap.between(0, 3 * unit))
    rebuilt = reconstruct_minutes(tables["lineups"], tables["events"], m)
    check = team_minutes_check(pm, rebuilt, m).set_index(key)
    out = pd.DataFrame({
        "c3": team_c3.groupby(level="match_uid").all(),
        "gap_points": gap.groupby(level="match_uid").agg(lambda s: s.loc[s.abs().idxmax()]),
        "c4": check["ok"].groupby(level="match_uid").all()
              & (check.groupby(level="match_uid").size() == 2),
        "gap_minutes": check["gap_min"].abs().groupby(level="match_uid").max(),
    })
    return out.reindex(m["match_uid"]).reset_index()
