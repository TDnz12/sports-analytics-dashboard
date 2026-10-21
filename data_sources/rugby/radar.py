"""
Radar de comparaison rugby (pages/1_Radar_de_comparaison.py) : axes, choix des axes selon les postes
comparés, scores, cartes joueur, colonnes hors radar du tableau et notes sous le graph.

- Axes par poste : schema.RADAR_AXES_BY_POSITION (règle des 0,4 de fiabilité, décision 13). Postes
  différents : intersection des axes des postes comparés (décision du 13 octobre 2026, lot 6), donc
  chaque axe affiché est fiable pour tous les joueurs. Pire cas en club sur toutes les combinaisons
  de 1 à 4 postes : 5 axes (ex. Pilier, Ailier et Arrière).
- Scores : moteur commun (radar_common.score_axes), z-score et centile PAR POSTE, référence = joueurs
  d'au moins 5 matchs et 520 minutes (schema.SAMPLE_THRESHOLDS) de la même compétition, saison et
  période. Pourcentages ajustés (padding) de schema.PCT_PADDING, NaN sous le seuil NC.
- Stats par 80 hors radar (tableau) : rapprochées de la moyenne du poste selon les minutes jouées
  (schema.PER80_SHRINK_M), valeur brute entre parenthèses. Le radar lui-même n'utilise que les
  valeurs brutes par 80 (règle des 0,4, décision 13).
- "Indéterminé" (remplaçants 19 à 23 jamais titulaires) : ni axes ni référence, pas de radar
  (radar_eligible = False). Un poste déduit du banc (16 à 18) a un radar comme les autres.
- Mode 3 saisons (window_status, chantier E) : la table est celle de la fenêtre (stats.get_player_stats,
  window=3), donc la référence aussi ; seuils, axes, padding et M inchangés. La carte donne la
  fenêtre, les saisons jouées et une ligne par saison.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import radar_common as rc
from . import schema
from .positions import POSITION_GROUPS, SOURCE_BENCH

# Sous ce nombre d'axes en commun, note sous le radar (le radar reste affiché).
MIN_COMMON_AXES = 5
FEW_AXES_NOTE = ("Ces postes ont peu d'axes en commun : compare plutôt des joueurs de la même "
                 "famille.")
# Sous ce nombre de joueurs de référence d'un poste, avertissement (décision 3).
MIN_REFERENCE_PLAYERS = 10


def _num(value: float, decimals: int = 1) -> str:
    """Nombre au format français (virgule décimale)."""
    return f"{value:.{decimals}f}".replace(".", ",")


def _pct(value: float) -> str:
    return f"{value * 100:.0f} %"


# Textes et axes du radar : réglages du club InCrowd (profil CLUB_ICW), seules saisons publiées
# en club. Ils dépendront du profil de la saison au lot 5 du plan ESPN (saisons ESPN publiées).
_MIN_GAMES, _MIN_MINUTES = schema.SAMPLE_THRESHOLDS[schema.CLUB_ICW]
_PAD = schema.PCT_PADDING[schema.CLUB_ICW]

_HELP = {
    "tackles": "Plaquages réussis par 80 minutes de jeu.",
    "tackle_pct": (
        "Plaquages réussis / plaquages tentés sur la saison. Le score utilise un % ajusté vers la "
        f"moyenne du poste ({_PAD['tackle_pct_adj'][2]} tentatives fictives) ; NC sous "
        f"{_PAD['tackle_pct_adj'][3]} plaquages tentés."),
    "metres": "Mètres gagnés ballon en main par 80 minutes.",
    "gain_line_pct": (
        "Part des courses qui franchissent la ligne d'avantage. Le score utilise un % ajusté vers "
        f"la moyenne du poste ({_PAD['gain_line_pct_adj'][2]} tentatives fictives) ; NC sous "
        f"{_PAD['gain_line_pct_adj'][3]} courses."),
    "carries": "Courses ballon en main par 80 minutes.",
    "turnovers_won": "Ballons récupérés par 80 minutes (grattages, interceptions comprises).",
    "defenders_beaten": "Défenseurs battus par 80 minutes.",
    "passes": "Passes par 80 minutes.",
    "kick_metres": "Mètres gagnés au pied dans le jeu courant, par 80 minutes.",
    "offloads": "Passes après contact par 80 minutes.",
    "lineouts_won_jumper": "Touches gagnées comme sauteur, par 80 minutes.",
    "lineout_steals": "Touches volées sur lancer adverse, par 80 minutes.",
}
# Libellé du volume des pourcentages, pour le survol d'un axe NC.
_ATTEMPTS_LABEL = {"tackle_attempts": "plaquages tentés", "carries": "courses"}


def _axis(key: str) -> dict:
    """Axe au format de nba.RADAR_AXES (key, label, stat_col, fmt, help, score_col,
    attempts_col), plus made_col, min_attempts et attempts_label pour les pourcentages : la page
    affiche alors "84 % (16/19)" et la raison d'un axe NC avec le minimum."""
    label, stat_col, score_col, attempts_col = schema.RADAR_AXES_CLUB[key]
    axis = {"key": key, "label": label, "stat_col": stat_col, "help": _HELP[key], "fmt": _num}
    if score_col is not None:
        made, attempts, _, min_attempts, _ = _PAD[score_col]
        axis.update(score_col=score_col, attempts_col=attempts, made_col=made, fmt=_pct,
                    min_attempts=min_attempts, attempts_label=_ATTEMPTS_LABEL[attempts])
    return axis


RADAR_AXES: list[dict] = [_axis(k) for k in schema.RADAR_AXES_CLUB]
AXES_BY_KEY = {a["key"]: a for a in RADAR_AXES}

RADAR_REFERENCE_CAPTION = (
    "Chaque axe est un z-score par poste (10 postes, du pilier à l'arrière) : chaque joueur est "
    "situé par rapport aux joueurs de référence de son propre poste (au moins "
    f"{_MIN_GAMES} matchs et {_MIN_MINUTES} minutes, même compétition, saison ou fenêtre de 3 "
    "saisons, et période), pas à l'ensemble du championnat. Axes par 80 minutes, sauf les "
    "pourcentages."
)

# Aide du choix "Mode d'affichage" de la page radar.
RADAR_MODE_HELP = (
    "Indice : z-score par poste borné à ±3 écarts-types, mis à l'échelle 0-100 (50 = moyenne du "
    "poste). Centile : rang percentile réel dans la même population (poste, même compétition, "
    f"saison ou fenêtre de 3 saisons, et période, au moins {_MIN_GAMES} matchs et {_MIN_MINUTES} "
    "minutes) ; par exemple, "
    "90 = ce joueur fait mieux que 90 % des joueurs de référence à son poste sur cet axe."
)

RADAR_CAVEATS: list[str] = [
    "Axes retenus : seulement ceux dont la fiabilité sur une saison de "
    f"{_MIN_MINUTES} minutes atteint 0,4 pour le poste. Pénalités concédées, ballons perdus, "
    "franchissements, essais et % au pied restent hors radar, dans le tableau.",
    "Pas de mêlée ni de rucks par joueur : la source ne fournit pas ces stats.",
    "Grattages = ballons récupérés, interceptions comprises.",
    "Par 80 min : total divisé par les minutes jouées, multiplié par 80. Les joueurs qui entrent "
    "souvent en cours de match peuvent être avantagés (jambes fraîches face à une défense "
    "fatiguée).",
    "Stats par 80 hors radar (tableau) : valeur ajustée, rapprochée de la moyenne du poste "
    "d'autant plus que le joueur a peu joué, (total + M x taux moyen du poste par minute) / "
    "(minutes + M) x 80, avec M de 89 à 1 982 minutes selon la stat (calibration) ; valeur brute "
    "entre parenthèses.",
]


def window_status(competition: str, season: str) -> tuple[str | None, str | None]:
    """Mode 3 saisons pour cette compétition et cette saison : (libellé de la fenêtre, None) si elle
    existe ("2023-24 à 2025-26"), sinon (None, phrase d'explication affichée sous le choix grisé)."""
    labels = schema.window_seasons(competition, season)
    if labels:
        return f"{labels[0]} à {labels[-1]}", None
    spec = schema.COMPETITION_SPECS[competition]
    if spec.mode != schema.CLUB:
        return None, "Mode 3 saisons réservé aux compétitions de club (Top 14, Pro D2)."
    published = schema.season_labels(competition)
    first = published[-1]
    window = schema.window_candidates(competition, season)
    start = window[0]
    if start < first:
        return None, (f"Mode 3 saisons indisponible pour {season} : il faudrait les saisons {start} "
                      f"à {season} de la même source, et les données {spec.label} commencent en "
                      f"{first}.")
    missing = [s for s in window if s not in published]
    if missing:
        return None, (f"Mode 3 saisons indisponible pour {season} : la saison "
                      f"{', '.join(missing)} n'est pas couverte par les données {spec.label}.")
    return None, (f"Mode 3 saisons indisponible pour {season} : les saisons {start} à {season} "
                  "viennent de deux sources différentes (ESPN, puis InCrowd), qui ne comptent pas "
                  "les stats de la même façon.")


WINDOW_NOTE = (
    "Mode 3 saisons ({window}) : totaux additionnés sur les 3 saisons puis divisés par les minutes "
    "(jamais une moyenne des saisons) ; joueurs de référence = joueurs du poste sur la même "
    f"fenêtre, au moins {_MIN_GAMES} matchs et {_MIN_MINUTES} minutes au total ; poste et club "
    "principal calculés sur la fenêtre. Mêmes axes qu'en 1 saison."
)


def _shrunk_per80(result: pd.DataFrame, stat: str, m: float) -> pd.Series:
    """Stat par 80 rapprochée de la moyenne du poste : (total + M x taux du poste par minute) /
    (minutes + M) x 80. Le total est celui des matchs à minutes connues (stat par 80 x minutes /
    80, mêmes matchs que minutes_total) ; le taux du poste est la somme des totaux / la somme des
    minutes de tous les joueurs du poste. NaN sans minutes ou sans valeur."""
    per80 = result[f"{stat}_per80"]
    minutes = result["minutes_total"]
    known = per80.notna() & (minutes > 0)
    total = per80 * minutes / 80
    group = result["position_group"]
    rate = total.where(known).groupby(group).sum() / minutes.where(known).groupby(group).sum()
    return ((total + m * group.map(rate)) / (minutes + m) * 80).where(known)


def compute_radar_scores(df: pd.DataFrame, period: str = "all",
                         competition: str = "top14") -> pd.DataFrame:
    """Ajoute à une copie de `df` (get_player_stats) :
    - les pourcentages ajustés de schema.PCT_PADDING (tackle_pct_adj, gain_line_pct_adj,
      goal_kick_pct_adj), NaN sous le seuil NC. Moyenne de référence : celle du poste (toutes les
      lignes du poste), ou celle des buteurs qualifiés (au moins le seuil NC) pour le % au pied ;
    - radar_<key>_z / _score / _percentile pour chaque axe de RADAR_AXES (radar_common.score_axes),
      NaN pour un joueur sans poste ;
    - <stat>_per80_adj pour chaque stat de schema.PER80_SHRINK_M (_shrunk_per80), affichée dans
      le tableau hors radar, jamais sur le radar ;
    - radar_reference (dans la population de référence) et radar_eligible (a un poste).
    `period` est accepté pour l'interface commune : les seuils du rugby ne dépendent pas de la
    période (la table `df` est déjà celle de la période choisie)."""
    seasons = df["season"].dropna().unique() if "season" in df.columns else []
    profile = schema.calibration_profile(competition, seasons[0] if len(seasons) == 1 else None)
    min_games, min_minutes = schema.SAMPLE_THRESHOLDS[profile]
    result = df.copy()
    has_position = result["position_group"].isin(POSITION_GROUPS)
    result["radar_eligible"] = has_position
    result["radar_reference"] = (has_position & (result["games_played"] >= min_games)
                                 & (result["minutes_total"] >= min_minutes))
    for adj, (made, attempts, padding, min_attempts, ref) in schema.PCT_PADDING.get(profile, {}).items():
        qualified = result[attempts] >= min_attempts
        if ref == schema.PADDING_REF_KICKERS:
            group = pd.Series(np.where(qualified, "buteurs", "autres"), index=result.index)
        else:
            group = result["position_group"]
        padded = rc.padded_pct(result.assign(_pad_group=group), made, attempts, padding,
                               group_col="_pad_group")
        result[adj] = padded.where(qualified)
    for stat, m in schema.PER80_SHRINK_M.get(profile, {}).items():
        if f"{stat}_per80" in result.columns:  # absente : pas de valeur ajustée, brute seule
            result[f"{stat}_per80_adj"] = _shrunk_per80(result, stat, m)
    result = rc.score_axes(result, RADAR_AXES, result["radar_reference"])
    for axis in RADAR_AXES:
        for suffix in ("_z", "_score", "_percentile"):
            result.loc[~has_position, f"radar_{axis['key']}{suffix}"] = np.nan
    return result


def _positions(positions) -> list[str]:
    """Postes distincts qui ont des axes, dans l'ordre de sélection des joueurs."""
    return list(dict.fromkeys(p for p in positions if p in schema.RADAR_AXES_BY_POSITION))


def _common_and_removed(groups: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    lists = [schema.RADAR_AXES_BY_POSITION[g] for g in groups]
    common = [k for k in lists[0] if all(k in axes for axes in lists[1:])]
    removed = {g: [k for k in axes if k not in common] for g, axes in zip(groups, lists)}
    return common, {g: keys for g, keys in removed.items() if keys}


def radar_axes_for(positions) -> tuple[list[dict], list[str]]:
    """Axes du radar pour les postes des joueurs comparés (un par joueur, doublons permis) :
    intersection des axes de ces postes, dans l'ordre du poste du premier joueur, et notes à
    afficher sous le radar (axes retirés, peu d'axes en commun)."""
    groups = _positions(positions)
    if not groups:
        return [], []
    common, removed = _common_and_removed(groups)
    notes = []
    if len(groups) > 1:
        notes.append("Postes différents : seuls les axes fiables pour tous ces postes sont "
                     "affichés, et chaque joueur reste situé par rapport à son propre poste.")
    if removed:
        notes.append("Axes retirés, faute d'être fiables pour tous les postes comparés : " + " ; ".join(
            f"{', '.join(AXES_BY_KEY[k]['label'] for k in keys)} ({g})" for g, keys in removed.items()
        ) + ". Leurs valeurs restent dans le tableau.")
    if len(common) < MIN_COMMON_AXES:
        notes.append(FEW_AXES_NOTE)
    return [AXES_BY_KEY[k] for k in common], notes


def radar_notes(df: pd.DataFrame, positions) -> list[str]:
    """Notes qui dépendent des données : effectif de référence de chaque poste affiché
    (avertissement sous MIN_REFERENCE_PLAYERS) et joueurs sans poste non proposés. `df` : sortie de
    compute_radar_scores."""
    notes = []
    groups = _positions(positions)
    if groups:
        counts = df.loc[df["radar_reference"], "position_group"].value_counts()
        parts = []
        for g in groups:
            n = int(counts.get(g, 0))
            parts.append(f"{g} {n} joueurs" + (" (moins de 10 : comparaison fragile)"
                                               if n < MIN_REFERENCE_PLAYERS else ""))
        notes.append("Joueurs de référence : " + ", ".join(parts) + ".")
    if "window_label" in df.columns and len(df):
        notes.append(WINDOW_NOTE.format(window=df["window_label"].iloc[0]))
    n_out = int((~df["radar_eligible"] & (df["games_played"].fillna(0) > 0)).sum())
    if n_out:
        notes.append(f"{n_out} joueurs sans poste déterminé (remplaçants 19 à 23 jamais "
                     "titulaires) ne sont pas proposés : pas de poste, donc pas de référence.")
    return notes


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("s" if n >= 2 else "")


def _goal_kicking(row: pd.Series) -> str:
    """% au pied de la carte : "78 % (52/67)", "NC" sous le seuil, "aucune tentative"."""
    attempts = row.get("goal_attempts")
    if pd.isna(attempts) or attempts == 0:
        return "aucune tentative"
    if attempts < _PAD["goal_kick_pct_adj"][3]:
        return "NC"
    return f"{_pct(row['goal_kick_pct'])} ({row['goals_made']:.0f}/{attempts:.0f})"


def _key_figures(row: pd.Series) -> str:
    """Ligne de chiffres clés de la carte : essais (total), % au pied, cartons."""
    tries = "n.d." if pd.isna(row.get("tries")) else f"{row['tries']:.0f}"
    yellow = int(np.nan_to_num(row.get("yellow_cards", 0)))
    red = int(np.nan_to_num(row.get("red_cards", 0)))
    return (f"Essais : {tries} · % au pied : {_goal_kicking(row)} · "
            f"Cartons : {_plural(yellow, 'jaune')}, {_plural(red, 'rouge')}")


def _window_lines(row: pd.Series) -> list[str]:
    """Carte en mode 3 saisons : saisons jouées (dernière saison si absent de la saison choisie),
    puis une ligne par saison jouée, "2023-24 · Bordeaux-Bègles · 20 matchs · 1324 min"."""
    seasons = row.get("seasons") or []
    played = f"A joué {int(row['seasons_played'])} saison" + ("s" if row["seasons_played"] >= 2 else "")
    played += f" sur {schema.WINDOW_SEASONS}"
    if seasons and seasons[-1][0] != row["season"]:
        played += f" (dernière : {seasons[-1][0]})"
    return [played] + [f"{s} · {club} · {_plural(games, 'match')} · {minutes} min"
                       for s, club, games, minutes in seasons]


def radar_card_lines(row: pd.Series) -> list[str]:
    """Lignes de la carte d'un joueur sous son nom et sa saison (texte brut, échappé par la page).
    En mode 3 saisons (colonne window_label) : poste de la fenêtre signalé s'il diffère de celui
    de la saison choisie, saisons jouées et une ligne par saison à la place des clubs."""
    window = isinstance(row.get("window_label"), str)
    position = row["position_group"]
    if row.get("position_source") == SOURCE_BENCH:
        position += ", poste déduit du maillot de banc"
    if row.get("mixed_position"):
        position += ", poste mixte"
    if isinstance(row.get("secondary_positions"), str) and row["secondary_positions"]:
        position += f" (aussi : {row['secondary_positions']})"
    season_position = row.get("season_position_group")
    if window and isinstance(season_position, str) and season_position != row["position_group"]:
        position += (f" ; poste calculé sur les {schema.WINDOW_SEASONS} saisons ({row['season']} : "
                     f"{season_position})")
    lines = [position]
    if window:
        lines += _window_lines(row)
    elif isinstance(row.get("clubs"), str) and row["clubs"]:
        lines.append(f"Clubs : {row['clubs']}")
    games = int(row["games_played"])
    play = [_plural(int(row["starts"]), "titularisation")]
    if pd.notna(row.get("minutes_per_game")):
        play.append(f"{row['minutes_per_game']:.0f} min par match")
    if pd.notna(row.get("availability")):
        play.append(f"disponibilité {_pct(row['availability'])}")
    lines.append(" · ".join(play))
    lines.append(_key_figures(row))
    if not row["radar_reference"]:
        over = f" sur {schema.WINDOW_SEASONS} saisons" if window else ""
        lines.append(f"Échantillon court{over} : {_plural(games, 'match')}, "
                     f"{row['minutes_total']:.0f} min (hors population de référence)")
    return lines


def _adjusted_per80(row: pd.Series, per80_col: str) -> str:
    """Stat par 80 hors radar : valeur ajustée (_shrunk_per80), brute entre parenthèses,
    "0,6 (brut 0,9)" ; brute seule si la valeur ajustée manque."""
    raw, adj = row.get(per80_col), row.get(f"{per80_col}_adj")
    if pd.isna(raw):
        return "n.d."
    return _num(raw) if pd.isna(adj) else f"{_num(adj)} (brut {_num(raw)})"


def _hors_radar(axis: dict, row: pd.Series) -> str:
    """Valeur d'un axe retiré du radar : stat par 80 ajustée ("0,6 (brut 0,9)") ou pourcentage
    réel avec son ajusté ("84 % (16/19)  ·  ajusté 83 %", ou "  ·  NC")."""
    if "made_col" not in axis:
        return _adjusted_per80(row, axis["stat_col"])
    attempts = row.get(axis["attempts_col"])
    if pd.isna(attempts) or attempts == 0:
        return "aucune tentative"
    text = f"{_pct(row.get(axis['stat_col']))} ({row[axis['made_col']]:.0f}/{attempts:.0f})"
    adj = row.get(axis["score_col"])
    return f"{text}  ·  " + (f"ajusté {_pct(adj)}" if pd.notna(adj) else "NC")


UNRELIABLE = "(ajusté, peu fiable)"
ADJUSTED = "(ajusté)"
_ADJUSTED_HELP = (" Valeur ajustée : rapprochée de la moyenne du poste d'autant plus que le joueur "
                  "a peu joué ; valeur brute entre parenthèses.")


def _extra_label(axis: dict) -> str:
    """En-tête d'un axe retiré dans le tableau : "Grattages (ajusté)", "% plaquages réussis"."""
    return axis["label"] if "made_col" in axis else f"{axis['label']} {ADJUSTED}"


RADAR_EXTRA_HELP = {
    **{_extra_label(a): a["help"] + " Hors radar ici : pas fiable pour tous les postes comparés."
       + ("" if "made_col" in a else _ADJUSTED_HELP) for a in RADAR_AXES},
    "Essais (total)": "Essais marqués sur la saison (total).",
    "Franchissements (total)": "Franchissements de la ligne de défense sur la saison (total).",
    f"Pénalités concédées par 80 min {UNRELIABLE}": (
        "Pénalités concédées par 80 minutes. Peu fiable sur une saison : écarts entre joueurs "
        "surtout dus au hasard." + _ADJUSTED_HELP),
    f"Ballons perdus par 80 min {UNRELIABLE}": (
        "Ballons perdus par 80 minutes. Peu fiable sur une saison : écarts entre joueurs surtout "
        "dus au hasard." + _ADJUSTED_HELP),
    "% au pied": (
        "Transformations et pénalités réussies / tentées, drops exclus. Ajusté vers la moyenne "
        f"des buteurs qualifiés ({_PAD['goal_kick_pct_adj'][2]} tentatives fictives) ; NC sous "
        f"{_PAD['goal_kick_pct_adj'][3]} tentatives."),
    "Cartons (J / R)": "Cartons jaunes et rouges sur la saison.",
}


def radar_extra_columns(row: pd.Series, positions) -> dict[str, str]:
    """Colonnes hors radar du tableau récapitulatif pour un joueur : axes retirés par
    l'intersection des postes comparés (valeur seule, sans score), puis essais, franchissements,
    pénalités concédées et ballons perdus par 80, % au pied et cartons. Stats par 80 ajustées vers
    la moyenne du poste (colonnes <stat>_per80_adj de compute_radar_scores), brute entre
    parenthèses."""
    out = {}
    groups = _positions(positions)
    if groups:
        _, removed = _common_and_removed(groups)
        for key in dict.fromkeys(k for keys in removed.values() for k in keys):
            out[_extra_label(AXES_BY_KEY[key])] = _hors_radar(AXES_BY_KEY[key], row)
    for col, label in (("tries", "Essais (total)"), ("clean_breaks", "Franchissements (total)")):
        out[label] = "n.d." if pd.isna(row.get(col)) else f"{row[col]:.0f}"
    for col, label in (("penalties_conceded_per80", "Pénalités concédées par 80 min"),
                       ("turnovers_conceded_per80", "Ballons perdus par 80 min")):
        out[f"{label} {UNRELIABLE}"] = _adjusted_per80(row, col)
    attempts = row.get("goal_attempts")
    if pd.isna(attempts) or attempts == 0:
        out["% au pied"] = "aucune tentative"
    else:
        kick = f"{_pct(row['goal_kick_pct'])} ({row['goals_made']:.0f}/{attempts:.0f})"
        adj = row.get("goal_kick_pct_adj")
        out["% au pied"] = f"{kick}  ·  " + (f"ajusté {_pct(adj)}" if pd.notna(adj) else "NC")
    out["Cartons (J / R)"] = row.get("cards", "n.d.")
    return out
