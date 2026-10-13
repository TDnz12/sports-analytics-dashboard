"""
Schéma commun du rugby : identifiants, compétitions, saisons, chemins de cache, versions et noms
de colonnes des tables. Aucun calcul ici, aucun appel réseau.

Identifiants : toujours une chaîne "{source}:{id natif}" (icw:122907 pour InCrowd, espn:238367 pour
ESPN), pour les joueurs, les équipes et les matchs. Un identifiant InCrowd et un identifiant ESPN ne
peuvent donc jamais se confondre, même quand les deux nombres sont égaux. Aucun lien entre sources
en V1 : le même joueur en Top 14 et en Six Nations a deux identifiants distincts.

Colonnes : nommées par leur SENS, jamais par le nom du champ source. Exemple : "lineoutsWon"
compte le sauteur chez InCrowd mais le lanceur chez ESPN (vérifié sur des matchs réels), d'où
lineouts_won_jumper d'un côté, lineout_throws / lineout_throws_won de l'autre. Une stat absente
d'une source vaut NaN dans les tables, jamais 0.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..base import PROCESSED_ROOT, RAW_ROOT
from .positions import (
    BACKS, CENTRE, FLANKER, FLY_HALF, FORWARDS, FULLBACK, HOOKER, LOCK, NUMBER_8, PROP,
    SCRUM_HALF, WING,
)

# --- Identifiants ----------------------------------------------------------
SOURCE_INCROWD = "icw"
SOURCE_ESPN = "espn"
SOURCES = (SOURCE_INCROWD, SOURCE_ESPN)


def make_uid(source: str, native_id) -> str:
    """Identifiant interne "{source}:{id natif}". L'id natif doit être un entier (int, entier
    numpy ou chaîne de chiffres) : une valeur comme "122907.0" (id passé par un float pandas à cause
    d'un NaN dans la colonne) ou "nan" lève une erreur plutôt que de créer un identifiant qui ne
    correspondrait à aucun autre."""
    if source not in SOURCES:
        raise ValueError(f"Source inconnue : {source!r} (attendu : {', '.join(SOURCES)})")
    native = str(native_id).strip()
    if not native.isdigit():
        raise ValueError(f"Identifiant natif invalide pour {source} : {native_id!r}")
    return f"{source}:{native}"


def parse_uid(uid: str) -> tuple[str, str]:
    """(source, id natif) d'un identifiant interne ; lève ValueError s'il est mal formé."""
    source, sep, native = str(uid).partition(":")
    if not sep or source not in SOURCES or not native.isdigit():
        raise ValueError(f"Identifiant interne invalide : {uid!r}")
    return source, native


# --- Compétitions et saisons ----------------------------------------------
CLUB = "club"
INTERNATIONAL = "international"


@dataclass(frozen=True)
class CompetitionSpec:
    key: str                  # clé interne, ex "top14"
    label: str                # libellé affiché, ex "Top 14"
    mode: str                 # CLUB ou INTERNATIONAL
    source: str               # SOURCE_INCROWD ou SOURCE_ESPN
    native_id: int            # compId InCrowd ou league ESPN
    season_ids: tuple         # ids natifs de saison, la plus récente en premier
    # Nombre de journées de phase régulière : au-delà, le match est une phase finale. Le champ
    # roundTypeId d'InCrowd n'est pas fiable pour ça (phases finales du Top 14 2021-22 en
    # roundTypeId=1, vérifié au lot 0). None : pas de phase finale (Six Nations).
    regular_rounds: int | None


COMPETITION_SPECS: dict[str, CompetitionSpec] = {
    spec.key: spec for spec in [
        # InCrowd : saison 202401 = 2024-25 (vérifié au lot 0 sur les dates des matchs).
        CompetitionSpec("top14", "Top 14", CLUB, SOURCE_INCROWD, 1002,
                        tuple(range(202501, 202100, -100)), 26),
        CompetitionSpec("prod2", "Pro D2", CLUB, SOURCE_INCROWD, 1013,
                        tuple(range(202501, 202200, -100)), 30),
        CompetitionSpec("six_nations", "Six Nations", INTERNATIONAL, SOURCE_ESPN, 180659,
                        tuple(range(2026, 2009, -1)), None),
    ]
}


def season_label(competition: str, season_id: int) -> str:
    """Libellé affiché d'une saison : "2024-25" pour l'id InCrowd 202401, "2026" pour l'édition
    2026 du Six Nations. Lève ValueError pour une saison hors du périmètre de la compétition."""
    spec = COMPETITION_SPECS[competition]
    if season_id not in spec.season_ids:
        raise ValueError(f"Saison {season_id!r} hors du périmètre de {spec.label}")
    if spec.mode == CLUB:
        year = season_id // 100
        return f"{year}-{str(year + 1)[-2:]}"
    return str(season_id)


def season_labels(competition: str) -> list[str]:
    """Libellés de toutes les saisons de la compétition, la plus récente en premier (même ordre
    que nba.SEASONS)."""
    return [season_label(competition, s) for s in COMPETITION_SPECS[competition].season_ids]


def season_id(competition: str, label: str) -> int:
    """Inverse de season_label."""
    for sid in COMPETITION_SPECS[competition].season_ids:
        if season_label(competition, sid) == label:
            return sid
    raise ValueError(f"Saison {label!r} inconnue pour {COMPETITION_SPECS[competition].label}")


# --- Caches ----------------------------------------------------------------
RUGBY_RAW_DIR = RAW_ROOT / "rugby"
RUGBY_PROCESSED_DIR = PROCESSED_ROOT / "rugby"
# Pas de table de profils InCrowd : profils abandonnés en V1 (décision 11 du plan, environ 60 % de
# 404). Les profils ESPN (Six Nations) seront lus dans le boxscore, au lot 7.

# JSON bruts téléchargés (environ 600 Mo décompressés) : HORS du dépôt, jamais versionnés. Par
# défaut dans le dossier personnel, pas sur le Bureau : le Bureau est synchronisé avec iCloud, qui
# peut évincer des fichiers du disque et bloquer leur lecture. La variable d'environnement
# RUGBY_JSON_DIR permet de les placer ailleurs. Lue à l'appel (pas à l'import) pour rester
# modifiable dans les tests.
DEFAULT_JSON_DIR = Path.home() / "rugby_raw_json"


def json_dir() -> Path:
    return Path(os.environ.get("RUGBY_JSON_DIR", DEFAULT_JSON_DIR))


RAW_TABLES = ("matches", "lineups", "player_match", "events", "team_match")


# Périodes de la table traitée : "all" = saison complète, phases finales incluses (défaut) ;
# "regular" = phase régulière seule. Pas de période "phases finales seules" (5 matchs au plus).
PERIODS = ("all", "regular")


def raw_table_path(competition: str, season: str, table: str, root: Path | None = None) -> Path:
    """data_cache/raw/rugby/<compétition>/<saison>/<table>.parquet ; `season` est le libellé.
    `root` remplace data_cache/ (essais hors du dépôt, ex. scripts/rugby_build.py --out-root)."""
    if table not in RAW_TABLES:
        raise ValueError(f"Table inconnue : {table!r}")
    if season not in season_labels(competition):
        raise ValueError(f"Saison {season!r} inconnue pour {competition}")
    base = RUGBY_RAW_DIR if root is None else Path(root) / "raw" / "rugby"
    return base / competition / season / f"{table}.parquet"


def processed_path(competition: str, season: str, period: str = "all",
                   root: Path | None = None) -> Path:
    """data_cache/processed/rugby/<compétition>/<saison>[_regular].parquet (une ligne par joueur),
    même convention de suffixe que les caches NBA (_playoffs)."""
    if season not in season_labels(competition):
        raise ValueError(f"Saison {season!r} inconnue pour {competition}")
    if period not in PERIODS:
        raise ValueError(f"Période inconnue : {period!r} (attendu : {', '.join(PERIODS)})")
    base = RUGBY_PROCESSED_DIR if root is None else Path(root) / "processed" / "rugby"
    suffix = "" if period == "all" else f"_{period}"
    return base / competition / f"{season}{suffix}.parquet"


# Versions de schéma (même mécanisme que nba.PROCESSED_SCHEMA_VERSION : base.read_cache traite
# un cache d'une autre version comme absent). Chaque montée porte un commentaire "vN : raison".
RUGBY_RAW_TABLES_SCHEMA_VERSION = 1      # les 5 tables de RAW_TABLES, produites ensemble
RUGBY_PROFILES_SCHEMA_VERSION = 1
RUGBY_PROCESSED_SCHEMA_VERSION = 2      # v2 : low_sample_size au seuil club calibré (5 matchs, 520 min)

# --- Seuils et radar (calibration : scripts/rugby_calibrate.py, rugby_notes/calibration_v1.md) ---
# Population de référence du radar et badge "échantillon court" : (matchs joués, minutes).
# Club : 520 min = plus grand seuil qui garde, dans chaque poste et chaque saison (Top 14 et
# Pro D2), au moins 12 joueurs et 70 % des minutes jouées ; au-delà, les piliers (39 min par
# match en médiane) passent sous 70 %. Une fiabilité médiane de 0,6 sur l'ancien socle aurait
# demandé 1 220 min. 5 matchs : sans effet à 520 min (7 matchs au moins), gardé pour le badge.
# International : provisoire, à calibrer au lot 7 avec la même méthode.
SAMPLE_THRESHOLDS = {CLUB: (5, 520), INTERNATIONAL: (2, 120)}

# Pourcentages ajustés ("padding", même formule que la NBA) : (réussis + P x moyenne de
# référence) / (tentatives + P). {mode : {colonne ajustée : (réussis, tentatives, P, tentatives
# minimum sur la saison, référence de la moyenne)}}. Sous le minimum : NaN, "NC" dans le tableau.
# P : split-half en tentatives, un seul P par stat (les P par poste divergent, piste notée après
# la V1). Minimum NC : volume où le joueur pèse 0,2 dans son % ajusté (n = P / 4, arrondi à 5),
# ordre de grandeur des seuils NBA. Référence "position" : moyenne du poste ; "kickers" : tous les
# buteurs qualifiés, sans poste. International : au lot 7.
PADDING_REF_POSITION, PADDING_REF_KICKERS = "position", "kickers"
PCT_PADDING = {
    CLUB: {
        "tackle_pct_adj": ("tackles", "tackle_attempts", 97, 25, PADDING_REF_POSITION),
        "gain_line_pct_adj": ("carries_gain_line", "carries", 82, 20, PADDING_REF_POSITION),
        "goal_kick_pct_adj": ("goals_made", "goal_attempts", 146, 35, PADDING_REF_KICKERS),
    },
}

# Axes du radar club. Règle (décision du 13 octobre 2026) : un axe n'est sur le radar d'un poste
# que si sa fiabilité sur une saison de 520 min atteint 0,4 pour ce poste (calibration_v1.md,
# section 5). Hors radar mais gardés dans le tableau et la fiche joueur : pénalités concédées et
# ballons perdus (par 80, "peu fiable sur une saison"), franchissements, essais (total), % au pied
# (détail réussis / tentatives, % ajusté de PCT_PADDING), % plaquages des arrières.
# {clé : (libellé, colonne affichée, colonne du score ou None, colonne des tentatives ou None)}
RADAR_MIN_RELIABILITY = 0.4
RADAR_AXES_CLUB = {
    "tackles": ("Plaquages", "tackles_per80", None, None),
    "tackle_pct": ("% plaquages", "tackle_pct", "tackle_pct_adj", "tackle_attempts"),
    "metres": ("Mètres", "metres_per80", None, None),
    "gain_line_pct": ("% gain de ligne", "gain_line_pct", "gain_line_pct_adj", "carries"),
    "carries": ("Courses", "carries_per80", None, None),
    "turnovers_won": ("Grattages", "turnovers_won_per80", None, None),
    "defenders_beaten": ("Défenseurs battus", "defenders_beaten_per80", None, None),
    "passes": ("Passes", "passes_per80", None, None),
    "kick_metres": ("Mètres au pied", "kick_metres_per80", None, None),
    "offloads": ("Offloads", "offloads_per80", None, None),
    "lineouts_won_jumper": ("Touches gagnées", "lineouts_won_jumper_per80", None, None),
    "lineout_steals": ("Touches volées", "lineout_steals_per80", None, None),
}
RADAR_SOCLE = ("tackles", "tackle_pct", "metres", "gain_line_pct")
RADAR_FAMILY = {
    FORWARDS: ("carries", "turnovers_won", "defenders_beaten", "passes"),
    BACKS: ("defenders_beaten", "carries", "kick_metres"),
}
# Axes du radar par poste, dans l'ordre d'affichage : socle, famille, spécialités. Une spécialité
# déjà présente dans la famille n'est pas remplacée (3e ligne aile, 3e ligne centre, demis).
RADAR_AXES_BY_POSITION = {
    PROP: RADAR_SOCLE + RADAR_FAMILY[FORWARDS] + ("offloads",),
    HOOKER: RADAR_SOCLE + RADAR_FAMILY[FORWARDS] + ("offloads",),
    LOCK: RADAR_SOCLE + RADAR_FAMILY[FORWARDS] + ("lineouts_won_jumper", "lineout_steals"),
    FLANKER: RADAR_SOCLE + RADAR_FAMILY[FORWARDS] + ("lineouts_won_jumper",),
    NUMBER_8: RADAR_SOCLE + RADAR_FAMILY[FORWARDS] + ("offloads",),
    SCRUM_HALF: RADAR_SOCLE + RADAR_FAMILY[BACKS] + ("passes",),
    FLY_HALF: RADAR_SOCLE + RADAR_FAMILY[BACKS] + ("passes",),
    CENTRE: RADAR_SOCLE + RADAR_FAMILY[BACKS] + ("offloads", "passes"),
    WING: RADAR_SOCLE + RADAR_FAMILY[BACKS] + ("offloads",),
    # % plaquages : fiabilité 0,32 (45 plaquages tentés par saison en médiane).
    FULLBACK: tuple(a for a in RADAR_SOCLE if a != "tackle_pct") + RADAR_FAMILY[BACKS] + ("passes",),
}

# --- Colonnes des tables brutes ----------------------------------------------
# extra_time / duration_min : prolongation (2 x 10 min, phases finales seulement), durée de
# référence du match en minutes (80 ou 100), utilisée par le contrôle des minutes par équipe.
MATCH_COLUMNS = [
    "match_uid", "source", "competition", "season", "season_id", "date_utc", "round", "phase",
    "extra_time", "duration_min",
    "home_team_uid", "home_team", "away_team_uid", "away_team", "home_score", "away_score",
    "status", "coverage_level", "venue",
]
LINEUP_COLUMNS = [
    "match_uid", "team_uid", "player_uid", "player_name", "jersey", "is_starter", "captain",
    "source_position_label",
]
# Stats par joueur et par match, mêmes noms pour les deux sources (NaN si absente de la source).
PLAYER_MATCH_STAT_COLUMNS = [
    "tackles", "missed_tackles", "carries", "carries_gain_line", "metres", "clean_breaks",
    "defenders_beaten", "tries", "try_assists", "passes", "offloads", "turnovers_conceded",
    "turnovers_won", "penalties_conceded", "yellow_cards", "red_cards", "kicks_from_hand",
    "kick_metres", "lineouts_won_jumper", "lineout_steals", "lineout_throws", "lineout_throws_won",
    "conversions_made", "conversions_missed", "penalty_goals_made", "penalty_goals_missed",
    "goal_attempts", "drop_goals_made", "points",
]
# score_source : "source" (stats du joueur telles que fournies) ou "evenements" (essais, buts et
# points recomptés depuis les événements, quand la source a perdu le score de l'équipe-match).
PLAYER_MATCH_COLUMNS = [
    "match_uid", "team_uid", "player_uid", "minutes", "minutes_method", "appeared", "score_source",
] + PLAYER_MATCH_STAT_COLUMNS
EVENT_COLUMNS = [
    "match_uid", "team_uid", "player_uid", "type", "period", "clock_raw_s", "t80_s",
]
# Types d'événements normalisés (les deux sources sont ramenées à cette liste).
EVENT_TYPES = (
    "sub_on", "sub_off", "yellow", "red", "try", "penalty_try", "conversion", "conversion_missed",
    "penalty_goal", "penalty_missed", "drop_goal", "drop_missed", "period_start", "period_end",
)
# Stats par équipe et par match : contrôles de cohérence (points, essais, pénalités manquées) et
# futur classement. scrums_won / scrums_lost : scrumsTotal est vide chez InCrowd.
TEAM_MATCH_COLUMNS = [
    "match_uid", "team_uid", "team", "is_home", "points", "tries", "penalty_tries",
    "conversions_made", "conversions_missed", "penalty_goals_made", "penalty_goals_missed",
    "drop_goals_made", "drop_goals_missed", "goal_attempts", "lineouts_won", "total_lineouts",
    "scrums_won", "scrums_lost", "possession", "territory", "tackles", "missed_tackles", "carries",
    "metres", "penalties_conceded", "turnovers_conceded", "turnovers_won", "yellow_cards",
    "red_cards",
]
PROFILE_COLUMNS = [
    "player_uid", "name", "first_name", "last_name", "date_of_birth", "height_cm", "weight_kg",
    "nationality", "profile_position_label", "fetched_at",
]
