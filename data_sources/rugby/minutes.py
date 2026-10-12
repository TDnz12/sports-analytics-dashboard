"""
Minutes jouées reconstruites depuis les événements (remplacements, cartons), commun aux deux
sources : les événements arrivent déjà normalisés (schema.EVENT_COLUMNS), période en nombre.

Échelle de temps "t80" (secondes, sans arrêts de jeu) : 0 à 4 800 s pour le temps réglementaire,
4 800 à 6 000 s pour une prolongation (2 x 10 min, phases finales). Les horloges des sources sont
réelles, arrêts de jeu compris (InCrowd et ESPN font repartir la 2e mi-temps à 40:00) : un
événement est ramené dans les bornes de sa période (un remplacement à 42:30 de la 1re mi-temps
compte à 40:00).

Usage :
- ESPN (lot 7) : seule source des minutes ;
- InCrowd (lot 3) : minutesPlayedTotal fait foi, la reconstruction sert de validation croisée
  (mesure de la fiabilité de la méthode avant de l'appliquer à ESPN).

Règles (plan, 4.1) : les maillots 1 à 15 entrent à 0 ; chaque sortie ferme le passage en cours,
chaque entrée en ouvre un (retours après protocole commotion ou saignement gérés) ; un passage
encore ouvert se ferme à la fin du match. Jaune : absence sur [t, t + 10 min], seule
l'intersection avec ses passages est retirée (pas de double déduction s'il est remplacé pendant
l'exclusion). Rouge : le passage se ferme à t. Événements incohérents (entrée d'un joueur déjà sur
le terrain, sortie d'un joueur qui n'y est pas) : minutes NaN pour ce joueur et ce match.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

# Bornes de chaque période sur l'échelle t80, en secondes. 3 et 4 : prolongation.
PERIOD_BOUNDS_S = {1: (0, 2400), 2: (2400, 4800), 3: (4800, 5400), 4: (5400, 6000)}
YELLOW_S = 600
REGULATION_S = 4800
EXTRA_TIME_S = 6000
# Tolérance du contrôle des minutes par équipe et par match (5 min, 2 au plan) : les arrondis de
# 23 joueurs s'additionnent et InCrowd décompte parfois un jaune en temps réel (environ 12 min) ;
# avec 2 min, 25 équipes-matchs sur 374 du Top 14 2025-26 sortaient sans anomalie réelle.
TEAM_TOLERANCE_MIN = 5.0


def t80_seconds(period, clock_s) -> float:
    """Horloge réelle de la source -> échelle t80. NaN pour un événement hors période (avant-match,
    après-match) ou sans horloge."""
    if period is None or clock_s is None or (isinstance(period, float) and math.isnan(period)):
        return np.nan
    bounds = PERIOD_BOUNDS_S.get(int(period))
    if bounds is None or (isinstance(clock_s, float) and math.isnan(clock_s)):
        return np.nan
    lo, hi = bounds
    return float(min(max(clock_s, lo), hi))


def _overlap(intervals: list[tuple[float, float]], lo: float, hi: float) -> float:
    return sum(max(0.0, min(b, hi) - max(a, lo)) for a, b in intervals)


def _union(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def player_minutes(starter: bool, events: list[tuple[float, str]], end_s: float) -> dict:
    """Minutes d'un joueur sur un match. `events` : ses événements (t80, type), types utiles
    sub_on, sub_off, yellow, red (les autres sont ignorés). Renvoie :
    - minutes : temps sur le terrain moins exclusions, en minutes arrondies (NaN si incohérent) ;
    - team_excluded_s : temps pendant lequel son équipe a joué à un de moins à cause de ses
      cartons (jaune : 10 min entières même s'il est remplacé pendant l'exclusion ; rouge :
      jusqu'à la fin, ou jusqu'à sa "sortie" notée après le rouge : rouge de 20 minutes, où un
      remplaçant entre au bout de 20 min, vu en Top 14 2025-26 et jamais avant), compté seulement
      pour un carton reçu sur le terrain."""
    events = sorted((t, typ) for t, typ in events if not math.isnan(t))
    stints: list[tuple[float, float]] = []
    start = 0.0 if starter else None
    sent_off = False
    yellows: list[float] = []
    reds: list[list[float]] = []      # [début, fin] de l'infériorité numérique
    incoherent = False
    for t, typ in events:
        if typ == "sub_on":
            if start is not None or sent_off:
                incoherent = True
                break
            start = t
        elif typ == "sub_off":
            if start is None:
                if sent_off:      # rouge de 20 minutes : un remplaçant entre à sa place
                    if reds and reds[-1][1] == end_s:
                        reds[-1][1] = max(t, reds[-1][0])
                    continue
                incoherent = True
                break
            stints.append((start, t))
            start = None
        elif typ == "yellow":
            if start is not None:
                yellows.append(t)
        elif typ == "red":
            if start is not None:
                stints.append((start, t))
                start = None
                reds.append([t, end_s])
            sent_off = True
    if start is not None and not incoherent:
        stints.append((start, end_s))

    excluded = _union([(t, min(t + YELLOW_S, end_s)) for t in yellows] + [tuple(r) for r in reds])
    team_excluded_s = sum(b - a for a, b in excluded)
    if incoherent:
        return {"minutes": np.nan, "team_excluded_s": team_excluded_s}
    yellow_windows = _union([(t, min(t + YELLOW_S, end_s)) for t in yellows])
    on_field = sum(b - a for a, b in stints) - sum(_overlap(stints, a, b) for a, b in yellow_windows)
    return {"minutes": float(round(on_field / 60)), "team_excluded_s": team_excluded_s}


def reconstruct_minutes(lineups: pd.DataFrame, events: pd.DataFrame,
                        matches: pd.DataFrame) -> pd.DataFrame:
    """Minutes reconstruites pour toutes les lignes de `lineups` (un ou plusieurs matchs).
    `matches` donne la durée de chaque match (duration_min, 80 ou 100). Colonnes renvoyées :
    match_uid, team_uid, player_uid, minutes_rebuilt, team_excluded_s."""
    end_by_match = (matches.set_index("match_uid")["duration_min"] * 60).to_dict()
    useful = events[events["type"].isin(["sub_on", "sub_off", "yellow", "red"])
                    & events["player_uid"].notna()]
    by_player = {key: list(zip(g["t80_s"], g["type"]))
                 for key, g in useful.groupby(["match_uid", "player_uid"], sort=False)}
    rows = []
    for r in lineups[["match_uid", "team_uid", "player_uid", "is_starter"]].itertuples(index=False):
        res = player_minutes(bool(r.is_starter), by_player.get((r.match_uid, r.player_uid), []),
                             end_by_match[r.match_uid])
        rows.append((r.match_uid, r.team_uid, r.player_uid, res["minutes"], res["team_excluded_s"]))
    return pd.DataFrame(rows, columns=["match_uid", "team_uid", "player_uid", "minutes_rebuilt",
                                       "team_excluded_s"])


def team_minutes_check(player_match: pd.DataFrame, rebuilt: pd.DataFrame, matches: pd.DataFrame,
                       tolerance_min: float = TEAM_TOLERANCE_MIN) -> pd.DataFrame:
    """Contrôle par équipe et par match : somme des minutes des joueurs comparée à
    15 x durée réelle du match (80 ou 100 min) moins le temps d'exclusion de l'équipe (cartons,
    d'après les événements). `rebuilt` : sortie de reconstruct_minutes (pour team_excluded_s)."""
    sums = player_match.groupby(["match_uid", "team_uid"], as_index=False)["minutes"].sum(min_count=1)
    excl = rebuilt.groupby(["match_uid", "team_uid"], as_index=False)["team_excluded_s"].sum()
    out = sums.merge(excl, on=["match_uid", "team_uid"], how="left").merge(
        matches[["match_uid", "duration_min", "extra_time"]], on="match_uid", how="left")
    out["exclusion_min"] = out["team_excluded_s"].fillna(0) / 60
    out["expected_min"] = 15 * out["duration_min"] - out["exclusion_min"]
    out["gap_min"] = out["minutes"] - out["expected_min"]
    out["ok"] = out["gap_min"].abs() <= tolerance_min
    return out.drop(columns="team_excluded_s").rename(columns={"minutes": "minutes_sum"})
