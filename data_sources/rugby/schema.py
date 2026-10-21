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
class SeasonSource:
    """Une saison d'une compétition et la source qui la fournit (« une saison = une source »,
    plan_espn.md) : une compétition peut changer de source d'une saison à l'autre (Top 14 : ESPN
    jusqu'en 2020-21, InCrowd ensuite), jamais à l'intérieur d'une saison."""
    label: str                # libellé affiché, ex "2024-25" ou "2026"
    source: str               # SOURCE_INCROWD ou SOURCE_ESPN
    native_comp_id: int       # compId InCrowd ou league ESPN
    season_id: int            # id natif de la saison chez la source
    # False : saison déclarée (construction des caches possible) mais pas encore proposée dans
    # l'appli ni dans les fenêtres de 3 saisons.
    published: bool = True


@dataclass(frozen=True)
class CompetitionSpec:
    key: str                  # clé interne, ex "top14"
    label: str                # libellé affiché, ex "Top 14"
    mode: str                 # CLUB ou INTERNATIONAL
    seasons: tuple            # SeasonSource, la plus récente en premier
    # Nombre de journées de phase régulière : au-delà, le match est une phase finale. Le champ
    # roundTypeId d'InCrowd n'est pas fiable pour ça (phases finales du Top 14 2021-22 en
    # roundTypeId=1, vérifié au lot 0). None : pas de phase finale (Six Nations).
    regular_rounds: int | None


def _club_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _incrowd_club(comp_id: int, first_year: int, last_year: int) -> tuple:
    """Saisons InCrowd d'un club, de last_year à first_year (années de début) : saison 202401 =
    2024-25 (vérifié au lot 0 sur les dates des matchs)."""
    return tuple(SeasonSource(_club_label(y), SOURCE_INCROWD, comp_id, y * 100 + 1)
                 for y in range(last_year, first_year - 1, -1))


def _espn_club(league: int, start_years: tuple, published: bool) -> tuple:
    """Saisons ESPN d'un club : ESPN numérote une saison par son année de fin (2017 = 2016-17)."""
    return tuple(SeasonSource(_club_label(y), SOURCE_ESPN, league, y + 1, published)
                 for y in start_years)


COMPETITION_SPECS: dict[str, CompetitionSpec] = {
    spec.key: spec for spec in [
        # Top 14 ESPN (league 270559) : 4 saisons acceptées par l'audit de couverture (lot A,
        # plan_v1_rugby.md section J) ; 2019-20 refusée (saison arrêtée). Non publiées jusqu'au
        # lot 5 du plan ESPN.
        CompetitionSpec("top14", "Top 14", CLUB,
                        _incrowd_club(1002, 2021, 2025)
                        + _espn_club(270559, (2020, 2018, 2017, 2016), published=False), 26),
        CompetitionSpec("prod2", "Pro D2", CLUB, _incrowd_club(1013, 2022, 2025), 30),
        CompetitionSpec("six_nations", "Six Nations", INTERNATIONAL,
                        tuple(SeasonSource(str(y), SOURCE_ESPN, 180659, y)
                              for y in range(2026, 2009, -1)), None),
    ]
}


def _seasons(competition: str, published_only: bool) -> tuple:
    seasons = COMPETITION_SPECS[competition].seasons
    return tuple(s for s in seasons if s.published) if published_only else seasons


def season_source(competition: str, label: str) -> SeasonSource:
    """Saison (publiée ou non) de libellé `label` ; ValueError si inconnue."""
    for s in COMPETITION_SPECS[competition].seasons:
        if s.label == label:
            return s
    raise ValueError(f"Saison {label!r} inconnue pour {COMPETITION_SPECS[competition].label}")


def season_label(competition: str, season_id: int) -> str:
    """Libellé affiché d'une saison d'après son id natif : "2024-25" pour l'id InCrowd 202401,
    "2016-17" pour l'id ESPN 2017 du Top 14, "2026" pour l'édition 2026 du Six Nations. Lève
    ValueError pour une saison hors du périmètre de la compétition."""
    for s in COMPETITION_SPECS[competition].seasons:
        if s.season_id == season_id:
            return s.label
    raise ValueError(f"Saison {season_id!r} hors du périmètre de {COMPETITION_SPECS[competition].label}")


def season_labels(competition: str, published_only: bool = True) -> list[str]:
    """Libellés des saisons de la compétition, la plus récente en premier (même ordre que
    nba.SEASONS). Par défaut les saisons publiées seulement (appli, fenêtres, contrôles des
    caches) ; published_only=False pour toutes les saisons déclarées (construction des caches)."""
    return [s.label for s in _seasons(competition, published_only)]


def season_id(competition: str, label: str) -> int:
    """Inverse de season_label."""
    return season_source(competition, label).season_id


def source_season_ids(competition: str, source: str) -> list[int]:
    """Ids natifs des saisons fournies par `source` (publiées ou non), la plus récente en premier."""
    return [s.season_id for s in COMPETITION_SPECS[competition].seasons if s.source == source]


def source_comp_id(competition: str, source: str) -> int:
    """Id de la compétition chez `source` (compId InCrowd, league ESPN)."""
    ids = {s.native_comp_id for s in COMPETITION_SPECS[competition].seasons if s.source == source}
    if len(ids) != 1:
        raise ValueError(f"{COMPETITION_SPECS[competition].label} : pas d'id unique chez {source}")
    return ids.pop()


def competitions_with_source(source: str) -> list[str]:
    """Compétitions dont au moins une saison vient de `source`."""
    return [k for k, spec in COMPETITION_SPECS.items() if any(s.source == source for s in spec.seasons)]


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
    if season not in season_labels(competition, published_only=False):
        raise ValueError(f"Saison {season!r} inconnue pour {competition}")
    base = RUGBY_RAW_DIR if root is None else Path(root) / "raw" / "rugby"
    return base / competition / season / f"{table}.parquet"


def processed_path(competition: str, season: str, period: str = "all",
                   root: Path | None = None) -> Path:
    """data_cache/processed/rugby/<compétition>/<saison>[_regular].parquet (une ligne par joueur),
    même convention de suffixe que les caches NBA (_playoffs)."""
    if season not in season_labels(competition, published_only=False):
        raise ValueError(f"Saison {season!r} inconnue pour {competition}")
    if period not in PERIODS:
        raise ValueError(f"Période inconnue : {period!r} (attendu : {', '.join(PERIODS)})")
    base = RUGBY_PROCESSED_DIR if root is None else Path(root) / "processed" / "rugby"
    suffix = "" if period == "all" else f"_{period}"
    return base / competition / f"{season}{suffix}.parquet"


# Mode "3 saisons" du radar (chantier E) : la saison choisie et les 2 précédentes, même compétition,
# saisons publiées, consécutives et de la même source (jamais une fenêtre à cheval sur deux sources,
# plan_v1_rugby.md section J). Club seulement.
WINDOW_SEASONS = 3


def window_candidates(competition: str, season: str) -> list[str] | None:
    """Libellés des WINDOW_SEASONS saisons consécutives qui finissent à `season` (club), qu'elles
    existent ou non, de la plus ancienne à la plus récente ; None hors club."""
    if COMPETITION_SPECS[competition].mode != CLUB:
        return None
    end = int(season[:4])
    return [_club_label(y) for y in range(end - WINDOW_SEASONS + 1, end + 1)]


def window_seasons(competition: str, season: str) -> list[str] | None:
    """Libellés des WINDOW_SEASONS saisons de la fenêtre qui finit à `season`, de la plus ancienne à
    la plus récente, ou None si la fenêtre n'existe pas : compétition internationale, saison
    inconnue, une des saisons absente ou non publiée (années consécutives exigées : le trou de
    2019-20 en Top 14 ne se saute pas), ou saisons de sources différentes."""
    labels = season_labels(competition)
    if season not in labels:
        return None
    window = window_candidates(competition, season)
    if window is None or any(s not in labels for s in window):
        return None
    if len({season_source(competition, s).source for s in window}) != 1:
        return None
    return window


def window_path(competition: str, season: str, period: str = "all",
                root: Path | None = None) -> Path:
    """data_cache/processed/rugby/<compétition>/<saison>_3saisons[_regular].parquet : une ligne par
    joueur de la fenêtre qui finit à `season`. Lève ValueError si la fenêtre n'existe pas."""
    if window_seasons(competition, season) is None:
        raise ValueError(f"Pas de fenêtre de {WINDOW_SEASONS} saisons pour {competition} {season}")
    if period not in PERIODS:
        raise ValueError(f"Période inconnue : {period!r} (attendu : {', '.join(PERIODS)})")
    base = RUGBY_PROCESSED_DIR if root is None else Path(root) / "processed" / "rugby"
    suffix = "" if period == "all" else f"_{period}"
    return base / competition / f"{season}_{WINDOW_SEASONS}saisons{suffix}.parquet"


# Versions de schéma (même mécanisme que nba.PROCESSED_SCHEMA_VERSION : base.read_cache traite
# un cache d'une autre version comme absent). Chaque montée porte un commentaire "vN : raison".
RUGBY_RAW_TABLES_SCHEMA_VERSION = 3      # les 5 tables de RAW_TABLES, produites ensemble
# Raw v2 : first_name et last_name dans lineups (tri du tableau du Dashboard par nom de famille).
# Raw v3 : minute négative = inconnue ("echec") ; appeared = minutes > 0 ou une stat de jeu ;
# compteurs de score pris dans les événements quand points de la source = événements
# (score_source "evenements_ligne").
RUGBY_PROFILES_SCHEMA_VERSION = 1
RUGBY_PROCESSED_SCHEMA_VERSION = 4      # v2 : low_sample_size au seuil club calibré (5 matchs, 520 min)
# v3 : first_name et last_name (tri du tableau du Dashboard par nom de famille puis prénom).
# v4 : par 80 stat par stat sur les matchs à minutes > 0 ; club principal = le plus de minutes ;
# clubs_detail ; position_share (badge "poste mixte").
# Caches des fenêtres de 3 saisons (window_path) : colonnes de la table traitée, plus window_label,
# window_start, window_end, seasons_played, season_detail et season_position_group
# (aggregate.aggregate_window). À reconstruire aussi quand RUGBY_PROCESSED_SCHEMA_VERSION monte.
RUGBY_WINDOW_SCHEMA_VERSION = 1

# --- Seuils et radar (calibration : scripts/rugby_calibrate.py, rugby_notes/calibration_v1.md) ---
# Profils de calibration : (mode, source) de la saison. Les réglages calibrés dépendent de la source
# et pas seulement du mode : ESPN et InCrowd ne comptent pas pareil (plan_v1_rugby.md, section J),
# d'où une calibration propre aux saisons ESPN (plan_espn.md, lot 4).
CLUB_ICW = (CLUB, SOURCE_INCROWD)
INTERNATIONAL_ESPN = (INTERNATIONAL, SOURCE_ESPN)


def calibration_profile(competition: str, season: str | None = None) -> tuple[str, str]:
    """Profil (mode, source) de la saison `season` de la compétition ; sans saison, celui de la
    saison publiée la plus récente."""
    src = (season_source(competition, season) if season is not None
           else _seasons(competition, published_only=True)[0])
    return COMPETITION_SPECS[competition].mode, src.source


# Population de référence du radar et badge "échantillon court" : (matchs joués, minutes).
# Club : 520 min = plus grand seuil qui garde, dans chaque poste et chaque saison (Top 14 et
# Pro D2), au moins 12 joueurs et 70 % des minutes jouées ; au-delà, les piliers (39 min par
# match en médiane) passent sous 70 %. Une fiabilité médiane de 0,6 sur l'ancien socle aurait
# demandé 1 220 min. 5 matchs : sans effet à 520 min (7 matchs au moins), gardé pour le badge.
# International : provisoire, à calibrer au lot 7 avec la même méthode.
SAMPLE_THRESHOLDS = {CLUB_ICW: (5, 520), INTERNATIONAL_ESPN: (2, 120)}

# Pourcentages ajustés ("padding", même formule que la NBA) : (réussis + P x moyenne de
# référence) / (tentatives + P). {mode : {colonne ajustée : (réussis, tentatives, P, tentatives
# minimum sur la saison, référence de la moyenne)}}. Sous le minimum : NaN, "NC" dans le tableau.
# P : split-half en tentatives, un seul P par stat (les P par poste divergent, piste notée après
# la V1). Minimum NC : volume où le joueur pèse 0,2 dans son % ajusté (n = P / 4, arrondi à 5),
# ordre de grandeur des seuils NBA. Référence "position" : moyenne du poste ; "kickers" : tous les
# buteurs qualifiés, sans poste. Clés : profils de calibration. International : au lot 7.
PADDING_REF_POSITION, PADDING_REF_KICKERS = "position", "kickers"
PCT_PADDING = {
    CLUB_ICW: {
        "tackle_pct_adj": ("tackles", "tackle_attempts", 97, 25, PADDING_REF_POSITION),
        "gain_line_pct_adj": ("carries_gain_line", "carries", 82, 20, PADDING_REF_POSITION),
        "goal_kick_pct_adj": ("goals_made", "goal_attempts", 146, 35, PADDING_REF_KICKERS),
    },
}

# Stats par 80 hors radar (tableau du radar) : rapprochées de la moyenne du poste, même logique que
# le padding des pourcentages, en minutes : (total + M x taux du poste par minute) / (minutes + M)
# x 80. M : constante split-half "M club" de calibration_v1.md, section 1.2 (un seul M par stat,
# comme un seul P par stat), minutes auxquelles la moitié de l'écart observé entre joueurs est du
# bruit. Contrôlées par scripts/rugby_calibrate.py.
PER80_SHRINK_M = {
    CLUB_ICW: {
        "tackles": 382, "metres": 400, "penalties_conceded": 1494, "turnovers_conceded": 1982,
        "carries": 145, "turnovers_won": 550, "clean_breaks": 1126, "defenders_beaten": 345,
        "offloads": 444, "passes": 297, "kick_metres": 180, "tries": 1919,
        "lineouts_won_jumper": 89, "lineout_steals": 389,
    },
}

# Axes du radar club, profil CLUB_ICW (un dictionnaire par profil au lot 5 du plan ESPN, avec les
# textes du radar). Règle (décision du 13 octobre 2026) : un axe n'est sur le radar d'un poste
# que si sa fiabilité sur une saison de 520 min atteint 0,4 pour ce poste (calibration_v1.md,
# section 5). Hors radar mais gardés dans le tableau et la fiche joueur : pénalités concédées et
# ballons perdus (par 80, "peu fiable sur une saison"), franchissements, essais (total), % au pied
# (détail réussis / tentatives, % ajusté de PCT_PADDING), % plaquages des arrières.
# {clé : (libellé, colonne affichée, colonne du score ou None, colonne des tentatives ou None)}
RADAR_MIN_RELIABILITY = 0.4
RADAR_AXES_CLUB = {
    "tackles": ("Plaquages", "tackles_per80", None, None),
    "tackle_pct": ("% plaquages réussis", "tackle_pct", "tackle_pct_adj", "tackle_attempts"),
    "metres": ("Mètres", "metres_per80", None, None),
    "gain_line_pct": ("% gain de ligne", "gain_line_pct", "gain_line_pct_adj", "carries"),
    "carries": ("Courses", "carries_per80", None, None),
    "turnovers_won": ("Grattages", "turnovers_won_per80", None, None),
    "defenders_beaten": ("Défenseurs battus", "defenders_beaten_per80", None, None),
    "passes": ("Passes", "passes_per80", None, None),
    "kick_metres": ("Mètres au pied", "kick_metres_per80", None, None),
    "offloads": ("Passes après contact", "offloads_per80", None, None),
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
# player_name : nom affiché (champ "known" d'InCrowd, sinon "name") ; first_name / last_name :
# prénom et nom de famille séparés par la source, pour le tri ("Champion de Crespigny", "le Brun"
# et "Arata Perrone" sont des noms de famille entiers, qu'un découpage au premier espace casserait).
LINEUP_COLUMNS = [
    "match_uid", "team_uid", "player_uid", "player_name", "first_name", "last_name", "jersey",
    "is_starter", "captain",
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
# score_source : "source" (stats du joueur telles que fournies), "evenements" (essais, buts et
# points recomptés depuis les événements, quand la source a perdu le score de l'équipe-match) ou
# "evenements_ligne" (compteurs d'une seule ligne pris dans les événements, quand les points de la
# source leur donnent raison contre les compteurs ; voir incrowd.fix_scoring_counters).
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
