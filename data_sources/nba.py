"""
Couche data pour le basketball NBA.

Source primaire (stats de jeu, saison par saison, en direct) :
    nba_api -> endpoints officiels stats.nba.com (gratuit, sans clé).

Source secondaire (salaires + PER historique) — DEUX datasets Kaggle, frontière à
RATIN21_DATASET_START_YEAR (2010-11) :
  - 2010-11 → saison courante : "ratin21/nba-player-stats-and-salaries-2010-2025"
    (lui-même sourcé de HoopsHype / Basketball-Reference). En prod depuis le début du
    projet, vérifié (voir _load_kaggle_raw).
  - 1996-97 → 2009-10 : "iampunitkmryh/nba-players-details-198518" (fichier
    salaries_1985to2018.csv, licence CC0), qui comble le trou que ratin21 ne couvre pas
    (voir _load_legacy_kaggle_raw). Les deux jeux de données sont normalisés vers les
    mêmes colonnes Player/Salary/Season avant d'alimenter la logique d'extraction
    commune (_extract_kaggle_season) : le reste du pipeline ne sait pas lequel a été
    utilisé. Deux trous connus DANS ce dataset legacy (saisons sans couverture salariale
    exploitable) sont documentés et exclus via KNOWN_SALARY_DATA_GAPS.
    1996-97 est la borne basse absolue du dashboard : c'est la première saison où
    nba_api renvoie des données exploitables (confirmé empiriquement, voir
    EARLIEST_SUPPORTED_SEASON_START_YEAR) — antérieur à ça, même avec un salaire
    disponible, il n'y aurait pas de stats de jeu à croiser avec.
nba_api n'expose pas les salaires ni le PER "officiel" Basketball-Reference : on les
récupère donc via ces datasets et on les fusionne sur le nom du joueur.

Le salaire en $ est aussi normalisé en % du plafond salarial officiel de la saison
(NBA_SALARY_CAP_BY_SEASON) : salary_pct_cap, pour rester comparable entre des saisons où
le plafond a été multiplié par ~6 (24M$ en 1996-97 à 155M$ en 2025-26).

Tout est mis en cache dans /data_cache pour ne pas re-scraper/re-télécharger
à chaque lancement de l'app (voir base.py: RAW_ROOT / PROCESSED_ROOT). Pour pré-remplir
ce cache sur toutes les saisons d'un coup (hors premier chargement utilisateur), voir
scripts/prefill_cache.py.

Point d'entrée public : get_player_stats(season) -> DataFrame normalisé.
"""

from __future__ import annotations

import functools
import glob
import logging
import math
import time
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from .base import Metric, RAW_ROOT, PROCESSED_ROOT, normalize_name, read_cache, write_cache

# Seuil en dessous duquel une moyenne par match (n'importe laquelle) est jugée peu fiable pour
# représenter un joueur sur la saison affichée -- un tout petit échantillon de matchs (ex: 4-11)
# peut être gonflé par un simple coup de chaud plutôt que refléter une vraie performance de
# saison. Pas un filtre qui cache le joueur : voir la colonne `low_sample_size`
# (`_recompute_derived_stat_columns`), utilisée par Dashboard.py/le radar pour le distinguer
# visuellement (badge, marqueur différent) sans le cacher, et comme référence pour le radar de
# comparaison (`compute_radar_scores`).
#
# NOTE : le nom "MIN_GAMES_FOR_FIT" date d'une fonctionnalité de salaire attendu/valeur ajoutée
# retirée du dashboard (régression salaire ~ performance jugée peu fiable sur les cas extrêmes,
# voir METHODOLOGY.md) -- gardé tel quel pour ne pas renommer une constante encore utilisée
# ailleurs (Dashboard.py, radar) sans nécessité, mais ne désigne plus aucun "fit" aujourd'hui.
MIN_GAMES_FOR_FIT = 15

# Seuil équivalent pour period="playoffs" -- 15 est intenable en playoffs : le maximum RÉEL
# jouable sur une saison tourne autour de 22-23 matchs (4 tours best-of-7, sweep systématique de
# l'adversaire à chaque tour requis pour approcher le maximum théorique de 28), et la plupart des
# équipes sont éliminées bien avant. Mesuré sur données réelles (2024-25) avant correction : ~84%
# de TOUS les joueurs ayant fait les playoffs étaient marqués low_sample_size avec le seuil de
# 15, y compris 33 à 53% du roster de l'équipe CHAMPIONNE selon la saison (qui joue pourtant le
# maximum de matchs possible). 4 matchs = le minimum pour compléter/sweeper une série (format
# best-of-7) -- seuil bas mais structurellement significatif, contrairement à 15 qui ne l'est
# simplement pas dans ce contexte.
MIN_GAMES_FOR_FIT_PLAYOFFS = 4

# Nombre de saisons (la saison affichée + les précédentes) utilisées pour calculer la
# métrique "Fiabilité" = matchs joués / matchs possibles de l'équipe sur cette fenêtre. Voir
# _fetch_reliability. nba_api couvre l'historique bien avant 2010, donc cette fenêtre peut
# regarder plus loin en arrière que SEASONS (le sélecteur de saisons de l'UI) sans problème.
RELIABILITY_LOOKBACK_SEASONS = 3
EARLIEST_SUPPORTED_SEASON_START_YEAR = 1996  # nba_api est fiable à partir de 1996-97

# Nombre de tentatives (avec backoff court) pour un appel réseau nba_api jugé assez critique
# pour justifier des retries — voir _call_with_retries. N'est pas appliqué systématiquement à
# tous les appels du fichier : seulement là où un échec casse une fonctionnalité entière plutôt
# qu'une colonne annexe (ex: _fetch_player_positions, dont dépend le radar de comparaison).
NETWORK_RETRY_ATTEMPTS = 3
NETWORK_RETRY_BACKOFF_SECONDS = 1.5
# Délai max d'un appel nba_api sans réponse (défaut nba_api : 30 s). Sur Streamlit Cloud,
# stats.nba.com ne répond pas : 3 tentatives x 30 s bloquaient la page Effectifs (ex-Mercato) ~1 min 30.
NBA_API_TIMEOUT_SECONDS = 10

logger = logging.getLogger(__name__)

NBA_RAW_DIR = RAW_ROOT / "nba"
NBA_PROCESSED_DIR = PROCESSED_ROOT / "nba"
KAGGLE_DATASET_SLUG = "ratin21/nba-player-stats-and-salaries-2010-2025"
KAGGLE_RAW_CACHE = NBA_RAW_DIR / "kaggle_raw.parquet"
MANUAL_FALLBACK_DIR = NBA_RAW_DIR / "manual"

# Deuxième source de salaires, pour les saisons ANTÉRIEURES à ratin21 (voir
# RATIN21_DATASET_START_YEAR). Licence CC0 (domaine public) d'après la page Kaggle du
# dataset — à revérifier manuellement sur la page avant toute republication du code source,
# cette vérification automatisée n'ayant pas pu être faite (page Kaggle en JS, illisible par
# les outils de lecture web disponibles ici). Fiabilité vérifiée par recoupement exact (3/3,
# au dollar près) avec ratin21 sur des cas connus (LeBron James 2010-11/2014-15, Kobe Bryant
# 2010-11) lors du diagnostic préalable à cette intégration.
LEGACY_KAGGLE_DATASET_SLUG = "iampunitkmryh/nba-players-details-198518"
LEGACY_KAGGLE_RAW_CACHE = NBA_RAW_DIR / "legacy_kaggle_raw.parquet"
LEGACY_MANUAL_FALLBACK_DIR = NBA_RAW_DIR / "manual_legacy"

# Frontière entre les deux sources de salaires : les saisons à partir de cette année
# (incluse, ex. "2010-11") utilisent ratin21 (déjà en prod, vérifié) ; les saisons
# antérieures (jusqu'à EARLIEST_SUPPORTED_SEASON_START_YEAR=1996, la vraie limite —
# nba_api renvoie 0 ligne avant 1996-97, testé empiriquement — le dataset legacy couvrirait
# en théorie jusqu'à 1984-85 mais ça ne sert à rien, PIE/positions/fiabilité n'existeraient
# pas pour ces saisons-là) utilisent le dataset legacy.
RATIN21_DATASET_START_YEAR = 2010

# Saisons avec un trou de couverture connu et documenté dans le dataset legacy (40 et 64
# lignes contre 200-550+ pour les saisons voisines — repéré lors du diagnostic préalable).
# Exclues explicitement de SEASONS plutôt qu'affichées avec des données manifestement
# incomplètes, qui fausseraient silencieusement le modèle salaire~performance (fit instable
# sur un échantillon anormalement petit) et le classement par équipe (quelques franchises
# seulement représentées). Actuellement hors de la plage utilisée (1996-97+, limite nba_api)
# donc sans impact concret — conservé si le périmètre bouge encore (ex: si nba_api étend un
# jour sa couverture, ou si une autre source de stats de jeu pré-1996 est ajoutée).
KNOWN_SALARY_DATA_GAPS = {"1986-87", "1989-90"}

# Plafond salarial officiel de la NBA par saison, en dollars — utilisé pour les métriques
# "% du plafond" (comparables entre saisons malgré l'inflation du cap au fil du temps,
# contrairement aux M$ bruts). Données publiques (annonces officielles de la ligue,
# largement reprises), PAS scrapées automatiquement : relevées manuellement depuis
# SalarySwish (https://www.salaryswish.com/salary-cap) et recoupées avec succès (valeurs
# identiques) contre des annonces officielles individuelles trouvées séparément (ESPN,
# pr.nba.com) pour 1996-97, 1997-98, 1998-99, 1999-00, 2016-17 à 2025-26 — 11 des 30 valeurs
# vérifiées par une deuxième source indépendante avant intégration.
NBA_SALARY_CAP_BY_SEASON: dict[str, int] = {
    "1996-97": 24_363_000,
    "1997-98": 26_900_000,
    "1998-99": 30_000_000,
    "1999-00": 34_000_000,
    "2000-01": 35_500_000,
    "2001-02": 42_500_000,
    "2002-03": 40_271_000,
    "2003-04": 43_840_000,
    "2004-05": 43_870_000,
    "2005-06": 49_500_000,
    "2006-07": 53_135_000,
    "2007-08": 55_630_000,
    "2008-09": 58_680_000,
    "2009-10": 57_700_000,
    "2010-11": 58_044_000,
    "2011-12": 58_044_000,
    "2012-13": 58_044_000,
    "2013-14": 58_679_000,
    "2014-15": 63_065_000,
    "2015-16": 70_000_000,
    "2016-17": 94_143_000,
    "2017-18": 99_093_000,
    "2018-19": 101_869_000,
    "2019-20": 109_140_000,
    "2020-21": 109_140_000,
    "2021-22": 112_414_000,
    "2022-23": 123_655_000,
    "2023-24": 136_021_000,
    "2024-25": 140_588_000,
    "2025-26": 154_647_000,
}

# Récompenses individuelles de fin de saison à lauréat UNIQUE (une seule par saison — délibérément
# PAS les équipes All-NBA/All-Défense, qui désignent 10-15 joueurs et rendraient les icônes
# illisibles sur un nuage déjà dense) : MVP, DPOY (Défenseur de l'année), ROY (Rookie de l'année),
# MIP (Progression de l'année), 6MOY (Sixième homme de l'année), FINALS_MVP (MVP des finales).
# Compilées à la main saison par saison à partir des annonces officielles NBA connues (même
# politique que NBA_SALARY_CAP_BY_SEASON : PAS depuis Basketball-Reference/HoopsHype).
# Chaque valeur est une LISTE de noms (pas une chaîne unique) : le cas normal a un seul lauréat,
# mais l'historique NBA a un vrai cas de co-lauréats (ROY 1999-00, Elton Brand et Steve Francis
# à égalité de votes) — une liste évite un traitement spécial pour ce cas plutôt que de forcer un
# format "Nom A / Nom B" à parser. Noms orthographiés tels qu'attendus dans PLAYER_NAME de
# nba_api (prénom + nom, suffixe Jr./Sr./III inclus si officiel) ; le rapprochement avec la
# colonne `player` du dataset passe par base.normalize_name (accents, casse, suffixes, ponctuation
# — voir match_season_awards) plutôt que par une comparaison exacte de chaîne.
#
# Vérification des 3 saisons les plus récentes (2023-24 à 2025-26) : recoupées via recherche web
# le 14/09/2026 (au-delà de la connaissance interne pour 2024-25/2025-26, saisons closes après la
# date de coupure d'entraînement) — sources : ESPN, NBA.com, Spurs.com, CBS Sports, Olympics.com,
# CBSSports, Bleacher Report, Yahoo Sports, Wikipedia. Aucun doute résiduel sur ces 3 saisons
# après vérification, y compris pour MIP/6MOY/FINALS_MVP ajoutés dans un 2e temps (même
# vérification web refaite pour ces 3 nouvelles catégories).
SEASON_AWARDS: dict[str, dict[str, list[str]]] = {
    # MIP 1996-97 : Isaac Austin, orthographié "Ike Austin" ici -- c'est le nom d'usage sous lequel
    # nba_api le référence (PLAYER_NAME), pas son prénom complet. Repéré par match_season_awards.
    "1996-97": {"MVP": ["Karl Malone"], "DPOY": ["Dikembe Mutombo"], "ROY": ["Allen Iverson"], "MIP": ["Ike Austin"], "6MOY": ["John Starks"], "FINALS_MVP": ["Michael Jordan"]},
    "1997-98": {"MVP": ["Michael Jordan"], "DPOY": ["Dikembe Mutombo"], "ROY": ["Tim Duncan"], "MIP": ["Alan Henderson"], "6MOY": ["Danny Manning"], "FINALS_MVP": ["Michael Jordan"]},
    "1998-99": {"MVP": ["Karl Malone"], "DPOY": ["Alonzo Mourning"], "ROY": ["Vince Carter"], "MIP": ["Darrell Armstrong"], "6MOY": ["Darrell Armstrong"], "FINALS_MVP": ["Tim Duncan"]},
    "1999-00": {"MVP": ["Shaquille O'Neal"], "DPOY": ["Alonzo Mourning"], "ROY": ["Elton Brand", "Steve Francis"], "MIP": ["Jalen Rose"], "6MOY": ["Rodney Rogers"], "FINALS_MVP": ["Shaquille O'Neal"]},
    "2000-01": {"MVP": ["Allen Iverson"], "DPOY": ["Dikembe Mutombo"], "ROY": ["Mike Miller"], "MIP": ["Tracy McGrady"], "6MOY": ["Aaron McKie"], "FINALS_MVP": ["Shaquille O'Neal"]},
    "2001-02": {"MVP": ["Tim Duncan"], "DPOY": ["Ben Wallace"], "ROY": ["Pau Gasol"], "MIP": ["Jermaine O'Neal"], "6MOY": ["Corliss Williamson"], "FINALS_MVP": ["Shaquille O'Neal"]},
    "2002-03": {"MVP": ["Tim Duncan"], "DPOY": ["Ben Wallace"], "ROY": ["Amar'e Stoudemire"], "MIP": ["Gilbert Arenas"], "6MOY": ["Bobby Jackson"], "FINALS_MVP": ["Tim Duncan"]},
    # DPOY 2003-04 : gagné par Ron Artest, orthographié "Metta World Peace" ici -- nba_api
    # référence rétroactivement ce player_id sous son nom légal ultérieur (changement de nom en
    # 2011) même pour ses saisons d'avant 2011, y compris 2003-04. Repéré par
    # match_season_awards (UnmatchedAwardWinner) en testant contre le dataset réel, pas deviné.
    "2003-04": {"MVP": ["Kevin Garnett"], "DPOY": ["Metta World Peace"], "ROY": ["LeBron James"], "MIP": ["Zach Randolph"], "6MOY": ["Antawn Jamison"], "FINALS_MVP": ["Chauncey Billups"]},
    "2004-05": {"MVP": ["Steve Nash"], "DPOY": ["Ben Wallace"], "ROY": ["Emeka Okafor"], "MIP": ["Bobby Simmons"], "6MOY": ["Ben Gordon"], "FINALS_MVP": ["Tim Duncan"]},
    "2005-06": {"MVP": ["Steve Nash"], "DPOY": ["Ben Wallace"], "ROY": ["Chris Paul"], "MIP": ["Boris Diaw"], "6MOY": ["Mike Miller"], "FINALS_MVP": ["Dwyane Wade"]},
    "2006-07": {"MVP": ["Dirk Nowitzki"], "DPOY": ["Marcus Camby"], "ROY": ["Brandon Roy"], "MIP": ["Monta Ellis"], "6MOY": ["Leandro Barbosa"], "FINALS_MVP": ["Tony Parker"]},
    "2007-08": {"MVP": ["Kobe Bryant"], "DPOY": ["Kevin Garnett"], "ROY": ["Kevin Durant"], "MIP": ["Hedo Türkoğlu"], "6MOY": ["Manu Ginóbili"], "FINALS_MVP": ["Paul Pierce"]},
    "2008-09": {"MVP": ["LeBron James"], "DPOY": ["Dwight Howard"], "ROY": ["Derrick Rose"], "MIP": ["Danny Granger"], "6MOY": ["Jason Terry"], "FINALS_MVP": ["Kobe Bryant"]},
    "2009-10": {"MVP": ["LeBron James"], "DPOY": ["Dwight Howard"], "ROY": ["Tyreke Evans"], "MIP": ["Aaron Brooks"], "6MOY": ["Jamal Crawford"], "FINALS_MVP": ["Kobe Bryant"]},
    "2010-11": {"MVP": ["Derrick Rose"], "DPOY": ["Dwight Howard"], "ROY": ["Blake Griffin"], "MIP": ["Kevin Love"], "6MOY": ["Lamar Odom"], "FINALS_MVP": ["Dirk Nowitzki"]},
    "2011-12": {"MVP": ["LeBron James"], "DPOY": ["Tyson Chandler"], "ROY": ["Kyrie Irving"], "MIP": ["Ryan Anderson"], "6MOY": ["James Harden"], "FINALS_MVP": ["LeBron James"]},
    # 6MOY 2012-13 : J.R. Smith, orthographié "JR Smith" ici (sans points) -- nba_api n'utilise
    # pas de points dans ses initiales, et avec points normalize_name échoue à matcher : "J.R."
    # (points retirés APRÈS le test du suffixe Jr./Sr., donc "jr" survit dans la clé) donne
    # "jr smith", alors que "JR" (sans points dès le départ) se fait retirer par la même regex de
    # suffixe (qui le confond avec un vrai "Jr.") pour donner "smith" -- clés différentes, faux
    # négatif. Repéré par match_season_awards, pas deviné.
    "2012-13": {"MVP": ["LeBron James"], "DPOY": ["Marc Gasol"], "ROY": ["Damian Lillard"], "MIP": ["Paul George"], "6MOY": ["JR Smith"], "FINALS_MVP": ["LeBron James"]},
    "2013-14": {"MVP": ["Kevin Durant"], "DPOY": ["Joakim Noah"], "ROY": ["Michael Carter-Williams"], "MIP": ["Goran Dragić"], "6MOY": ["Jamal Crawford"], "FINALS_MVP": ["Kawhi Leonard"]},
    "2014-15": {"MVP": ["Stephen Curry"], "DPOY": ["Kawhi Leonard"], "ROY": ["Andrew Wiggins"], "MIP": ["Jimmy Butler"], "6MOY": ["Lou Williams"], "FINALS_MVP": ["Andre Iguodala"]},
    "2015-16": {"MVP": ["Stephen Curry"], "DPOY": ["Kawhi Leonard"], "ROY": ["Karl-Anthony Towns"], "MIP": ["C.J. McCollum"], "6MOY": ["Jamal Crawford"], "FINALS_MVP": ["LeBron James"]},
    "2016-17": {"MVP": ["Russell Westbrook"], "DPOY": ["Draymond Green"], "ROY": ["Malcolm Brogdon"], "MIP": ["Giannis Antetokounmpo"], "6MOY": ["Eric Gordon"], "FINALS_MVP": ["Kevin Durant"]},
    "2017-18": {"MVP": ["James Harden"], "DPOY": ["Rudy Gobert"], "ROY": ["Ben Simmons"], "MIP": ["Victor Oladipo"], "6MOY": ["Lou Williams"], "FINALS_MVP": ["Kevin Durant"]},
    "2018-19": {"MVP": ["Giannis Antetokounmpo"], "DPOY": ["Rudy Gobert"], "ROY": ["Luka Dončić"], "MIP": ["Pascal Siakam"], "6MOY": ["Lou Williams"], "FINALS_MVP": ["Kawhi Leonard"]},
    "2019-20": {"MVP": ["Giannis Antetokounmpo"], "DPOY": ["Giannis Antetokounmpo"], "ROY": ["Ja Morant"], "MIP": ["Brandon Ingram"], "6MOY": ["Montrezl Harrell"], "FINALS_MVP": ["LeBron James"]},
    "2020-21": {"MVP": ["Nikola Jokić"], "DPOY": ["Rudy Gobert"], "ROY": ["LaMelo Ball"], "MIP": ["Julius Randle"], "6MOY": ["Jordan Clarkson"], "FINALS_MVP": ["Giannis Antetokounmpo"]},
    "2021-22": {"MVP": ["Nikola Jokić"], "DPOY": ["Marcus Smart"], "ROY": ["Scottie Barnes"], "MIP": ["Ja Morant"], "6MOY": ["Tyler Herro"], "FINALS_MVP": ["Stephen Curry"]},
    "2022-23": {"MVP": ["Joel Embiid"], "DPOY": ["Jaren Jackson Jr."], "ROY": ["Paolo Banchero"], "MIP": ["Lauri Markkanen"], "6MOY": ["Malcolm Brogdon"], "FINALS_MVP": ["Nikola Jokić"]},
    # --- Saisons vérifiées par recherche web (voir note ci-dessus) ---
    "2023-24": {"MVP": ["Nikola Jokić"], "DPOY": ["Rudy Gobert"], "ROY": ["Victor Wembanyama"], "MIP": ["Tyrese Maxey"], "6MOY": ["Naz Reid"], "FINALS_MVP": ["Jaylen Brown"]},
    "2024-25": {"MVP": ["Shai Gilgeous-Alexander"], "DPOY": ["Evan Mobley"], "ROY": ["Stephon Castle"], "MIP": ["Dyson Daniels"], "6MOY": ["Payton Pritchard"], "FINALS_MVP": ["Shai Gilgeous-Alexander"]},
    "2025-26": {"MVP": ["Shai Gilgeous-Alexander"], "DPOY": ["Victor Wembanyama"], "ROY": ["Cooper Flagg"], "MIP": ["Nickeil Alexander-Walker"], "6MOY": ["Keldon Johnson"], "FINALS_MVP": ["Jalen Brunson"]},
}

# Champion NBA (abréviation d'équipe, format nba_api TEAM_ABBREVIATION) par saison -- séparé de
# SEASON_AWARDS car c'est une récompense COLLECTIVE (l'effectif entier du roster, ~15 joueurs, pas
# un lauréat individuel) : affiché comme un badge sur l'ÉQUIPE dans le classement, pas comme une
# icône sur un point individuel du nuage. Même politique de sourcing que SEASON_AWARDS (annonces
# officielles connues + vérification web pour 2023-24 → 2025-26).
CHAMPIONS_BY_SEASON: dict[str, str] = {
    "1996-97": "CHI", "1997-98": "CHI", "1998-99": "SAS", "1999-00": "LAL",
    "2000-01": "LAL", "2001-02": "LAL", "2002-03": "SAS", "2003-04": "DET",
    "2004-05": "SAS", "2005-06": "MIA", "2006-07": "SAS", "2007-08": "BOS",
    "2008-09": "LAL", "2009-10": "LAL", "2010-11": "DAL", "2011-12": "MIA",
    "2012-13": "MIA", "2013-14": "SAS", "2014-15": "GSW", "2015-16": "CLE",
    "2016-17": "GSW", "2017-18": "GSW", "2018-19": "TOR", "2019-20": "LAL",
    "2020-21": "MIL", "2021-22": "GSW", "2022-23": "DEN", "2023-24": "BOS",
    "2024-25": "OKC", "2025-26": "NYK",
}


@functools.lru_cache(maxsize=1)
def get_teams_static() -> list[dict]:
    """Liste statique des 30 franchises NBA actuelles -- nba_api.stats.static.teams, données
    embarquées dans le package (AUCUN appel réseau, contrairement au reste de ce module).
    Chaque entrée : id/abbreviation/full_name/nickname/city. Sert à construire les URLs de
    logos du CDN public NBA (pages/2_Effectifs.py) --
    https://cdn.nba.com/logos/nba/{id}/global/L/logo.svg.

    Abréviations D'AUJOURD'HUI uniquement : une franchise ayant changé de nom/ville depuis 1996
    (ex: Seattle SuperSonics -> Oklahoma City Thunder, Vancouver -> Memphis Grizzlies, New
    Jersey -> Brooklyn Nets) n'a qu'UNE entrée ici, sous son identité actuelle -- alors que la
    colonne "team" de get_player_stats reste l'abréviation HISTORIQUE réellement en usage cette
    saison-là (nba_api normalise season par season, voir _fetch_nba_api_stats). Ne pas s'en
    servir pour lister les équipes d'une saison : pages/2_Effectifs.py utilise les codes
    d'équipe de la saison (get_mercato_lineup/get_team_identity), et ses logos d'époque viennent
    d'une table locale (data_sources/nba_logos.csv), plus de cette liste.

    lru_cache (pas d'écriture disque via base.write_cache comme le reste du module) : purement
    statique et déjà instantané (aucun appel réseau), un cache disque n'apporterait rien."""
    from nba_api.stats.static import teams

    return teams.get_teams()


# À incrémenter chaque fois que la forme du DataFrame retourné par
# get_player_stats() change (colonne ajoutée/renommée/supprimée, logique de
# calcul modifiée). Un cache disque écrit sous une version différente est
# automatiquement ignoré et recalculé (voir base.read_cache/write_cache) —
# évite qu'un ancien cache reste silencieusement incomplet après un déploiement.
PROCESSED_SCHEMA_VERSION = 20  # v20: team = équipe du DERNIER match de saison régulière (game log, voir _with_final_game_team) au lieu de la dernière équipe d'inscription renvoyée par la NBA
# v19: retrait complet de la fonctionnalité salaire attendu/valeur ajoutée (expected_salary*, value_added* et toutes leurs variantes, is_rookie_scale, years_experience, impact_hors_scoring_zscore_poste) -- voir METHODOLOGY.md pour le pourquoi
# v18: plafond CBA indépendant sur expected_salary/value_added -- retiré en v19, mention gardée pour l'historique
# v15: ajout value_added_residual_std_pct_cap (bande d'incertitude de la trajectoire par joueur, Dashboard.py) -- colonne retirée en v19
# v14: extension historique 1996-97→2009-10 (dataset legacy) + colonnes salary_pct_cap/expected_salary_pct_cap/value_added_pct_cap -- les deux dernières retirées en v19
# v13: ajout value_added_residual_std_musd + fix base.read_cache qui laissait fuiter _schema_version (collision de merge possible sur un cache déjà écrit) -- colonne retirée en v19

# Même principe que PROCESSED_SCHEMA_VERSION, mais pour le cache brut intermédiaire de
# _fetch_nba_api_stats (avant fusion salaire). À incrémenter si les colonnes qu'elle renvoie
# changent (ex: ajout de player_id en v2, nécessaire pour joindre positions/fiabilité) — sinon
# un vieux cache brut resterait incomplet indéfiniment, même après un bump de
# PROCESSED_SCHEMA_VERSION, puisque c'est un cache distinct.
NBA_API_STATS_SCHEMA_VERSION = 2  # v2: ajout player_id

# Cache brut pour _fetch_nba_api_stats_playoffs (season_type_all_star="Playoffs") -- même schéma
# de colonnes que NBA_API_STATS_SCHEMA_VERSION, versionné séparément (cache dans un fichier
# différent, voir cache_suffix).
NBA_API_STATS_PLAYOFFS_SCHEMA_VERSION = 1

# Caches bruts pour _fetch_team_games_possible et _fetch_reliability (voir plus bas).
NBA_API_TEAM_GAMES_SCHEMA_VERSION = 1
NBA_API_RELIABILITY_SCHEMA_VERSION = 3  # v3: ne met plus en cache un résultat partiel (saison(s) manquante(s) suite à une erreur réseau)

# Cache brut pour _fetch_team_stats (bandeau classement des équipes de Dashboard.py).
NBA_API_TEAM_STATS_SCHEMA_VERSION = 1

# Cache brut pour _fetch_player_positions (voir plus bas).
NBA_API_POSITIONS_SCHEMA_VERSION = 1

# Cache brut pour _fetch_player_game_log (voir plus bas).
NBA_API_GAME_LOG_SCHEMA_VERSION = 2  # v2: ajout team_id/team_name (déjà renvoyés par
# LeagueGameLog, juste pas gardés avant) -- utilisés par get_team_identity, pas de second appel
# réseau nécessaire pour le nom d'équipe exact d'une saison (ex: "Charlotte Bobcats" en 2004-05
# vs "Charlotte Hornets" aujourd'hui, même team_id -- voir pages/2_Effectifs.py)

# Cache pour get_mercato_lineup (carte "Mercato" par équipe).
MERCATO_SCHEMA_VERSION = 4  # v4: troisième critère d'éligibilité -- un joueur établi (>= 25% de
# la saison TOUTES ÉQUIPES CONFONDUES) reste éligible dès MERCATO_MIN_GAMES_ESTABLISHED_PLAYER
# matchs avec son équipe de fin de saison, même s'il rate les deux critères existants (ex: Kevin
# Durant, Phoenix 2022-23, seulement 8 matchs à Phoenix après sa blessure post-transfert -- sous
# les deux seuils précédents malgré un statut de titulaire incontestable sur la saison)
# v3: éligibilité assouplie -- un joueur est aussi éligible s'il a
# joué >= 50% des matchs de son équipe depuis son arrivée (même si < 25% de la saison complète),
# pour ne pas exclure un titulaire tradé à la deadline (ex: Kyrie Irving à Dallas, 2022-23, ~20
# matchs sur les ~24 restants après son arrivée -- sous les 25% de la saison mais titulaire) --
# avec un plancher MERCATO_MIN_GAMES_SINCE_ARRIVAL pour ne pas rendre éligible un contrat de 10
# jours qui joue 3 des 4 derniers matchs de l'équipe
# v2: minutes/matchs recalculés PAR ÉQUIPE (_fetch_player_game_log) -- v1 utilisait les moyennes
# saison de get_player_stats, mélangeant les équipes d'un joueur transféré en cours de saison
# (ex: Hayward CHA+OKC 2023-24 ressortait à 24.4 min/match blend, alors qu'il ne tournait qu'à
# ~17 min/match une fois à OKC)

# Nombre minimum de matchs joués AVEC L'ÉQUIPE pour le second critère d'éligibilité (50% des
# matchs de l'équipe depuis l'arrivée du joueur, voir get_mercato_lineup) -- sans ce plancher, un
# contrat de 10 jours qui joue 3 des 4 derniers matchs de l'équipe (75% >= 50%) deviendrait
# éligible et pourrait entrer dans le top 5. Ne s'applique qu'à ce second critère : le premier
# (25% de la saison complète) n'a pas besoin d'un plancher séparé, il en impose déjà un de fait.
MERCATO_MIN_GAMES_SINCE_ARRIVAL = 10

# Nombre minimum de matchs joués AVEC L'ÉQUIPE DE FIN DE SAISON pour le troisième critère
# d'éligibilité (joueur "établi" sur la saison entière, toutes équipes confondues -- voir
# get_mercato_lineup) -- évite qu'un match unique joué juste avant la fin de saison (ex: retour
# de blessure sur le dernier match) suffise à rendre éligible un joueur par ailleurs éligible
# côté volume de saison.
MERCATO_MIN_GAMES_ESTABLISHED_PLAYER = 5

# Cache brut pour _load_legacy_kaggle_raw.
LEGACY_KAGGLE_SCHEMA_VERSION = 1

# Saisons couvertes par le sélecteur : 1996-97 (limite dure de nba_api, testée
# empiriquement — 0 ligne renvoyée avant, sans erreur) à 2025-26. Le salaire vient de
# ratin21 pour 2010-11+ et du dataset legacy avant (voir RATIN21_DATASET_START_YEAR) ;
# au-delà de 2025-26, les stats de jeu resteraient disponibles via nba_api mais le
# salaire/PER seraient à NaN tant que ratin21 n'est pas mis à jour par son auteur.
# KNOWN_SALARY_DATA_GAPS exclu par précaution (aucun effet actuel, les 2 saisons
# concernées sont hors de cette plage, mais coûte rien à garder si le périmètre bouge).
SEASONS = [
    s for s in (f"{y}-{str(y + 1)[-2:]}" for y in range(1996, 2026))
    if s not in KNOWN_SALARY_DATA_GAPS
][::-1]


class KaggleDatasetUnavailable(Exception):
    """Levée quand ni kagglehub ni un fichier manuel ne sont disponibles."""


class UnmatchedAwardWinner(Exception):
    """Levée par match_season_awards quand un lauréat de SEASON_AWARDS ne correspond à aucun
    joueur du DataFrame fourni pour cette saison — plutôt que de laisser une icône de récompense
    disparaître silencieusement (faute de correspondance) sans que ce soit visible nulle part."""


def match_season_awards(df: pd.DataFrame, season: str) -> dict[str, list[str]]:
    """Rapproche les lauréats SEASON_AWARDS[season] avec la colonne `player` de `df` (le
    DataFrame retourné par get_player_stats(season)), via normalize_name (base.py : accents,
    casse, suffixes Jr./Sr./II/III/IV, ponctuation) plutôt qu'une comparaison exacte de chaîne —
    même logique déjà utilisée pour la jointure des salaires Kaggle.

    Retourne {award: [nom(s) EXACT(S) tel(s) qu'orthographié(s) dans df["player"], ...]} — pas
    l'orthographe de SEASON_AWARDS, pour permettre un filtre direct type
    `df["player"].isin(matched["MVP"])` par l'appelant. Saison sans récompenses connues (hors
    SEASON_AWARDS, ex. si la couverture est étendue plus tard) -> dict vide, pas d'erreur.

    Lève UnmatchedAwardWinner si un lauréat connu ne trouve AUCUNE correspondance dans `df` pour
    cette saison (orthographe différente entre SEASON_AWARDS et nba_api, ou joueur absent du
    dataset) : mieux vaut un échec bruyant, détecté par le script de vérification ou l'appelant,
    qu'une icône manquante sans qu'on sache pourquoi. N'utilise PAS un match approximatif
    (fuzzy) au-delà de normalize_name — un vrai homonyme donnerait un faux positif silencieux,
    pire qu'un faux négatif bruyant."""
    awards = SEASON_AWARDS.get(season, {})
    if not awards or "player" not in df.columns:
        return {}
    df_keys = df["player"].map(normalize_name)
    result: dict[str, list[str]] = {}
    for award, winners in awards.items():
        matched_names: list[str] = []
        for winner in winners:
            key = normalize_name(winner)
            matches = df.loc[df_keys == key, "player"].unique().tolist()
            if not matches:
                raise UnmatchedAwardWinner(
                    f"{season} {award} : aucun joueur ne correspond à '{winner}' (clé normalisée "
                    f"'{key}') dans le dataset de cette saison. Vérifie l'orthographe dans "
                    f"SEASON_AWARDS, ou l'absence réelle du joueur pour cette saison."
                )
            matched_names.extend(matches)
        result[award] = matched_names
    return result


# Icônes et libellés d'affichage pour les codes de récompenses de SEASON_AWARDS — ordre
# d'insertion volontaire (MVP, DPOY, ROY, MIP, 6MOY, FINALS_MVP), réutilisé par Dashboard.py pour
# construire le badge composite dans un ordre stable quand un joueur cumule plusieurs récompenses
# la même saison (ex. SGA 2024-25 : MVP + Finals MVP -> "👑🎖️", pas l'inverse selon l'ordre
# d'itération d'un dict non garanti). Choisies pour ne pas réutiliser une icône déjà présente
# ailleurs dans le dashboard : 🏆 reste exclusif au badge d'équipe championne (CHAMPIONS_BY_SEASON,
# récompense collective), ⚠️/◆ à l'échantillon court, 📈/📊/🔍 aux titres de section.
AWARD_ICONS: dict[str, str] = {
    "MVP": "👑",
    "DPOY": "🛡️",
    "ROY": "🌟",
    "MIP": "🚀",
    "6MOY": "🔥",
    "FINALS_MVP": "🎖️",
}
AWARD_LABELS: dict[str, str] = {
    "MVP": "MVP",
    "DPOY": "Défenseur de l'année",
    "ROY": "Rookie de l'année",
    "MIP": "Progression de l'année",
    "6MOY": "Sixième homme de l'année",
    "FINALS_MVP": "MVP des Finales",
}


def get_award_badges(df: pd.DataFrame) -> pd.Series:
    """Version multi-saisons de match_season_awards : pour un DataFrame `df` couvrant une ou
    plusieurs saisons (colonnes `season` + `player`, ex. plot_df de Dashboard.py, en saison unique ou en
    mode "Toutes les saisons"), retourne une Series alignée sur df.index où chaque valeur est la
    LISTE (éventuellement vide) des codes de récompenses gagnées par ce joueur cette saison-là,
    dans l'ordre AWARD_ICONS.

    Propage UnmatchedAwardWinner si une saison présente dans `df` a un lauréat SEASON_AWARDS
    introuvable (voir match_season_awards) — même principe de non-silence, pas de dégradation
    silencieuse même appelé depuis l'UI."""
    result = pd.Series([[] for _ in range(len(df))], index=df.index, dtype=object)
    if "season" not in df.columns or "player" not in df.columns:
        return result
    for season, season_df in df.groupby("season"):
        matched = match_season_awards(season_df, season)
        if not matched:
            continue
        for award in AWARD_ICONS:  # ordre stable, pas l'ordre d'itération de `matched`
            names = matched.get(award)
            if not names:
                continue
            for i in season_df.index[season_df["player"].isin(names)]:
                result.at[i] = result.at[i] + [award]
    return result


# --------------------------------------------------------------------------
# Catalogue des métriques sélectionnables en X / Y dans le dashboard.
# --------------------------------------------------------------------------
METRICS: dict[str, Metric] = {
    "points_per_game": Metric("points_per_game", "Points par match", ",.1f", "Volume"),
    "rebounds_per_game": Metric("rebounds_per_game", "Rebonds par match", ",.1f", "Volume"),
    "assists_per_game": Metric("assists_per_game", "Passes décisives par match", ",.1f", "Volume"),
    "steals_per_game": Metric("steals_per_game", "Interceptions par match", ",.1f", "Volume"),
    "blocks_per_game": Metric("blocks_per_game", "Contres par match", ",.1f", "Volume"),
    "turnovers_per_game": Metric("turnovers_per_game", "Pertes de balle par match", ",.1f", "Volume"),
    "minutes_per_game": Metric("minutes_per_game", "Minutes jouées par match", ",.1f", "Volume"),
    "games_played": Metric("games_played", "Matchs joués", ",.0f", "Volume"),
    "fg_pct": Metric("fg_pct", "% Réussite au tir (FG%)", ".1%", "Efficacité"),
    "fg3_pct": Metric("fg3_pct", "% Réussite à 3 points", ".1%", "Efficacité"),
    "ft_pct": Metric("ft_pct", "% Réussite aux lancers francs", ".1%", "Efficacité"),
    "ts_pct": Metric("ts_pct", "True Shooting % (TS%)", ".1%", "Efficacité"),
    "usg_pct": Metric("usg_pct", "Usage Rate (USG%)", ".1%", "Efficacité"),
    "pie": Metric("pie", "PIE (Player Impact Estimate)", ".3f", "Efficacité"),
    "plus_minus": Metric("plus_minus", "+/- par match", ",.1f", "Efficacité"),
    "impact_hors_scoring": Metric("impact_hors_scoring", "Impact hors scoring (reb+ctr+pd+int par match)", ",.1f", "Efficacité"),
    "salary_musd": Metric("salary_musd", "Salaire (M$)", ",.2f", "Salaire"),
    "salary_pct_cap": Metric("salary_pct_cap", "Salaire (% du plafond)", ".1%", "Salaire"),
    "reliability_pct": Metric(
        "reliability_pct", "Fiabilité (% matchs joués, 3 dernières saisons)", ".1%", "Fiabilité"
    ),
}
# Remarque : le dataset Kaggle utilisé (ratin21/nba-player-stats-and-salaries-2010-2025)
# fournit Player/Salary/Year mais pas de colonne PER — d'où l'usage du PIE (nba_api,
# toujours disponible) comme métrique d'efficacité/valeur plutôt que le PER historique
# de Basketball-Reference. _resolve_kaggle_columns() garde un alias "per" au cas où une
# future version du dataset l'ajouterait ; la colonne resterait alors NaN sans casser rien.

# Catalogue dédié au bandeau "classement des équipes" (Dashboard.py) -- volontairement
# séparé de METRICS ci-dessus : uniquement des stats d'ÉQUIPE réelles (_fetch_team_stats)
# ou agrégées par équipe (masse salariale), pas le catalogue joueurs entier.
TEAM_RANKING_METRICS: dict[str, Metric] = {
    "pts_per_game": Metric("pts_per_game", "Points par match", ",.1f", "Volume"),
    "reb_per_game": Metric("reb_per_game", "Rebonds par match", ",.1f", "Volume"),
    "ast_per_game": Metric("ast_per_game", "Passes décisives par match", ",.1f", "Volume"),
    "stl_per_game": Metric("stl_per_game", "Interceptions par match", ",.1f", "Volume"),
    "blk_per_game": Metric("blk_per_game", "Contres par match", ",.1f", "Volume"),
    "fg_pct": Metric("fg_pct", "% Réussite au tir (FG%)", ".1%", "Efficacité"),
    "fg3_pct": Metric("fg3_pct", "% Réussite à 3 points", ".1%", "Efficacité"),
    "ft_pct": Metric("ft_pct", "% Réussite aux lancers francs", ".1%", "Efficacité"),
    "pie": Metric("pie", "PIE équipe (Player Impact Estimate agrégé)", ".3f", "Efficacité"),
    "salary_total_musd": Metric("salary_total_musd", "Masse salariale totale (M$)", ",.1f", "Salaire"),
}


# --------------------------------------------------------------------------
# Source 1 : nba_api (stats de jeu, en direct)
# --------------------------------------------------------------------------
def _fetch_nba_api_stats(
    season: str, force_refresh: bool = False,
    season_type: str = "Regular Season", cache_suffix: str = "",
) -> pd.DataFrame:
    """Retourne les stats per-game (base + advanced) d'une saison via nba_api,
    normalisées sur le schéma commun. Mis en cache par saison.

    `season_type`/`cache_suffix` : paramétrables pour réutiliser cette même fonction pour les
    playoffs (voir _fetch_nba_api_stats_playoffs) sans dupliquer la logique — par défaut,
    comportement et emplacement de cache strictement identiques à avant (saison régulière,
    cache_suffix="" -> data_cache/raw/nba/nba_api/<season>.parquet)."""
    raw_cache_path = NBA_RAW_DIR / "nba_api" / f"{season}{cache_suffix}.parquet"
    cached = None if force_refresh else read_cache(raw_cache_path, schema_version=NBA_API_STATS_SCHEMA_VERSION)
    if cached is not None:
        return cached

    # Import différé : nba_api n'est nécessaire que si on va effectivement
    # chercher des données en direct (permet à l'app de démarrer même si
    # le package n'est pas encore installé, avec un message clair).
    from nba_api.stats.endpoints import leaguedashplayerstats

    common_kwargs = dict(
        season=season,
        season_type_all_star=season_type,
        per_mode_detailed="PerGame",
    )
    base = leaguedashplayerstats.LeagueDashPlayerStats(
        measure_type_detailed_defense="Base", **common_kwargs
    ).get_data_frames()[0]
    advanced = leaguedashplayerstats.LeagueDashPlayerStats(
        measure_type_detailed_defense="Advanced", **common_kwargs
    ).get_data_frames()[0]

    adv_cols = ["PLAYER_ID", "TS_PCT", "USG_PCT", "PIE"]
    merged = base.merge(advanced[adv_cols], on="PLAYER_ID", how="left")

    rename_map = {
        "PLAYER_ID": "player_id",
        "PLAYER_NAME": "player",
        "TEAM_ABBREVIATION": "team",
        "GP": "games_played",
        "MIN": "minutes_per_game",
        "PTS": "points_per_game",
        "REB": "rebounds_per_game",
        "AST": "assists_per_game",
        "STL": "steals_per_game",
        "BLK": "blocks_per_game",
        "TOV": "turnovers_per_game",
        "FG_PCT": "fg_pct",
        "FG3_PCT": "fg3_pct",
        "FT_PCT": "ft_pct",
        "TS_PCT": "ts_pct",
        "USG_PCT": "usg_pct",
        "PIE": "pie",
        "PLUS_MINUS": "plus_minus",
    }
    normalized = merged.rename(columns=rename_map)[list(rename_map.values())]

    write_cache(normalized, raw_cache_path, schema_version=NBA_API_STATS_SCHEMA_VERSION)
    return normalized


def _fetch_nba_api_stats_playoffs(season: str, force_refresh: bool = False) -> pd.DataFrame:
    """Version playoffs de _fetch_nba_api_stats (mêmes colonnes, même schéma) --
    season_type_all_star="Playoffs". Cache séparé (fichier "<season>_playoffs.parquet") : un
    joueur/une équipe non qualifiée n'a pas de ligne, ce n'est pas une absence de données, juste
    l'absence de participation aux playoffs cette saison-là.

    Disponibilité vérifiée sur les 30 saisons (1996-97 -> 2025-26, voir le diagnostic de
    faisabilité playoffs) : mêmes champs que la saison régulière (PIE compris, toujours
    renseigné), aucun trou de couverture -- seulement la même sensibilité au rate-limiting
    ponctuel de stats.nba.com que le reste des appels nba_api de ce fichier (déjà couverte par
    _call_with_retries là où c'est critique)."""
    return _fetch_nba_api_stats(season, force_refresh=force_refresh, season_type="Playoffs", cache_suffix="_playoffs")


def _call_with_retries(fn, description: str, attempts: int = NETWORK_RETRY_ATTEMPTS,
                        backoff_seconds: float = NETWORK_RETRY_BACKOFF_SECONDS):
    """Exécute `fn()` avec quelques tentatives et un court backoff avant d'abandonner — utile
    pour un appel réseau ponctuel et flaky (timeout) plutôt qu'une vraie panne persistante.
    Relance la dernière exception rencontrée si toutes les tentatives échouent."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                logger.warning(
                    "%s : tentative %d/%d échouée (%s), nouvel essai dans %.1fs.",
                    description, attempt, attempts, exc, backoff_seconds,
                )
                time.sleep(backoff_seconds)
    raise last_exc


def _fetch_player_positions(season: str, force_refresh: bool = False) -> pd.DataFrame:
    """Regroupe chaque joueur en 3 postes simples (Intérieur/Ailier/Extérieur) via le filtre
    officiel `player_position_abbreviation_nullable` de nba_api (C/F/G) — 3 appels groupés par
    saison, pas un par joueur. Utilisé par le radar de comparaison (voir compute_radar_scores)
    pour normaliser certains axes par poste plutôt qu'en absolu ; n'est pas exposé dans le
    catalogue METRICS ni comme colonne affichée directement dans l'UI.

    Un joueur au poste hybride (ex: "F-C") peut apparaître dans plusieurs des 3 requêtes selon
    la saison/l'équipe — on garde alors la première catégorie rencontrée, dans l'ordre C > F > G
    (priorité au poste le plus "intérieur" en cas d'ambiguïté, cohérent avec le diagnostic qui
    avait classé les joueurs ainsi)."""
    raw_cache_path = NBA_RAW_DIR / "nba_api" / f"positions_{season}.parquet"
    cached = None if force_refresh else read_cache(raw_cache_path, schema_version=NBA_API_POSITIONS_SCHEMA_VERSION)
    if cached is not None:
        return cached

    from nba_api.stats.endpoints import leaguedashplayerstats

    label_map = {"C": "Intérieur", "F": "Ailier", "G": "Extérieur"}
    rows = []
    for pos, label in label_map.items():
        d = _call_with_retries(
            lambda pos=pos: leaguedashplayerstats.LeagueDashPlayerStats(
                season=season, season_type_all_star="Regular Season", per_mode_detailed="PerGame",
                measure_type_detailed_defense="Base", player_position_abbreviation_nullable=pos,
            ).get_data_frames()[0],
            description=f"_fetch_player_positions({season}, poste={pos})",
        )
        for pid in d["PLAYER_ID"]:
            rows.append({"player_id": pid, "position_group": label})

    result = pd.DataFrame(rows, columns=["player_id", "position_group"]).drop_duplicates(
        subset="player_id", keep="first"
    )
    write_cache(result, raw_cache_path, schema_version=NBA_API_POSITIONS_SCHEMA_VERSION)
    return result


def _seasons_lookback(season: str, n: int) -> list[str]:
    """Retourne `season` et les (n-1) saisons précédentes, la plus récente en
    premier, en s'arrêtant à EARLIEST_SUPPORTED_SEASON_START_YEAR plutôt que de
    produire une saison invalide. Une recrue n'aura donc que 1 ou 2 saisons
    dans la liste plutôt que de faire planter l'appelant."""
    start_year = int(season[:4])
    seasons = []
    for i in range(n):
        y = start_year - i
        if y < EARLIEST_SUPPORTED_SEASON_START_YEAR:
            break
        seasons.append(f"{y}-{str(y + 1)[-2:]}")
    return seasons


def _fetch_team_games_possible(season: str, force_refresh: bool = False) -> int:
    """Nombre de matchs "possibles" pour une équipe sur la saison régulière,
    déduit du nombre réel de matchs joués par l'équipe qui en a joué le plus
    (nba_api, endpoint LeagueDashTeamStats — un seul appel groupé). Plus
    fiable que de supposer 82 : certaines saisons sont raccourcies (lockout
    2011-12 : 66 matchs : COVID 2019-20 : 64-75 matchs selon l'équipe ;
    2020-21 : 72 matchs)."""
    raw_cache_path = NBA_RAW_DIR / "nba_api" / f"team_games_{season}.parquet"
    cached = None if force_refresh else read_cache(raw_cache_path, schema_version=NBA_API_TEAM_GAMES_SCHEMA_VERSION)
    if cached is not None:
        return int(cached["games_possible"].iloc[0])

    from nba_api.stats.endpoints import leaguedashteamstats

    team_stats = leaguedashteamstats.LeagueDashTeamStats(
        season=season, season_type_all_star="Regular Season", per_mode_detailed="Totals"
    ).get_data_frames()[0]
    games_possible = int(pd.to_numeric(team_stats["GP"], errors="coerce").max())

    result = pd.DataFrame({"games_possible": [games_possible]})
    write_cache(result, raw_cache_path, schema_version=NBA_API_TEAM_GAMES_SCHEMA_VERSION)
    return games_possible


# Stats de VOLUME/TIR (measure_type "Base") + PIE équipe (measure_type "Advanced", même
# formule que le PIE joueur mais appliquée aux totaux d'équipe -- corrélation mesurée à 0.96
# avec le win% sur 2023-24, un vrai signal de niveau global d'équipe, pas un bricolage)
# retenues pour le bandeau "classement des équipes" de Dashboard.py, via _fetch_team_stats.
TEAM_STATS_MEASURE_COLS = {
    "Base": ["PTS", "REB", "AST", "STL", "BLK", "FG_PCT", "FG3_PCT", "FT_PCT"],
    "Advanced": ["PIE"],
}


def _fetch_team_stats(season: str, period: str = "regular", force_refresh: bool = False) -> pd.DataFrame:
    """Vraies stats d'ÉQUIPE par match (nba_api, LeagueDashTeamStats -- même endpoint que
    _fetch_team_games_possible), PAS une moyenne des joueurs actuellement affichés/filtrés
    dans le scatter plot. `period` ("regular" ou "playoffs") pilote season_type_all_star,
    indépendamment du mode saison régulière/playoffs du scatter plot au-dessus dans
    Dashboard.py -- une équipe non qualifiée n'a simplement pas de ligne en mode playoffs.

    LeagueDashTeamStats ne renvoie que TEAM_ID/TEAM_NAME, pas d'abréviation d'équipe
    (contrairement à LeagueDashPlayerStats qui a TEAM_ABBREVIATION) -- et TEAM_NAME n'est pas
    fiable pour reconstruire l'abréviation nous-mêmes sur les saisons anciennes (franchises
    renommées/déménagées : ex. l'abréviation nba_api pour Washington ressort "WAS" pour
    1996-97 alors que TEAM_NAME affiche encore "Washington Bullets"). Un second appel léger à
    LeagueDashPlayerStats (déjà utilisé ailleurs, ici seulement pour la paire TEAM_ID/
    TEAM_ABBREVIATION de cette même saison) sert de table de correspondance, garantie
    cohérente avec la colonne "team" du reste du pipeline (_fetch_nba_api_stats)."""
    season_type = "Playoffs" if period == "playoffs" else "Regular Season"
    raw_cache_path = NBA_RAW_DIR / "nba_api" / f"team_stats_{season}_{period}.parquet"
    cached = None if force_refresh else read_cache(raw_cache_path, schema_version=NBA_API_TEAM_STATS_SCHEMA_VERSION)
    if cached is not None:
        return cached

    from nba_api.stats.endpoints import leaguedashplayerstats, leaguedashteamstats

    common_kwargs = dict(season=season, season_type_all_star=season_type, per_mode_detailed="PerGame")
    merged = None
    for measure_type, cols in TEAM_STATS_MEASURE_COLS.items():
        raw = leaguedashteamstats.LeagueDashTeamStats(
            measure_type_detailed_defense=measure_type, **common_kwargs
        ).get_data_frames()[0][["TEAM_ID"] + cols]
        merged = raw if merged is None else merged.merge(raw, on="TEAM_ID", how="outer")

    team_abbrev = leaguedashplayerstats.LeagueDashPlayerStats(
        measure_type_detailed_defense="Base", **common_kwargs
    ).get_data_frames()[0][["TEAM_ID", "TEAM_ABBREVIATION"]].drop_duplicates()
    merged = merged.merge(team_abbrev, on="TEAM_ID", how="inner")  # exclut les lignes "TOT"/agrégats éventuels

    rename_map = {
        "TEAM_ABBREVIATION": "team",
        "PTS": "pts_per_game", "REB": "reb_per_game", "AST": "ast_per_game",
        "STL": "stl_per_game", "BLK": "blk_per_game",
        "FG_PCT": "fg_pct", "FG3_PCT": "fg3_pct", "FT_PCT": "ft_pct",
        "PIE": "pie",
    }
    result = merged.rename(columns=rename_map)[list(rename_map.values())]

    write_cache(result, raw_cache_path, schema_version=NBA_API_TEAM_STATS_SCHEMA_VERSION)
    return result


def _fetch_reliability(season: str, force_refresh: bool = False) -> tuple[pd.DataFrame, bool]:
    """Calcule, pour chaque joueur, `reliability_pct` = (somme de ses matchs
    joués) / (somme des matchs possibles de la ligue) sur `season` et les
    RELIABILITY_LOOKBACK_SEASONS-1 saisons précédentes disponibles. Une
    recrue avec moins de saisons d'historique n'est simplement sommée que sur
    les saisons où elle a effectivement joué (voir _seasons_lookback), plutôt
    que de planter ou de produire une valeur fausse. Mis en cache par saison
    (la fenêtre de 3 saisons regardée dépend de la saison demandée).

    Retourne (résultat, complet) : `complet` est False si au moins une saison de la fenêtre
    n'a pas pu être récupérée -- le résultat est alors partiel (dénominateur trop petit, valeurs
    faussées) et l'appelant ne doit ni l'afficher ni le persister (voir get_player_stats)."""
    raw_cache_path = NBA_RAW_DIR / "nba_api" / f"reliability_{season}.parquet"
    cached = None if force_refresh else read_cache(raw_cache_path, schema_version=NBA_API_RELIABILITY_SCHEMA_VERSION)
    if cached is not None:
        return cached, True  # seul un résultat complet est jamais écrit dans ce cache (voir plus bas)

    target_seasons = _seasons_lookback(season, RELIABILITY_LOOKBACK_SEASONS)
    frames = []
    for s in target_seasons:
        try:
            stats_s = _fetch_nba_api_stats(s, force_refresh=force_refresh)[["player_id", "games_played"]].copy()
            games_possible = _fetch_team_games_possible(s, force_refresh=force_refresh)
        except Exception as exc:
            logger.warning("Fiabilité : saison %s indisponible (utilisée pour %s) : %s", s, season, exc)
            continue
        stats_s["games_possible"] = games_possible
        frames.append(stats_s)

    if not frames:
        return pd.DataFrame(columns=["player_id", "reliability_pct"]), False

    combined = pd.concat(frames, ignore_index=True)
    agg = combined.groupby("player_id", as_index=False)[["games_played", "games_possible"]].sum()
    # Plafonné à 100% : constaté à l'usage, quelques joueurs ressortent légèrement au-dessus
    # (~100.4%), vraisemblablement les matchs de Play-In comptés côté LeagueDashPlayerStats
    # mais pas dans le max de LeagueDashTeamStats utilisé comme "matchs possibles". Un joueur
    # "fiable à 104%" n'a pas de sens à afficher tel quel.
    agg["reliability_pct"] = (agg["games_played"] / agg["games_possible"]).clip(upper=1.0)
    result = agg[["player_id", "reliability_pct"]]

    # Ne met en cache que si TOUTES les saisons visées ont pu être récupérées. Un résultat
    # partiel (ex: timeout réseau sur 2 des 3 saisons) ne doit pas être persisté tel quel : il
    # resterait "valide" indéfiniment vis-à-vis du schema_version (le code n'a pas changé, donc
    # rien ne le distinguerait d'un vrai résultat complet), privant silencieusement des joueurs
    # (ex: ceux absents des saisons qui ont échoué) de leur métrique à chaque rechargement
    # suivant. Le résultat partiel est quand même retourné, signalé par complete=False, sans être
    # gravé sur disque.
    complete = len(frames) == len(target_seasons)
    if complete:
        write_cache(result, raw_cache_path, schema_version=NBA_API_RELIABILITY_SCHEMA_VERSION)
    else:
        logger.warning(
            "Fiabilité pour %s : résultat partiel (%d/%d saisons), non mis en cache.",
            season, len(frames), len(target_seasons),
        )
    return result, complete


# --------------------------------------------------------------------------
# Source 2 : dataset Kaggle (salaires + PER)
# --------------------------------------------------------------------------
def _download_kaggle_dataset(slug: str) -> Path:
    """Télécharge (ou récupère depuis le cache kagglehub) un dataset Kaggle et
    retourne le dossier local contenant ses fichiers. Générique : utilisé pour
    le dataset ratin21 (2010-2025) et le dataset legacy 1985-2018 (voir plus
    bas), tous deux publics et téléchargeables sans identifiants (vérifié à
    l'usage pour les deux).

    Des identifiants Kaggle gratuits (compte Kaggle -> Settings -> "Create New
    API Token" -> ~/.kaggle/kaggle.json, ou variables d'environnement
    KAGGLE_USERNAME / KAGGLE_KEY) peuvent être nécessaires si Kaggle change sa
    politique d'accès anonyme ; sans ça, on bascule sur le fallback manuel.
    """
    import kagglehub

    return Path(kagglehub.dataset_download(slug))


def _find_manual_csv(directory: Path) -> Path | None:
    """Fallback sans authentification : l'utilisateur télécharge le zip
    depuis la page Kaggle du dataset et dépose le(s) CSV dans `directory`."""
    candidates = sorted(glob.glob(str(directory / "*.csv")))
    return Path(candidates[0]) if candidates else None


def _load_kaggle_raw(force_refresh: bool = False) -> pd.DataFrame:
    """Charge le CSV Kaggle brut (ratin21, saisons 2010-11+ — voir
    RATIN21_DATASET_START_YEAR) via kagglehub ou fallback manuel, le met en
    cache en parquet, et retourne le DataFrame tel quel (colonnes d'origine,
    non renommées -> voir _extract_kaggle_season)."""
    cached = None if force_refresh else read_cache(KAGGLE_RAW_CACHE)
    if cached is not None:
        return cached

    csv_path: Path | None = None
    try:
        dataset_dir = _download_kaggle_dataset(KAGGLE_DATASET_SLUG)
        csvs = sorted(dataset_dir.glob("*.csv"))
        if csvs:
            csv_path = csvs[0]
    except Exception as exc:  # kagglehub non configuré, pas d'internet, etc.
        logger.warning("Téléchargement kagglehub impossible (%s), tentative fallback manuel.", exc)

    if csv_path is None:
        csv_path = _find_manual_csv(MANUAL_FALLBACK_DIR)

    if csv_path is None:
        raise KaggleDatasetUnavailable(
            "Impossible de charger le dataset Kaggle de salaires/PER.\n"
            "Option A (auto) : configure des identifiants Kaggle gratuits "
            "(compte -> Settings -> Create New API Token -> "
            "~/.kaggle/kaggle.json) puis relance.\n"
            f"Option B (manuel) : télécharge le CSV depuis "
            f"https://www.kaggle.com/datasets/{KAGGLE_DATASET_SLUG} et "
            f"dépose-le dans {MANUAL_FALLBACK_DIR}/"
        )

    df = pd.read_csv(csv_path)
    write_cache(df, KAGGLE_RAW_CACHE)
    return df


def _load_legacy_kaggle_raw(force_refresh: bool = False) -> pd.DataFrame:
    """Charge le dataset Kaggle "legacy" (iampunitkmryh/nba-players-details-
    198518, licence CC0, saisons 1996-97 à 2009-10 — voir
    RATIN21_DATASET_START_YEAR pour la frontière avec ratin21), le met en
    cache, et retourne un DataFrame déjà au format attendu par
    _resolve_kaggle_columns/_extract_kaggle_season (colonnes Player/Salary/
    Season) pour réutiliser cette logique telle quelle plutôt que de la
    dupliquer.

    Ce dataset a deux fichiers distincts (contrairement à ratin21) :
    salaries_1985to2018.csv (player_id/salary/season, pas de nom de joueur en
    clair) et players.csv (player_id -> name, bio) — fusionnés ici sur
    player_id. Sa colonne "season" est déjà au format "1996-97" (contrairement
    à ratin21 qui n'a qu'une année numérique) : pas besoin du fallback "année
    la plus proche", un match exact suffit (voir _extract_kaggle_season).

    Connu et documenté : ce dataset a un trou de couverture sur 1986-87 et
    1989-90 (voir KNOWN_SALARY_DATA_GAPS) — hors de la plage réellement
    utilisée ici (1996-97+, limite nba_api) donc sans impact concret, mais la
    liste est conservée si le périmètre bouge encore."""
    cached = None if force_refresh else read_cache(LEGACY_KAGGLE_RAW_CACHE, schema_version=LEGACY_KAGGLE_SCHEMA_VERSION)
    if cached is not None:
        return cached

    dataset_dir: Path | None = None
    try:
        dataset_dir = _download_kaggle_dataset(LEGACY_KAGGLE_DATASET_SLUG)
    except Exception as exc:
        logger.warning("Téléchargement kagglehub (legacy) impossible (%s), tentative fallback manuel.", exc)

    salaries_path = (dataset_dir / "salaries_1985to2018.csv") if dataset_dir else None
    players_path = (dataset_dir / "players.csv") if dataset_dir else None
    if not (salaries_path and salaries_path.exists() and players_path and players_path.exists()):
        salaries_path = LEGACY_MANUAL_FALLBACK_DIR / "salaries_1985to2018.csv"
        players_path = LEGACY_MANUAL_FALLBACK_DIR / "players.csv"

    if not (salaries_path.exists() and players_path.exists()):
        raise KaggleDatasetUnavailable(
            "Impossible de charger le dataset Kaggle legacy de salaires (1996-97 à 2009-10).\n"
            "Option A (auto) : configure des identifiants Kaggle gratuits (voir README).\n"
            "Option B (manuel) : télécharge salaries_1985to2018.csv ET players.csv depuis "
            f"https://www.kaggle.com/datasets/{LEGACY_KAGGLE_DATASET_SLUG} et "
            f"dépose les deux dans {LEGACY_MANUAL_FALLBACK_DIR}/"
        )

    salaries = pd.read_csv(salaries_path)
    players = pd.read_csv(players_path)
    merged = salaries.merge(players[["_id", "name"]], left_on="player_id", right_on="_id", how="left")
    df = merged.rename(columns={"name": "Player", "salary": "Salary", "season": "Season"})[
        ["Player", "Salary", "Season"]
    ]
    write_cache(df, LEGACY_KAGGLE_RAW_CACHE, schema_version=LEGACY_KAGGLE_SCHEMA_VERSION)
    return df


def _resolve_kaggle_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Détecte les noms de colonnes réels du CSV Kaggle (peuvent varier
    légèrement selon la version publiée) parmi une liste d'alias connus."""
    aliases = {
        "player": ["Player", "player", "Name", "PLAYER"],
        "salary": ["Salary", "salary", "SALARY"],
        "season_str": ["Season", "season"],  # ex "2023-24" si déjà présent
        "year": ["Year", "year", "YEAR"],     # sinon année numérique
        "per": ["PER", "per"],
    }
    resolved: dict[str, str | None] = {}
    for key, candidates in aliases.items():
        resolved[key] = next((c for c in candidates if c in df.columns), None)
    return resolved


def _extract_kaggle_season(kaggle_df: pd.DataFrame, season: str, max_year_gap: int = 2) -> pd.DataFrame:
    """Extrait les salaires du dataset Kaggle brut pour la saison demandée et
    retourne un DataFrame à colonnes normalisées : player_kaggle, salary, per,
    _key (nom normalisé, pour la jointure), salary_is_estimated.

    Le dataset (constaté à l'usage) a des trous : certains joueurs n'ont pas
    de ligne pour l'année exacte demandée alors qu'ils en ont pour les années
    voisines (probablement lié à la façon dont HoopsHype liste les contrats
    pluriannuels). Plutôt que de perdre ces joueurs, on retombe sur l'année la
    plus proche disponible (jusqu'à `max_year_gap` ans d'écart) et on marque
    la ligne `salary_is_estimated=True` pour que l'UI puisse le signaler.

    Le format de la colonne saison varie selon les versions du dataset
    (chaîne "2023-24" ou année numérique unique -- vérifié empiriquement :
    "Year" = année de FIN de saison, ex. Year=2010 pour la saison 2009-10).
    """
    cols = _resolve_kaggle_columns(kaggle_df)
    if cols["player"] is None or cols["salary"] is None:
        raise KaggleDatasetUnavailable(
            "Le CSV Kaggle chargé n'a pas les colonnes attendues (Player/Salary). "
            "Vérifie le fichier dans data_cache/raw/nba/ ou ajuste les alias "
            "dans _resolve_kaggle_columns()."
        )

    working = pd.DataFrame(
        {
            "player_kaggle": kaggle_df[cols["player"]],
            "salary": pd.to_numeric(kaggle_df[cols["salary"]], errors="coerce"),
        }
    )
    working["_key"] = working["player_kaggle"].map(normalize_name)
    working["per"] = pd.to_numeric(kaggle_df[cols["per"]], errors="coerce") if cols["per"] is not None else np.nan

    if cols["season_str"] is not None:
        # Format "2023-24" déjà présent : pas de notion de "proximité", on ne
        # garde que le match exact.
        exact = kaggle_df[cols["season_str"]].astype(str).str.strip() == season
        result = working[exact.values].copy()
        result["salary_is_estimated"] = False
        return result.drop_duplicates(subset="_key", keep="first")

    if cols["year"] is None:
        return working.iloc[0:0].assign(salary_is_estimated=pd.Series(dtype=bool))

    start_year = int(season[:4])
    target_year = start_year + 1  # convention "Year = fin de saison", confirmée empiriquement
    year_col = pd.to_numeric(kaggle_df[cols["year"]], errors="coerce")
    working["_year_gap"] = (year_col - target_year).abs()

    candidates = working[working["_year_gap"] <= max_year_gap].sort_values("_year_gap")
    nearest_per_player = candidates.drop_duplicates(subset="_key", keep="first").copy()
    nearest_per_player["salary_is_estimated"] = nearest_per_player["_year_gap"] > 0
    return nearest_per_player.drop(columns="_year_gap")


# --------------------------------------------------------------------------
# Mode playoffs (get_player_stats(..., period=...)) :
#   - "regular" (défaut, comportement inchangé) : saison régulière seule, comme avant.
#   - "playoffs" : stats playoffs SEULES (pas de moyenne).
# Le salaire réel (salary_musd/salary_pct_cap) reste TOUJOURS celui de la saison régulière dans
# les 2 cas : c'est le seul qui existe réellement, les playoffs ne sont pas rémunérés à part.
#
# Un 3e mode a existé ("regular_playoffs" : stats combinées saison+playoffs en moyenne pondérée
# par le total de matchs) puis a été retiré (décision explicite) : mélanger un échantillon
# cohérent (saison régulière, 82 matchs pour tout le monde) avec un échantillon non représentatif
# (playoffs, biaisé par qui se qualifie et jusqu'où) n'apportait pas assez de valeur pour la
# complexité ajoutée. La fonction qui le calculait (_combine_regular_playoffs_stats) a été
# supprimée -- PLAYOFF_PERIOD_STAT_COLS ci-dessous reste nécessaire, toujours utilisée par
# _substitute_playoffs_only_stats (mode "playoffs").

# Colonnes de stats "par période" (substituées selon `period`) — le reste d'une ligne (salaire,
# poste...) ne dépend pas de la période choisie. games_played est géré séparément (pas dans cette
# liste) par _substitute_playoffs_only_stats, qui l'ajoute explicitement à côté.
PLAYOFF_PERIOD_STAT_COLS = [
    "points_per_game", "rebounds_per_game", "assists_per_game", "steals_per_game",
    "blocks_per_game", "turnovers_per_game", "minutes_per_game", "fg_pct", "fg3_pct",
    "ft_pct", "ts_pct", "usg_pct", "pie", "plus_minus",
]


def _recompute_derived_stat_columns(df: pd.DataFrame, min_games: int = MIN_GAMES_FOR_FIT) -> pd.DataFrame:
    """(Ré)calcule impact_hors_scoring et low_sample_size à partir des colonnes de stats
    actuellement présentes dans `df` — appelé après avoir établi les stats de la période voulue
    (régulière ou playoffs seules), pour que ces deux colonnes dérivées restent cohérentes avec
    la période effectivement affichée plutôt que de garder des valeurs issues d'une période
    précédente.

    `min_games` : seuil du badge "échantillon court" -- MIN_GAMES_FOR_FIT (15) par défaut, mais
    l'appelant doit passer MIN_GAMES_FOR_FIT_PLAYOFFS (4) pour period="playoffs" (voir sa
    docstring pour pourquoi 15 y est structurellement intenable)."""
    df = df.copy()
    df["impact_hors_scoring"] = (
        df["rebounds_per_game"] + df["blocks_per_game"] + df["assists_per_game"] + df["steals_per_game"]
    )
    df["low_sample_size"] = df["games_played"] < min_games
    return df


def _zscore_by_position(stat_source: pd.DataFrame, apply_to: pd.DataFrame, impact_col: str, stat_mask: pd.Series) -> pd.Series:
    """Z-score de `impact_col` PAR GROUPE DE POSTE — moyenne/écart-type calculés sur
    `stat_source[stat_mask]`, appliqués aux valeurs de `apply_to[impact_col]`/
    `apply_to["position_group"]` — `apply_to` peut être le MÊME DataFrame que `stat_source` ou un
    AUTRE (voir compute_radar_scores, seul appelant actuel : normalise un axe du radar de
    comparaison par rapport aux joueurs du même poste, plutôt qu'en absolu)."""
    group_stats = stat_source.loc[stat_mask].groupby("position_group")[impact_col].agg(["mean", "std"])
    group_mean = apply_to["position_group"].map(group_stats["mean"])
    group_std = apply_to["position_group"].map(group_stats["std"])
    z = (apply_to[impact_col] - group_mean) / group_std
    return z.replace([np.inf, -np.inf], np.nan)


def _substitute_playoffs_only_stats(regular_enriched: pd.DataFrame, playoffs: pd.DataFrame) -> pd.DataFrame:
    """Remplace les colonnes de stats par leurs valeurs PLAYOFFS SEULES (pas de moyenne, pas de
    total) — pour period="playoffs". Un joueur absent de `playoffs` (n'a pas fait les playoffs
    cette saison) se retrouve avec games_played/stats de période à NaN : il disparaîtra du nuage
    comme n'importe quel joueur sans donnée sur les axes choisis (dropna déjà en place côté
    Dashboard.py), pas de traitement spécial nécessaire ici. Le reste de la ligne (salaire, poste)
    est conservé tel quel depuis `regular_enriched` — ces attributs ne dépendent pas de la
    période."""
    drop_cols = [c for c in PLAYOFF_PERIOD_STAT_COLS + ["games_played"] if c in regular_enriched.columns]
    po_cols = ["player_id"] + PLAYOFF_PERIOD_STAT_COLS + ["games_played"]
    return regular_enriched.drop(columns=drop_cols).merge(playoffs[po_cols], on="player_id", how="left")


def _enrich_stats(stats: pd.DataFrame, season: str, force_refresh: bool) -> pd.DataFrame:
    """Ajoute au DataFrame de stats per-game `stats` (même schéma que _fetch_nba_api_stats, quelle
    que soit la période) tout ce qui ne dépend QUE du joueur/de la saison, pas des stats de jeu
    elles-mêmes : salaire réel (TOUJOURS saison régulière, voir docstring de module), poste,
    impact_hors_scoring dérivé et low_sample_size (sur le games_played fourni). Reprend
    exactement la logique historique de get_player_stats, seulement paramétrée sur `stats` au
    lieu de le fetcher elle-même — permet de la réutiliser à l'identique pour la saison régulière
    ET pour l'échantillon combiné saison+playoffs."""
    stats = stats.copy()
    try:
        if int(season[:4]) >= RATIN21_DATASET_START_YEAR:
            kaggle_raw = _load_kaggle_raw(force_refresh=force_refresh)
        else:
            kaggle_raw = _load_legacy_kaggle_raw(force_refresh=force_refresh)
        salary_per = _extract_kaggle_season(kaggle_raw, season)
    except KaggleDatasetUnavailable as exc:
        logger.warning("Salaire/PER indisponibles pour %s : %s", season, exc)
        salary_per = pd.DataFrame(columns=["_key", "salary", "per", "salary_is_estimated"])

    stats["_key"] = stats["player"].map(normalize_name)
    join_cols = ["_key", "salary", "per", "salary_is_estimated"]
    merged = stats.merge(salary_per[join_cols], on="_key", how="left").drop(columns="_key")
    merged["salary_is_estimated"] = merged["salary_is_estimated"].fillna(False)
    merged.insert(0, "season", season)
    merged.insert(0, "sport", "nba")
    merged["salary_musd"] = merged["salary"] / 1_000_000

    try:
        positions = _fetch_player_positions(season, force_refresh=force_refresh)
        merged = merged.merge(positions, on="player_id", how="left")
    except Exception as exc:
        logger.warning("Postes indisponibles pour %s : %s", season, exc)
        merged["position_group"] = np.nan

    merged = _recompute_derived_stat_columns(merged)
    return merged


def _with_final_game_team(stats: pd.DataFrame, season: str, force_refresh: bool) -> tuple[pd.DataFrame, bool]:
    """Remplace `team` de `stats` (TEAM_ABBREVIATION de LeagueDashPlayerStats) par l'équipe du
    DERNIER match de saison régulière du joueur d'après le game log -- même règle que
    get_mercato_lineup. La valeur NBA est la dernière équipe d'INSCRIPTION du joueur sur la
    saison, même sans y avoir joué : échange à la date limite d'un joueur blessé (Ingram
    NOP -> TOR 2024-25), transaction d'intersaison conclue avant fin juin (Bane MEM -> ORL,
    juin 2025), contrat court sans match. 97 écarts de 2012-13 à 2025-26, aucun avant (vérifié
    en septembre 2026). Valeur NBA conservée pour un joueur sans aucun match dans le log.

    Renvoie aussi un booléen "complet" : False si le game log est indisponible (valeurs NBA
    gardées telles quelles), pour que l'appelant n'écrive pas le cache traité -- même principe
    que la fiabilité incomplète dans get_player_stats."""
    try:
        game_log = _fetch_player_game_log(season, force_refresh=force_refresh)
    except Exception as exc:
        logger.warning("Game log indisponible pour %s, équipe NBA d'origine gardée : %s", season, exc)
        return stats, False
    final_team = (
        game_log.sort_values("game_date")
        .drop_duplicates(subset="player_id", keep="last")
        .set_index("player_id")["team"]
    )
    stats = stats.copy()
    stats["team"] = stats["player_id"].map(final_team).fillna(stats["team"])
    return stats, True


# --------------------------------------------------------------------------
# Point d'entrée public
# --------------------------------------------------------------------------
# Type de `period` ci-dessous -- déclaré explicitement (n'existait pas avant, la seule occurrence
# était une annotation sur get_player_stats jamais définie ; resté sans erreur jusqu'ici
# uniquement grâce à `from __future__ import annotations`, qui traite les annotations comme de
# simples chaînes jamais évaluées au runtime). Deux valeurs seulement depuis le retrait de
# "regular_playoffs".
PlayoffMode = Literal["regular", "playoffs"]
def get_player_stats(season: str, force_refresh: bool = False, period: PlayoffMode = "regular") -> pd.DataFrame:
    """Retourne les stats joueurs NBA pour une saison, normalisées et enrichies (salaire, PER),
    avec mise en cache disque (data_cache/processed/nba/<season>[_<period>].parquet).

    `period` (voir le bloc de commentaires juste au-dessus de PLAYOFF_PERIOD_STAT_COLS pour le
    détail complet) :
      - "regular" (défaut) : comportement historique inchangé, saison régulière seule.
      - "playoffs" : stats de jeu playoffs SEULES.
    Dans les 2 cas, le salaire réel (salary_musd/salary_pct_cap) reste celui de la saison
    régulière — c'est le seul qui existe réellement. Un 3e mode combiné ("regular_playoffs") a
    existé puis a été retiré (décision explicite, voir le commentaire au-dessus de
    PLAYOFF_PERIOD_STAT_COLS).

    Colonnes garanties : sport, season, player, team + toutes les clés de
    METRICS (certaines peuvent être NaN, ex. salaire/PER si le dataset
    Kaggle ne couvre pas encore la saison demandée, ou stats playoffs pour un joueur dont
    l'équipe n'a pas été qualifiée cette saison-là).
    """
    if period not in ("regular", "playoffs"):
        raise ValueError(f"period invalide : {period!r} (attendu 'regular' ou 'playoffs')")

    cache_suffix = "" if period == "regular" else f"_{period}"
    processed_path = NBA_PROCESSED_DIR / f"{season}{cache_suffix}.parquet"
    if not force_refresh:
        cached = read_cache(processed_path, schema_version=PROCESSED_SCHEMA_VERSION)
        if cached is not None:
            return cached

    # --- Base "saison régulière" : TOUJOURS calculée, quel que soit `period` -- utilisée telle
    # quelle pour period="regular", et comme point de départ (salaire, poste) pour "playoffs"
    # (voir _substitute_playoffs_only_stats, qui ne remplace que les stats de jeu).
    reg_stats_raw = _fetch_nba_api_stats(season, force_refresh=force_refresh)
    # Équipe du dernier match (voir _with_final_game_team) : corrigée ici, sur la base saison
    # régulière, elle vaut aussi pour period="playoffs" (_substitute_playoffs_only_stats garde
    # l'équipe de cette base).
    reg_stats_raw, final_team_complete = _with_final_game_team(reg_stats_raw, season, force_refresh)
    reg_merged = _enrich_stats(reg_stats_raw, season, force_refresh)

    if period == "regular":
        working = reg_merged
    else:  # "playoffs"
        po_stats_raw = _fetch_nba_api_stats_playoffs(season, force_refresh=force_refresh)
        working = _substitute_playoffs_only_stats(reg_merged, po_stats_raw)
        # min_games=MIN_GAMES_FOR_FIT_PLAYOFFS (4, pas 15) : le badge "échantillon court" doit
        # utiliser un seuil adapté au nombre de matchs RÉELLEMENT jouable en playoffs, voir sa
        # docstring pour la justification complète.
        working = _recompute_derived_stat_columns(working, min_games=MIN_GAMES_FOR_FIT_PLAYOFFS)

    # Normalisation en % du plafond salarial officiel de la saison -- rend les montants
    # comparables entre saisons très éloignées (24M$ de plafond en 1996-97 contre 154M$ en
    # 2025-26 rendraient sinon la vue "Toutes les saisons" dominée par les saisons récentes).
    # .get(season) plutôt que [season] : NaN silencieux (pas de crash) si une saison hors de
    # NBA_SALARY_CAP_BY_SEASON était un jour demandée (ex. période dans KNOWN_SALARY_DATA_GAPS).
    season_cap = NBA_SALARY_CAP_BY_SEASON.get(season)
    working["salary_pct_cap"] = working["salary"] / season_cap if season_cap else np.nan

    # Fiabilité incomplète (une saison de la fenêtre indisponible, ex. erreur réseau) ou en
    # erreur : valeur laissée manquante (NaN, jamais une valeur partielle donc fausse) ET cache
    # traité NON écrit, pour qu'il soit recalculé au prochain chargement. L'écrire, même avec
    # des NaN, le rendrait "valide" indéfiniment vis-à-vis de PROCESSED_SCHEMA_VERSION : la
    # métrique resterait perdue (ou fausse) jusqu'au prochain changement de schéma. Bug constaté
    # sur 2022-23 : fiabilité calculée sur 2 saisons sur 3 et persistée telle quelle.
    reliability_complete = False
    try:
        reliability, reliability_complete = _fetch_reliability(season, force_refresh=force_refresh)
    except Exception as exc:
        logger.warning("Fiabilité indisponible pour %s : %s", season, exc)
    if reliability_complete:
        working = working.merge(reliability, on="player_id", how="left")
    else:
        working["reliability_pct"] = np.nan

    if reliability_complete and final_team_complete:
        write_cache(working, processed_path, schema_version=PROCESSED_SCHEMA_VERSION)
    else:
        logger.warning(
            "Cache traité %s non écrit : fiabilité ou équipe du dernier match incomplète, "
            "recalcul au prochain chargement.",
            processed_path.name,
        )
    return working


def get_team_ranking(season: str, period: PlayoffMode = "regular", force_refresh: bool = False) -> pd.DataFrame:
    """Classement des équipes pour le bandeau de Dashboard.py -- vraies stats d'ÉQUIPE
    (_fetch_team_stats, PAS une moyenne des joueurs affichés/filtrés dans le scatter plot) +
    masse salariale totale de l'effectif + indicateur "champion" (CHAMPIONS_BY_SEASON).

    `period` ("regular"/"playoffs") pilote UNIQUEMENT les stats de jeu d'équipe, indépendamment
    du mode saison régulière/playoffs éventuellement choisi ailleurs dans le dashboard pour le
    scatter plot -- une équipe non qualifiée en playoffs n'a simplement pas de ligne ici.

    La masse salariale reste TOUJOURS sommée sur la saison régulière (même logique que
    salary_musd dans get_player_stats : le salaire est un concept saison régulière, pas
    playoffs) quel que soit `period`. `sum(min_count=1)` plutôt qu'un simple `.sum()` : une
    équipe dont AUCUN joueur n'a de salaire connu doit ressortir à NaN, pas à 0 -- une masse
    salariale à 0$ serait trompeuse (silencieusement confondue avec une vraie donnée)."""
    team_stats = _fetch_team_stats(season, period=period, force_refresh=force_refresh)

    players = get_player_stats(season, force_refresh=force_refresh, period="regular")
    salary_by_team = (
        players.dropna(subset=["team"])
        .groupby("team")["salary_musd"].sum(min_count=1)
        .rename("salary_total_musd")
        .reset_index()
    )

    result = team_stats.merge(salary_by_team, on="team", how="left")
    result["champion"] = result["team"] == CHAMPIONS_BY_SEASON.get(season)
    return result


MERCATO_LABELS = ["M", "A", "AI", "AF", "P"]
MERCATO_POSITION_ORDER = {"Extérieur": 0, "Ailier": 1, "Intérieur": 2}


def _fetch_player_game_log(season: str, force_refresh: bool = False) -> pd.DataFrame:
    """Log match par match de chaque joueur sur `season` (nba_api, LeagueGameLog en mode
    joueurs, saison régulière UNIQUEMENT) : une ligne par (joueur, match), avec l'équipe et les
    minutes de CE match précis. Contrairement à get_player_stats (une moyenne déjà agrégée sur
    toute la saison -- toutes équipes confondues pour un joueur transféré), ce log permet de
    recalculer une moyenne PAR ÉQUIPE, utilisée par get_mercato_lineup pour ne pas mélanger les
    minutes d'un joueur avant/après un transfert.

    Un seul appel groupé par saison (comme _fetch_team_games_possible) : LeagueGameLog renvoie
    directement une ligne par (joueur, match) pour toute la ligue en une requête, pas besoin
    d'un appel par joueur ou par équipe. Garde aussi team_id/team_name (déjà dans la réponse) --
    utilisés par get_team_identity, pas seulement team (abréviation)."""
    raw_cache_path = NBA_RAW_DIR / "nba_api" / f"game_log_{season}.parquet"
    cached = None if force_refresh else read_cache(raw_cache_path, schema_version=NBA_API_GAME_LOG_SCHEMA_VERSION)
    if cached is not None:
        return cached

    from nba_api.stats.endpoints import leaguegamelog

    raw = _call_with_retries(
        lambda: leaguegamelog.LeagueGameLog(
            season=season, season_type_all_star="Regular Season", player_or_team_abbreviation="P",
            timeout=NBA_API_TIMEOUT_SECONDS,
        ).get_data_frames()[0],
        description=f"_fetch_player_game_log({season})",
    )
    result = raw.rename(columns={
        "PLAYER_ID": "player_id", "TEAM_ID": "team_id", "TEAM_ABBREVIATION": "team",
        "TEAM_NAME": "team_name", "MIN": "minutes", "GAME_DATE": "game_date",
    })[["player_id", "team_id", "team", "team_name", "game_date", "minutes"]]

    write_cache(result, raw_cache_path, schema_version=NBA_API_GAME_LOG_SCHEMA_VERSION)
    return result


def get_mercato_lineup(season: str, force_refresh: bool = False) -> pd.DataFrame:
    """Pour chaque équipe de `season` (saison régulière UNIQUEMENT, jamais playoffs), les 6
    joueurs affichés sur sa carte "Mercato" : un top 5 par minutes/match parmi les joueurs
    éligibles, réordonné par groupe de poste (Extérieur puis Ailier puis Intérieur, minutes
    décroissantes dans chaque groupe) avec l'étiquette M/A/AI/AF/P collée aux positions 1-5
    dans cet ordre FIXE -- pas un vrai mapping poste réel -> étiquette, voir plus bas -- puis
    un 6e homme (position 6, étiquette "6e").

    Rattachement d'équipe et minutes/matchs recalculés depuis le game log match par match
    (_fetch_player_game_log), PAS depuis get_player_stats (dont les moyennes sont blendées sur
    toute la saison pour un joueur transféré, ex: Hayward CHA+OKC 2023-24 ressortait à
    24.4 min/match toutes équipes confondues, alors qu'il ne tournait qu'à ~17 min/match une
    fois à OKC) : chaque joueur est rattaché à l'équipe de son DERNIER match de la saison,
    recalculée depuis game_date. get_player_stats.team suit désormais la même règle (voir
    _with_final_game_team ; avant, c'était la dernière équipe d'inscription NBA, différente
    pour 8/572 joueurs en 2023-24). Ses minutes/matchs ne comptent que les matchs
    joués avec CETTE équipe -- il n'apparaît dans aucune autre carte. Un joueur sans aucun match
    loggé cette saison (blessé toute l'année, jamais appelé en two-way...) n'apparaît dans
    aucune carte : cohérent, impossible de lui attribuer une équipe ou des minutes sans match
    réel.

    Éligibilité (`games_played` avec cette équipe >= 25% des matchs possibles de la saison,
    arrondi au supérieur via _fetch_team_games_possible) : évite qu'un joueur à très peu de
    matchs mais beaucoup de minutes/match (petit échantillon gonflé) passe devant un vrai
    titulaire. Si une équipe a moins de 6 joueurs éligibles, les places restantes sont comblées
    par ses joueurs NON éligibles, par minutes/match décroissantes -- l'éligibilité prime
    TOUJOURS sur les minutes brutes (un joueur éligible passe avant n'importe quel non-éligible,
    même si ce dernier a plus de minutes/match).

    Second critère d'éligibilité, en OU avec le premier : au moins 50% des matchs joués par SON
    ÉQUIPE depuis le premier match du joueur avec elle (arrondi au supérieur), ET au moins
    MERCATO_MIN_GAMES_SINCE_ARRIVAL matchs joués avec cette équipe -- sans ce plancher, un
    contrat de 10 jours qui joue 3 des 4 derniers matchs de l'équipe (75% >= 50%) deviendrait
    éligible. Un joueur tradé à la deadline (ex: Kyrie Irving, Dallas 2022-23, ~20 matchs sur
    les ~24 restants après son arrivée) peut être sous le seuil des 25% de la saison complète
    tout en étant titulaire depuis son arrivée -- ce second critère l'évite. Le "match
    d'arrivée" et le calendrier de l'équipe viennent tous deux du game log (dates de match
    distinctes où l'équipe apparaît, sur TOUS les joueurs -- indépendant du joueur regardé).

    Troisième critère d'éligibilité, en OU avec les deux précédents : le joueur a joué au moins
    25% des matchs possibles de la saison TOUTES ÉQUIPES CONFONDUES (total de ses matchs dans le
    game log, peu importe l'équipe) ET au moins MERCATO_MIN_GAMES_ESTABLISHED_PLAYER matchs avec
    son équipe de fin de saison -- couvre un joueur clairement établi sur la saison mais dont le
    passage dans sa dernière équipe est trop court pour les deux critères précédents (ex: Kevin
    Durant, Phoenix 2022-23 : 8 matchs à Phoenix après une blessure post-transfert, mais 47
    matchs toutes équipes confondues sur la saison). Ne change RIEN au classement dans le top 6
    (toujours basé uniquement sur les minutes/match avec l'équipe de fin de saison) -- ce
    critère ne fait qu'élargir qui est éligible, pas comment les éligibles sont ordonnés (Hayward,
    OKC 2023-24, reste hors du top 6 : ses minutes à OKC restent basses même une fois éligible).

    Étiquettes M/A/AI/AF/P (Meneur/Arrière/Ailier/Ailier Fort/Pivot) : collées aux 5 PREMIÈRES
    places du tri par poste ci-dessus dans cet ordre fixe, quel que soit le mix réel de postes
    de l'équipe (ex: une équipe avec 3 Extérieurs dans son top 5 aura 3 joueurs étiquetés
    M/A/AI qui ne jouent pas tous réellement meneur/arrière/ailier) -- compromis explicitement
    accepté plutôt qu'un système de quota qui exclurait un joueur pour forcer un mix 2/2/1.

    `position_group` manquant (NaN) : traité comme "Ailier" UNIQUEMENT pour ce tri
    (position_missing=True le signale) -- la colonne position_group du résultat garde sa
    vraie valeur (NaN), ce repli ne change pas la donnée affichée.

    Mis en cache par saison (data_cache/processed/nba/mercato_<season>.parquet, même mécanisme
    read_cache/write_cache que le reste du module)."""
    processed_path = NBA_PROCESSED_DIR / f"mercato_{season}.parquet"
    cached = None if force_refresh else read_cache(processed_path, schema_version=MERCATO_SCHEMA_VERSION)
    if cached is not None:
        return cached

    game_log = _fetch_player_game_log(season, force_refresh=force_refresh)
    games_possible = _fetch_team_games_possible(season, force_refresh=force_refresh)
    min_games = math.ceil(0.25 * games_possible)

    # Équipe du DERNIER match de la saison = équipe "de fin de saison" pour ce joueur -- même
    # règle que get_player_stats.team (voir _with_final_game_team), recalculée ici depuis le game
    # log déjà chargé.
    last_game = (
        game_log.sort_values("game_date")
        .drop_duplicates(subset="player_id", keep="last")[["player_id", "team"]]
        .rename(columns={"team": "final_team"})
    )
    # Minutes/matchs recalculés en ne gardant QUE les lignes du game log où l'équipe jouée
    # correspond à l'équipe de fin de saison de ce joueur -- exclut mécaniquement les matchs
    # joués avec une équipe précédente en cas de transfert.
    per_team_stats = (
        game_log.merge(last_game, on="player_id")
        .query("team == final_team")
        .groupby("player_id", as_index=False)
        .agg(
            games_played=("minutes", "count"),
            minutes_per_game=("minutes", "mean"),
            first_game_date=("game_date", "min"),
        )
    )
    lineup_base = last_game.rename(columns={"final_team": "team"}).merge(
        per_team_stats, on="player_id", how="left"
    )

    # Nom + poste viennent de get_player_stats (jointure sur player_id UNIQUEMENT, pas sur team --
    # son "team" à lui n'est pas utilisé ici, voir docstring).
    players_meta = get_player_stats(season, force_refresh=force_refresh, period="regular")[
        ["player_id", "player", "position_group"]
    ].drop_duplicates(subset="player_id")
    lineup_base = lineup_base.merge(players_meta, on="player_id", how="left")

    # Calendrier de chaque équipe (dates de match distinctes, toutes lignes confondues -- un match
    # de l'équipe est loggé par au moins un joueur ayant cette valeur "team" ce jour-là) : sert au
    # second critère d'éligibilité ci-dessous ("50% des matchs de l'équipe depuis l'arrivée").
    team_schedule = game_log.groupby("team")["game_date"].apply(lambda s: np.sort(s.unique())).to_dict()

    def _team_games_since(team: str, since_date) -> int:
        dates = team_schedule.get(team, np.array([]))
        return int((dates >= since_date).sum())

    lineup_base["_team_games_since_arrival"] = [
        _team_games_since(t, d) for t, d in zip(lineup_base["team"], lineup_base["first_game_date"])
    ]
    lineup_base["_eligible_full_season"] = lineup_base["games_played"].fillna(0) >= min_games
    lineup_base["_eligible_since_arrival"] = (
        lineup_base["games_played"].fillna(0) >= MERCATO_MIN_GAMES_SINCE_ARRIVAL
    ) & (
        lineup_base["games_played"].fillna(0)
        >= lineup_base["_team_games_since_arrival"].apply(lambda n: math.ceil(0.5 * n))
    )
    # Troisième critère : joueur "établi" sur la saison ENTIÈRE toutes équipes confondues (total
    # de matchs dans le game log, sans filtrer sur l'équipe de fin de saison), avec un plancher
    # de matchs joués avec l'équipe de fin de saison -- voir docstring.
    total_games_by_player = game_log.groupby("player_id").size().rename("total_games_all_teams")
    lineup_base = lineup_base.merge(total_games_by_player, on="player_id", how="left")
    lineup_base["_eligible_established"] = (
        (lineup_base["total_games_all_teams"].fillna(0) >= min_games)
        & (lineup_base["games_played"].fillna(0) >= MERCATO_MIN_GAMES_ESTABLISHED_PLAYER)
    )
    lineup_base["_eligible"] = (
        lineup_base["_eligible_full_season"]
        | lineup_base["_eligible_since_arrival"]
        | lineup_base["_eligible_established"]
    )
    lineup_base["_position_missing"] = lineup_base["position_group"].isna()
    lineup_base["_position_order"] = lineup_base["position_group"].fillna("Ailier").map(MERCATO_POSITION_ORDER)

    rows = []
    for team, team_df in lineup_base.groupby("team"):
        eligible = team_df[team_df["_eligible"]].sort_values("minutes_per_game", ascending=False)
        rest = team_df[~team_df["_eligible"]].sort_values("minutes_per_game", ascending=False)
        six = pd.concat([eligible, rest], ignore_index=True).head(6)
        if six.empty:
            continue

        n_starters = min(5, len(six))
        starters = six.iloc[:n_starters].sort_values(
            ["_position_order", "minutes_per_game"], ascending=[True, False]
        )
        for slot, (label, (_, row)) in enumerate(zip(MERCATO_LABELS, starters.iterrows()), start=1):
            rows.append({
                "team": team, "slot": slot, "label": label,
                "player_id": row["player_id"], "player": row["player"],
                "position_group": row["position_group"],
                "minutes_per_game": row["minutes_per_game"],
                "position_missing": bool(row["_position_missing"]),
            })

        if len(six) >= 6:
            sixth = six.iloc[5]
            rows.append({
                "team": team, "slot": 6, "label": "6e",
                "player_id": sixth["player_id"], "player": sixth["player"],
                "position_group": sixth["position_group"],
                "minutes_per_game": sixth["minutes_per_game"],
                "position_missing": bool(sixth["_position_missing"]),
            })

    result = pd.DataFrame(
        rows,
        columns=["team", "slot", "label", "player_id", "player", "position_group",
                 "minutes_per_game", "position_missing"],
    )
    write_cache(result, processed_path, schema_version=MERCATO_SCHEMA_VERSION)
    return result


def get_team_identity(season: str, force_refresh: bool = False) -> pd.DataFrame:
    """Identité de chaque équipe pour `season` : team_id NBA (stable à travers un déménagement/
    renommage) + nom complet EXACT de CETTE saison (ex: "Charlotte Bobcats" en 2004-05 vs
    "Charlotte Hornets" aujourd'hui, même team_id ET même abréviation "CHA" -- piège si on se
    fie à l'abréviation seule). Dérivé du game log (_fetch_player_game_log, déjà en cache pour
    get_mercato_lineup) : TEAM_ID/TEAM_NAME sont déjà renvoyés par LeagueGameLog, pas besoin
    d'un second appel réseau (ex: FranchiseHistory) pour cette donnée.

    Utilisé par pages/2_Effectifs.py (grille et vue effectif réel) pour le nom d'équipe de la
    saison, et par scripts/update_nba_logos.py pour associer à chaque (saison, équipe) le logo
    de son époque (table data_sources/nba_logos.csv)."""
    game_log = _fetch_player_game_log(season, force_refresh=force_refresh)
    return game_log[["team", "team_id", "team_name"]].drop_duplicates(subset="team").reset_index(drop=True)


def get_first_game_teams(season: str, force_refresh: bool = False) -> pd.DataFrame:
    """Équipe du PREMIER match de saison régulière de chaque joueur (player_id, team, team_id),
    d'après le game log (_fetch_player_game_log, déjà en cache pour get_mercato_lineup). Pendant
    de l'équipe de fin de saison de get_mercato_lineup (dernier match).

    Utilisé par pages/2_Effectifs.py pour le portrait de la saison : le CDN NBA range ces
    portraits sous l'équipe de début de saison, donc un joueur transféré apparaît avec le maillot
    de sa première équipe (voulu : ça montre le transfert)."""
    game_log = _fetch_player_game_log(season, force_refresh=force_refresh)
    return (
        game_log.sort_values("game_date", kind="stable")
        .drop_duplicates(subset="player_id", keep="first")[["player_id", "team", "team_id"]]
        .reset_index(drop=True)
    )


# --------------------------------------------------------------------------
# Radar de comparaison de joueurs (voir pages/1_Radar_de_comparaison.py) — dix axes de skill
# dérivés de colonnes déjà présentes dans get_player_stats (catalogue METRICS), normalisés par
# poste avec _zscore_by_position (voir sa docstring). Section volontairement placée après
# get_player_stats : fonctionnalité indépendante du pipeline principal, qui n'a besoin d'aucune
# de ces colonnes.
#
# "Interceptions" et "Contres" (steals_per_game/blocks_per_game) étaient fusionnés en un seul axe
# "Activité défensive" dans une version précédente -- séparés ici à la demande de l'utilisateur
# (vraie granularité : anticipation/défense de périmètre vs protection du cercle, deux profils
# différents). Chacun garde individuellement le même type de caveat que l'ancien composite
# (proxy box-score, pas une vraie mesure de qualité défensive -- voir METHODOLOGY.md, section
# "Métrique défensive individuelle").
#
# "Sécurité de balle" (turnovers_per_game) est le seul axe où la stat brute va dans le sens
# INVERSE des autres (moins de pertes de balle = meilleur) -- `invert=True` signale qu'il faut
# calculer le z-score/percentile sur la stat NÉGÉE (voir compute_radar_scores), pour que "loin du
# centre = meilleur" reste vrai sur tous les axes du radar, y compris celui-ci. `stat_col` reste
# la colonne brute réelle (turnovers_per_game) pour l'affichage de la valeur/match dans le
# tooltip et le tableau récap -- seul le calcul du z-score/percentile utilise la version négée.
RADAR_STEALS_CAVEAT = (
    " ⚠️ \"Interceptions\" (steals) favorise structurellement les joueurs actifs sur le ballon "
    "(arrières/ailiers qui multiplient les prises de risque défensives) — un intérieur qui "
    "défend par positionnement peut en avoir peu sans être un mauvais défenseur. Proxy "
    "box-score, pas une vraie mesure de qualité défensive individuelle (voir METHODOLOGY.md)."
)
RADAR_BLOCKS_CAVEAT = (
    " ⚠️ \"Contres\" (blocks) favorise structurellement les intérieurs (proximité du cercle) — "
    "un extérieur qui en a peu n'est pas nécessairement moins bon défenseur, ce n'est simplement "
    "pas son registre. Proxy box-score, pas une vraie mesure de qualité défensive individuelle "
    "(voir METHODOLOGY.md)."
)
# "Sécurité de balle" a DEUX caveats distincts (d'où "caveats", une liste, sur cet axe -- les
# autres axes à caveat n'en ont qu'un) : le biais de volume ci-dessous (même famille que les
# caveats Interceptions/Contres -- un proxy box-score influencé par le rôle, pas une vraie mesure
# pure) et la note d'inversion (comment lire l'axe, pas un biais). Un meneur à fort volume de jeu
# porte le ballon beaucoup plus souvent qu'un rôleur -- il perd donc mécaniquement plus de ballons
# en ABSOLU (turnovers_per_game n'est pas normalisé par possessions/touches), même s'il est aussi
# fiable balle en main que ce rôleur. Contrairement à Interceptions/Contres (biais de poste),
# celui-ci est un biais de RÔLE OFFENSIF (volume de jeu), mais le principe est le même : proxy
# box-score, pas une mesure pure de fiabilité individuelle indépendante du rôle.
RADAR_TURNOVERS_BIAS_CAVEAT = (
    " ⚠️ \"Sécurité de balle\" reste corrélée au volume de jeu : un meneur à fort volume "
    "(beaucoup de possessions, porteur de balle principal) perd mécaniquement plus de ballons en "
    "absolu qu'un joueur à faible volume, même s'il est tout aussi fiable balle en main. Pas une "
    "mesure pure de fiabilité individuelle, indépendante du rôle offensif."
)
RADAR_TURNOVERS_NOTE = (
    " ℹ️ Axe inversé : moins de pertes de balle par match donne un score PLUS élevé sur cet axe, "
    "pour rester cohérent avec le reste du radar (plus loin du centre = meilleur, partout)."
)

RADAR_AXES: list[dict] = [
    {"key": "scoring", "label": "Scoring", "stat_col": "points_per_game"},
    {"key": "passe", "label": "Passe", "stat_col": "assists_per_game"},
    {"key": "rebond", "label": "Rebond", "stat_col": "rebounds_per_game"},
    {"key": "interceptions", "label": "Interceptions", "stat_col": "steals_per_game", "caveats": [RADAR_STEALS_CAVEAT]},
    {"key": "contres", "label": "Contres", "stat_col": "blocks_per_game", "caveats": [RADAR_BLOCKS_CAVEAT]},
    {"key": "efficacite", "label": "Efficacité (TS%)", "stat_col": "ts_pct"},
    {"key": "impact", "label": "Impact global (PIE)", "stat_col": "pie"},
    {"key": "tir_exterieur", "label": "Tir extérieur (3PT%)", "stat_col": "fg3_pct"},
    {
        "key": "securite_balle", "label": "Sécurité de balle", "stat_col": "turnovers_per_game",
        "invert": True, "caveats": [RADAR_TURNOVERS_BIAS_CAVEAT, RADAR_TURNOVERS_NOTE],
    },
    {"key": "lancers_francs", "label": "Lancers francs (LF%)", "stat_col": "ft_pct"},
]

# Collectés depuis RADAR_AXES plutôt que maintenus séparément : évite qu'un axe ajouté/retiré avec
# un caveat soit oublié ici.
RADAR_CAVEATS: list[str] = [c for a in RADAR_AXES for c in a.get("caveats", [])]


def _percentile_by_position(
    stat_source: pd.DataFrame, apply_to: pd.DataFrame, impact_col: str, stat_mask: pd.Series
) -> pd.Series:
    """Rang percentile de `impact_col` PAR GROUPE DE POSTE — même principe et mêmes paramètres
    que _zscore_by_position (même `stat_source`/`apply_to`/`stat_mask`), en rang plutôt qu'en
    écart-type : pourcentage de joueurs de RÉFÉRENCE (même poste, lignes de `stat_source` où
    `stat_mask` est vrai) que ce joueur égale ou dépasse sur cet axe. Calcul volontairement simple
    (rang / effectif, via np.searchsorted) plutôt qu'une fonction de bibliothèque externe (évite
    une dépendance à scipy pour un calcul déjà trivial avec numpy/pandas)."""
    ref = stat_source.loc[stat_mask]
    result = pd.Series(np.nan, index=apply_to.index, dtype=float)
    for group, ref_group in ref.groupby("position_group"):
        values = np.sort(ref_group[impact_col].dropna().to_numpy())
        n = len(values)
        if n == 0:
            continue
        in_group = apply_to["position_group"] == group
        col_vals = apply_to.loc[in_group, impact_col]
        valid = col_vals.notna()
        idx = col_vals[valid].index
        ranks = np.searchsorted(values, col_vals[valid].to_numpy(), side="right")
        result.loc[idx] = ranks / n * 100
    return result


def compute_radar_scores(df: pd.DataFrame, period: PlayoffMode = "regular") -> pd.DataFrame:
    """Ajoute, pour chaque axe de RADAR_AXES, sur la même référence (population de `df` ayant
    joué au moins un seuil minimum de matchs, groupée par poste) :
      - `radar_<key>_z` : z-score (_zscore_by_position, même fonction que le modèle de valeur
        ajoutée) et sa mise à l'échelle [0, 100] pour affichage radar (`radar_<key>_score`, clip
        à ±3 écarts-types puis rescale linéaire) — mode "Indice" de la page radar.
      - `radar_<key>_percentile` : rang percentile (_percentile_by_position) — mode "Centile".
    Les deux sont ensuite appliqués à TOUT `df`, y compris les échantillons courts sous ce seuil
    (comme le scatter principal, affichés mais pas dans la référence).

    `period` sélectionne le seuil, MÊME PRINCIPE que _recompute_derived_stat_columns/le badge
    "échantillon court" du scatter principal : MIN_GAMES_FOR_FIT (15) en "regular",
    MIN_GAMES_FOR_FIT_PLAYOFFS (4) en "playoffs" -- 15 y est structurellement intenable (voir la
    docstring de MIN_GAMES_FOR_FIT_PLAYOFFS), et sans cette distinction la population de
    référence du radar en mode playoffs serait quasi vide comme l'était le badge avant sa
    correction. Le paramètre s'appelle `period` (pas `min_games` en direct) pour que
    pages/1_Radar_de_comparaison.py n'ait pas besoin d'importer les constantes de seuil -- il
    passe déjà `stats_period` ("regular"/"playoffs"), cohérent avec le reste de l'app.

    Un axe avec `invert=True` (voir RADAR_AXES -- actuellement "Sécurité de balle") calcule son
    z-score/percentile sur l'OPPOSÉ de `stat_col` (colonne temporaire, supprimée avant de
    retourner) : `stat_col` lui-même n'est jamais modifié, il reste la vraie valeur/match pour
    l'affichage (tooltip, tableau récap) -- seul le calcul de position dans le radar est inversé."""
    min_games = MIN_GAMES_FOR_FIT_PLAYOFFS if period == "playoffs" else MIN_GAMES_FOR_FIT
    result = df.copy()

    if "position_group" not in result.columns:
        for axis in RADAR_AXES:
            result[f"radar_{axis['key']}_z"] = np.nan
            result[f"radar_{axis['key']}_score"] = np.nan
            result[f"radar_{axis['key']}_percentile"] = np.nan
        return result

    stat_mask = result["games_played"].fillna(0) >= min_games
    temp_cols = []
    for axis in RADAR_AXES:
        col = axis["stat_col"]
        if col not in result.columns:
            result[f"radar_{axis['key']}_z"] = np.nan
            result[f"radar_{axis['key']}_score"] = np.nan
            result[f"radar_{axis['key']}_percentile"] = np.nan
            continue
        z_col = col
        if axis.get("invert"):
            z_col = f"_radar_{axis['key']}_inverted"
            result[z_col] = -result[col]
            temp_cols.append(z_col)
        z = _zscore_by_position(result, result, z_col, stat_mask)
        result[f"radar_{axis['key']}_z"] = z
        result[f"radar_{axis['key']}_score"] = (z.clip(-3, 3) + 3) / 6 * 100
        result[f"radar_{axis['key']}_percentile"] = _percentile_by_position(result, result, z_col, stat_mask)
    return result.drop(columns=temp_cols)
