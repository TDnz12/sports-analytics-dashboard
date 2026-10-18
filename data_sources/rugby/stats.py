"""
Lecture des stats joueurs par saison pour les pages (Dashboard), et catalogue des métriques
sélectionnables en X / Y.

get_player_stats lit seulement le parquet traité de data_cache/ (écrit par scripts/rugby_build.py),
jamais le réseau : un cache absent ou d'une autre version lève une erreur claire. Elle ajoute des
colonnes d'affichage calculées à la lecture (pas stockées dans le cache) :
- position_label : poste, avec la mention "(banc)" pour un remplaçant jamais titulaire dont le
  poste est déduit du maillot 16, 17 ou 18 (plan, P5 ; explication dans SOURCE_CAPTION) ;
- position_family : "Indéterminé" à la place d'une valeur vide, pour la couleur du graph ;
- cards : "jaunes / rouges" de la saison ;
- team : nom d'affichage avec ses accents (TEAM_DISPLAY_NAMES), player_label recalculé avec lui ;
- player, first_name, last_name : une graphie par joueur sur toutes les saisons (player_names),
  puis les corrections manuelles PLAYER_DISPLAY_NAMES ; player_label recalculé avec elles ;
- clubs : "Bordeaux-Bègles (10), Perpignan (4)" (matchs joués, ordre chronologique) pour un joueur
  passé par plusieurs clubs dans la saison, sinon vide ; club_names : tuple des clubs où il a joué
  (filtre équipe du Dashboard : il apparaît dans chacun) ;
- mixed_position : poste principal sous 60 % des titularisations (positions.MIXED_POSITION_SHARE) ;
- seasons (fenêtre de 3 saisons seulement) : [(saison, club affiché, matchs joués, minutes), ...]
  depuis season_detail, pour la carte du radar.
"""

from __future__ import annotations

import functools
import json

import pandas as pd
from unidecode import unidecode

from ..base import Metric, read_cache
from . import schema
from .positions import MIXED_POSITION_SHARE, SOURCE_BENCH, SOURCE_STARTER, UNDETERMINED


# Noms d'équipes à l'affichage : InCrowd les donne sans accents ("Bordeaux-Begles") et sous des
# formes mélangées ("Castres Olympique" à côté de "Pau"). Indexés par identifiant d'équipe
# (stable), appliqués à la lecture seulement : caches et identifiants inchangés. Équipes Top 14 et
# Pro D2 (2021-22 à 2025-26) dont le nom perd un accent ou n'est pas le nom d'usage court.
TEAM_DISPLAY_NAMES = {
    "icw:5195": "Béziers",
    "icw:1610": "Biarritz",
    "icw:5979": "Bordeaux-Bègles",
    "icw:6294": "Castres",
    "icw:3094": "Clermont",
    "icw:2806": "Lyon",
    "icw:3921": "Soyaux-Angoulême",
    "icw:4003": "Stade Français",
}

# Noms de joueurs à l'affichage. La source écrit presque tous les noms sans accents, et un même
# joueur (identifiant) change parfois de graphie d'un match à l'autre ("Greg Alldritt" puis
# "Grégory Alldritt", "Adrien Lapegue Lafaye" puis "Adrien Lapegue"). Règle 1 (canonical_names) :
# une seule graphie par identifiant, sur toutes les saisons et les deux compétitions. Règle 2 :
# PLAYER_DISPLAY_NAMES, corrections manuelles appliquées en dernier (nom affiché seulement : le tri
# ignore les accents). Comme TEAM_DISPLAY_NAMES : à la lecture, caches et identifiants inchangés.
# Chaque entrée vérifiée contre une source externe (presse, Wikipedia, all.rugby, RugbyPass) le 15
# octobre 2026.
PLAYER_DISPLAY_NAMES = {
    "icw:206243": "Léo Barré",
    "icw:237225": "Émilien Gailleton",
    "icw:244532": "Théo Attissogbe",
    "icw:199515": "Gaël Fickou",
    "icw:241689": "Nicolas Depoortère",
    "icw:159140": "Gaëtan Barlot",
    "icw:245059": "Léon Darricarrère",
    "icw:177800": "Mickaël Guillard",
    "icw:187175": "Gabin Villière",
    "icw:173503": "Thomas Jolmès",
    "icw:166457": "Régis Montagne",
    "icw:120507": "Rémi Picquette",
    "icw:233225": "Clément Vergé",
    "icw:229823": "Léo Banos",
    "icw:184178": "Léo Coly",
    "icw:243934": "Léo Carbonneau",
    "icw:120396": "Sébastien Bézy",
    "icw:244533": "Axel Despérès",
    "icw:243881": "Lois Guérois-Galisson",
    "icw:189645": "Mickaël Ivaldi",
    "icw:203198": "Théo Millet",
    "icw:241359": "Théo Chabouni",
    "icw:162570": "Enzo Hervé",
    "icw:188484": "Arthur Retière",
    "icw:243819": "Mathis Ferté",
    "icw:161080": "Loïc Crédoz",
    "icw:244765": "Maël Moustin",
    "icw:158404": "Julien Hériteau",
    "icw:161580": "Charles-Henri Berguet",  # "Charlesty" (surnom) et "Martin" dans la source
    "icw:137322": "Chris Hilsenbeck",  # faute de frappe de la source ("Hilsenback")
}

# Identifiants laissés hors de la règle 1 (graphie de chaque saison gardée) : deux noms de famille
# sous le même identifiant, peut-être deux joueurs (anomalie de la source, vérifiée le 15 octobre
# 2026 : même club, mêmes maillots, jamais sur la même feuille de match).
SINGLE_NAME_EXCLUDED = {"icw:229659"}  # "Aurelien Lafforgue" / "Aurelien Lisena", Pro D2


def canonical_names(lineups: pd.DataFrame) -> pd.DataFrame:
    """Règle 1 sur des feuilles de match (player_uid, player_name, first_name, last_name,
    date_utc) : la graphie du match le plus récent, sauf si un autre match donne le même nom
    avec des accents (égal une fois accents et casse retirés) ; la graphie accentuée l'emporte
    alors. Une ligne par identifiant, colonnes player, first_name, last_name."""
    df = lineups.sort_values("date_utc", kind="stable")
    plain = df["player_name"].map(lambda n: unidecode(n).casefold())
    df = df[plain == plain.groupby(df["player_uid"]).transform("last")]
    df = (df.assign(_accented=df["player_name"] != df["player_name"].map(unidecode))
          .sort_values("_accented", kind="stable"))
    best = df.drop_duplicates("player_uid", keep="last").set_index("player_uid")
    return best.rename(columns={"player_name": "player"})[["player", "first_name", "last_name"]]


@functools.lru_cache(maxsize=1)
def player_names() -> pd.DataFrame:
    """canonical_names sur toutes les feuilles de match versionnées (tables brutes de
    data_cache/), lues une fois par processus (environ 0,1 s), sans SINGLE_NAME_EXCLUDED. Une
    compétition sans tables brutes (Six Nations, pas encore construit) est sautée."""
    frames = []
    for comp in schema.COMPETITION_SPECS:
        for season in schema.season_labels(comp):
            path = schema.raw_table_path(comp, season, "lineups")
            if not path.exists():
                continue
            lineups = pd.read_parquet(path, columns=["match_uid", "player_uid", "player_name",
                                                     "first_name", "last_name"])
            dates = pd.read_parquet(schema.raw_table_path(comp, season, "matches"),
                                    columns=["match_uid", "date_utc"])
            frames.append(lineups.merge(dates, on="match_uid"))
    names = canonical_names(pd.concat(frames, ignore_index=True))
    return names.drop(index=list(SINGLE_NAME_EXCLUDED), errors="ignore")


def get_player_stats(season: str, force_refresh: bool = False, period: str = "all",
                     competition: str = "top14", window: int = 1) -> pd.DataFrame:
    """Une ligne par joueur de la compétition et de la saison (libellé, ex. "2024-25"). `period` :
    "all" (saison complète, phases finales incluses) ou "regular". `window` : 1 (la saison) ou
    schema.WINDOW_SEASONS (la saison et les 2 précédentes, mode 3 saisons du radar ; ValueError si
    la fenêtre n'existe pas). `force_refresh` est accepté pour garder l'interface commune aux
    sports, sans effet : les caches se reconstruisent hors ligne avec scripts/rugby_build.py."""
    if window == 1:
        path, version = (schema.processed_path(competition, season, period),
                         schema.RUGBY_PROCESSED_SCHEMA_VERSION)
    elif window == schema.WINDOW_SEASONS:
        path, version = (schema.window_path(competition, season, period),
                         schema.RUGBY_WINDOW_SCHEMA_VERSION)
    else:
        raise ValueError(f"Fenêtre de {window} saisons non prévue (1 ou {schema.WINDOW_SEASONS})")
    df = read_cache(path, schema_version=version)
    if df is None:
        what = f"{season}" if window == 1 else f"{window} saisons jusqu'à {season}"
        option = "" if window == 1 else " --windows-only"
        raise FileNotFoundError(
            f"Cache rugby absent ou ancien ({competition}, {what}, période {period}) : "
            f"relancer scripts/rugby_build.py --comp {competition}{option}."
        )
    df = df.copy()
    df["team"] = df["team_uid"].map(TEAM_DISPLAY_NAMES).fillna(df["team"])
    names = player_names()
    for col in ("player", "first_name", "last_name"):
        df[col] = df["player_uid"].map(names[col]).fillna(df[col])
    df["player"] = df["player_uid"].map(PLAYER_DISPLAY_NAMES).fillna(df["player"])
    # Même règle que aggregate.aggregate_season, avec le nom d'équipe accentué.
    dup = df["player"].duplicated(keep=False)
    df["player_label"] = df["player"].where(~dup, df["player"] + " (" + df["team"] + ")")
    df["position_label"] = df["position_group"].where(
        df["position_source"] != SOURCE_BENCH, df["position_group"] + " (banc)")
    df["position_family"] = df["position_family"].fillna(UNDETERMINED)
    df["cards"] = (df["yellow_cards"].fillna(0).astype(int).astype(str) + " / "
                   + df["red_cards"].fillna(0).astype(int).astype(str))
    clubs = df["clubs_detail"].map(json.loads)
    named = clubs.map(lambda d: [(TEAM_DISPLAY_NAMES.get(uid, name), n) for uid, name, n in d])
    df["club_names"] = [tuple(name for name, _ in d) or (team,) for d, team in zip(named, df["team"])]
    df["clubs"] = named.map(lambda d: ", ".join(f"{name} ({n})" for name, n in d) if len(d) > 1 else None)
    df["mixed_position"] = ((df["position_source"] == SOURCE_STARTER)
                            & (df["position_share"] < MIXED_POSITION_SHARE))
    if "season_detail" in df.columns:
        df["seasons"] = df["season_detail"].map(json.loads).map(
            lambda d: [(s, TEAM_DISPLAY_NAMES.get(uid, name), games, minutes)
                       for s, uid, name, games, minutes in d])
    return df


# Seuils NC des pourcentages : mêmes valeurs que le radar (schema.PCT_PADDING, calibration).
_NC = {adj: spec[3] for adj, spec in schema.PCT_PADDING[schema.CLUB].items()}


def _per80(key: str, label: str, category: str, unreliable: bool = False) -> Metric:
    return Metric(f"{key}_per80", f"{label} par 80 min", ".1f", category, unreliable=unreliable)


def _pct(key: str, label: str, category: str, made: str, attempts: str, adj: str) -> Metric:
    return Metric(key, label, ".0%", category, made_col=made, attempts_col=attempts,
                  min_attempts=_NC[adj])


# Catalogue du Dashboard (club). "Peu fiable sur une saison" : fiabilité sous 0,4 sur une saison
# de 520 minutes, tous postes confondus (rugby_notes/calibration_v1.md, section 5). Passes
# décisives, âge, taille et poids : absents en club (vides chez InCrowd, profils abandonnés),
# donc hors catalogue ; ils reviendront avec le Six Nations.
_METRIC_LIST = [
    _per80("tackles", "Plaquages", "Défense"),
    _pct("tackle_pct", "% plaquages réussis", "Défense", "tackles", "tackle_attempts",
         "tackle_pct_adj"),
    _per80("missed_tackles", "Plaquages manqués", "Défense", unreliable=True),
    _per80("turnovers_won", "Grattages", "Défense"),
    _per80("carries", "Courses", "Attaque"),
    _per80("metres", "Mètres", "Attaque"),
    Metric("metres_per_carry", "Mètres par course", ".1f", "Attaque"),
    _pct("gain_line_pct", "% gain de ligne", "Attaque", "carries_gain_line", "carries",
         "gain_line_pct_adj"),
    _per80("defenders_beaten", "Défenseurs battus", "Attaque"),
    Metric("clean_breaks", "Franchissements (total)", ".0f", "Attaque"),
    _per80("clean_breaks", "Franchissements", "Attaque", unreliable=True),
    _per80("offloads", "Passes après contact", "Attaque"),
    _per80("passes", "Passes", "Attaque"),
    _per80("kicks_from_hand", "Coups de pied", "Jeu au pied"),
    _per80("kick_metres", "Mètres au pied", "Jeu au pied"),
    _pct("goal_kick_pct", "% au pied", "Jeu au pied",
         "goals_made", "goal_attempts", "goal_kick_pct_adj"),
    _per80("lineouts_won_jumper", "Touches gagnées", "Touche"),
    _per80("lineout_steals", "Touches volées", "Touche"),
    Metric("tries", "Essais (total)", ".0f", "Marque"),
    _per80("tries", "Essais", "Marque", unreliable=True),
    Metric("points", "Points (total)", ".0f", "Marque"),
    _per80("points", "Points", "Marque"),
    _per80("penalties_conceded", "Pénalités concédées", "Discipline", unreliable=True),
    _per80("turnovers_conceded", "Ballons perdus", "Discipline", unreliable=True),
    Metric("yellow_cards", "Cartons jaunes (total)", ".0f", "Discipline"),
    Metric("red_cards", "Cartons rouges (total)", ".0f", "Discipline"),
    Metric("games_played", "Matchs joués", ".0f", "Temps de jeu"),
    Metric("starts", "Titularisations", ".0f", "Temps de jeu"),
    Metric("minutes_total", "Minutes jouées (total)", ".0f", "Temps de jeu"),
    Metric("minutes_per_game", "Minutes par match", ".1f", "Temps de jeu"),
    Metric("start_rate", "Taux de titularisation", ".0%", "Temps de jeu"),
    Metric("availability", "Disponibilité (feuilles de match)", ".0%", "Temps de jeu"),
]
METRICS: dict[str, Metric] = {m.key: m for m in _METRIC_LIST}

# Colonnes du tableau détaillé du Dashboard, avant et après les colonnes des métriques choisies.
DETAIL_LEAD_COLUMNS = {
    "player_label": "Joueur", "team": "Équipe", "clubs": "Clubs", "position_label": "Poste",
    "games_played": "Matchs", "starts": "Titularisations", "minutes_total": "Minutes",
}
DETAIL_TAIL_COLUMNS = {"tries": "Essais", "cards": "Cartons (J / R)"}

_MIN_GAMES, _MIN_MINUTES = schema.SAMPLE_THRESHOLDS[schema.CLUB]
LOW_SAMPLE_LABEL = f"moins de {_MIN_GAMES} matchs ou {_MIN_MINUTES} minutes"

SOURCE_CAPTION = (
    "Stats de jeu : flux InCrowd (rugbyviz) du Top 14 et du Pro D2, téléchargé hors ligne puis "
    "mis en cache dans `data_cache/` (aucun appel réseau depuis le site).  ·  Minutes : celles de "
    "la source, reconstruites depuis les remplacements et les cartons quand la somme d'une équipe "
    "sort de la tolérance.  ·  Poste : numéro le plus porté comme titulaire ; remplaçant jamais "
    "titulaire : poste déduit du maillot de banc, 16 talonneur, 17 et 18 pilier (« Talonneur "
    "(banc) », « Pilier (banc) »), sinon « Indéterminé ».  ·  "
    "Par 80 min : total divisé par les minutes jouées, multiplié par 80. Les stats par 80 min "
    "des joueurs qui entrent souvent en cours de match peuvent être plus élevées : jambes "
    "fraîches face à une défense fatiguée, extrapolées sur 80 minutes.  ·  Pourcentages "
    "calculés sur les totaux de la saison ; % au pied : transformations et pénalités, drops "
    "exclus ; « NC » (non classé) sous "
    f"{_NC['tackle_pct_adj']} plaquages tentés, {_NC['gain_line_pct_adj']} courses ou "
    f"{_NC['goal_kick_pct_adj']} tentatives au but.  ·  Échantillon court : {LOW_SAMPLE_LABEL} "
    "sur la saison.  ·  « Peu fiable sur une saison » : stat dont la fiabilité reste sous 0,4 "
    f"sur une saison de {_MIN_MINUTES} minutes (événements rares : écarts entre joueurs surtout "
    "dus au hasard).  ·  Disponibilité : matchs sur la feuille divisés par les matchs de son "
    "équipe entre son premier et son dernier match ; les absences (blessure, choix, sélection) "
    "ne sont pas distinguées."
)
