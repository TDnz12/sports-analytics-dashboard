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
PROFILES_INCROWD_PATH = RUGBY_RAW_DIR / "profiles_incrowd.parquet"

# JSON bruts téléchargés (environ 600 Mo décompressés) : HORS du dépôt, jamais versionnés. Par
# défaut dans le dossier personnel, pas sur le Bureau : le Bureau est synchronisé avec iCloud, qui
# peut évincer des fichiers du disque et bloquer leur lecture. La variable d'environnement
# RUGBY_JSON_DIR permet de les placer ailleurs. Lue à l'appel (pas à l'import) pour rester
# modifiable dans les tests.
DEFAULT_JSON_DIR = Path.home() / "rugby_raw_json"


def json_dir() -> Path:
    return Path(os.environ.get("RUGBY_JSON_DIR", DEFAULT_JSON_DIR))


RAW_TABLES = ("matches", "lineups", "player_match", "events", "team_match")


def raw_table_path(competition: str, season: str, table: str) -> Path:
    """data_cache/raw/rugby/<compétition>/<saison>/<table>.parquet ; `season` est le libellé."""
    if table not in RAW_TABLES:
        raise ValueError(f"Table inconnue : {table!r}")
    if season not in season_labels(competition):
        raise ValueError(f"Saison {season!r} inconnue pour {competition}")
    return RUGBY_RAW_DIR / competition / season / f"{table}.parquet"


def processed_path(competition: str, season: str) -> Path:
    """data_cache/processed/rugby/<compétition>/<saison>.parquet (une ligne par joueur)."""
    if season not in season_labels(competition):
        raise ValueError(f"Saison {season!r} inconnue pour {competition}")
    return RUGBY_PROCESSED_DIR / competition / f"{season}.parquet"


# Versions de schéma (même mécanisme que nba.PROCESSED_SCHEMA_VERSION : base.read_cache traite
# un cache d'une autre version comme absent). Chaque montée porte un commentaire "vN : raison".
RUGBY_RAW_TABLES_SCHEMA_VERSION = 1      # les 5 tables de RAW_TABLES, produites ensemble
RUGBY_PROFILES_SCHEMA_VERSION = 1
RUGBY_PROCESSED_SCHEMA_VERSION = 1

# --- Colonnes des tables brutes ----------------------------------------------
MATCH_COLUMNS = [
    "match_uid", "source", "competition", "season", "season_id", "date_utc", "round", "phase",
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
PLAYER_MATCH_COLUMNS = [
    "match_uid", "team_uid", "player_uid", "minutes", "minutes_method", "appeared",
] + PLAYER_MATCH_STAT_COLUMNS
EVENT_COLUMNS = [
    "match_uid", "team_uid", "player_uid", "type", "period", "clock_raw_s", "t80_s",
]
# Types d'événements normalisés (les deux sources sont ramenées à cette liste).
EVENT_TYPES = (
    "sub_on", "sub_off", "yellow", "red", "try", "conversion", "conversion_missed",
    "penalty_goal", "penalty_missed", "drop_goal", "drop_missed", "period_start", "period_end",
)
PROFILE_COLUMNS = [
    "player_uid", "name", "first_name", "last_name", "date_of_birth", "height_cm", "weight_kg",
    "nationality", "profile_position_label", "fetched_at",
]
