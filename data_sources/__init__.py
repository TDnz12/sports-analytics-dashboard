"""
Registre central des sports supportés par le dashboard.

Chaque module de sport (nba.py, rugby.py, ...) doit exposer :
    - get_player_stats(season: str, force_refresh: bool = False, period: str = "regular")
      -> pd.DataFrame — DataFrame normalisé selon le schéma commun défini dans base.py.
      `period` est optionnel (par défaut "regular", comportement historique) : pour la NBA,
      voir data_sources/nba.py pour les valeurs acceptées ("regular"/"playoffs") — un sport sans
      notion de playoffs peut ignorer ce paramètre.
    - SEASONS: list[str]  -> saisons disponibles dans le sélecteur
    - METRICS: dict[str, Metric] -> métriques sélectionnables en X/Y

Pour ajouter un sport plus tard :
    1. Créer data_sources/<sport>.py avec la même interface.
    2. L'enregistrer ci-dessous dans SPORTS.
    3. Rien à changer dans Dashboard.py : le sélecteur de sport et les listes de
       métriques/saisons se construisent automatiquement à partir de SPORTS.

Un sport à plusieurs compétitions (rugby : Top 14, Pro D2, Six Nations) les déclare dans
SportConfig.competitions (liste de base.CompetitionConfig, chacune avec ses saisons) ; voir le
commentaire de ce champ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

from . import nba, rugby
from .base import CompetitionConfig


@dataclass(frozen=True)
class SportConfig:
    key: str                     # identifiant interne, ex "nba"
    label: str                   # libellé affiché dans l'UI, ex "Basketball (NBA)"
    available: bool              # False -> affiché grisé / "bientôt disponible"
    get_player_stats: Optional[Callable[..., pd.DataFrame]] = None
    seasons: Optional[list] = None
    metrics: Optional[dict] = None
    # Champion (récompense collective, pas un lauréat individuel) par saison, {season: team} --
    # optionnel : None pour un sport qui n'a pas encore cette donnée, Dashboard.py doit gérer l'absence
    # sans planter (voir la mention "Champion" du classement d'équipes).
    champions_by_season: Optional[dict] = None
    # Récompenses individuelles (MVP, DPOY...) : award_badges_fn(df) -> Series de listes de codes
    # par ligne (voir nba.get_award_badges) ; award_icons/award_labels pour l'affichage. Les 3
    # optionnels ensemble (None par défaut) -- Dashboard.py doit gérer leur absence sans planter.
    award_badges_fn: Optional[Callable[[pd.DataFrame], pd.Series]] = None
    award_icons: Optional[dict] = None
    award_labels: Optional[dict] = None
    # Radar de comparaison de joueurs (voir pages/1_Radar_de_comparaison.py) : radar_axes
    # décrit les axes affichés (voir nba.RADAR_AXES pour le format), compute_radar_scores(df,
    # period="regular"/"playoffs") ajoute les colonnes radar_<key>_z/_score/_percentile (period
    # sélectionne le seuil "échantillon court" utilisé comme référence, différent en playoffs --
    # voir sa docstring), radar_caveats est une liste de textes d'avertissement à afficher sous
    # le graph. Les 3 optionnels ensemble (None/[] par défaut pour un sport qui n'a pas encore
    # cette fonctionnalité) -- la page radar doit gérer leur absence sans planter (même principe
    # que award_badges_fn ci-dessus).
    radar_axes: Optional[list] = None
    compute_radar_scores: Optional[Callable[..., pd.DataFrame]] = None
    radar_caveats: Optional[list] = None
    # Bandeau "classement des équipes" (Dashboard.py, bas de page) : get_team_ranking(season,
    # period="regular"/"playoffs") -> pd.DataFrame de vraies stats d'ÉQUIPE (pas une moyenne des
    # joueurs affichés/filtrés dans le scatter plot) + masse salariale totale + colonne booléenne
    # "champion" ; team_ranking_metrics est le catalogue dédié (voir nba.TEAM_RANKING_METRICS),
    # volontairement séparé de `metrics` (catalogue joueurs). Les 2 optionnels ensemble (None par
    # défaut) -- Dashboard.py doit gérer leur absence sans planter, même principe que
    # award_badges_fn/radar_axes ci-dessus.
    get_team_ranking: Optional[Callable[..., pd.DataFrame]] = None
    team_ranking_metrics: Optional[dict] = None
    # get_teams_static() -> liste des franchises actuelles (id/abbreviation/full_name..., voir
    # nba.get_teams_static). Plus utilisée par les pages depuis les logos d'époque (table locale
    # data_sources/nba_logos.csv, voir scripts/update_nba_logos.py) ; gardée pour un usage
    # futur. Optionnel (None par défaut) -- même principe que les champs ci-dessus.
    get_teams_static: Optional[Callable[[], list]] = None
    # Page "Effectifs" (pages/2_Effectifs.py) : get_mercato_lineup(season) -> pd.DataFrame des 6
    # joueurs affichés sur la carte de chaque équipe dans la grille (voir nba.get_mercato_lineup pour le
    # détail complet du tri/étiquetage). get_team_identity(season) -> pd.DataFrame (team_id/nom
    # exact de cette saison-là, voir nba.get_team_identity) utilisé pour décider si le logo actuel
    # d'une franchise est affichable. Optionnels (None par défaut), même principe que les champs
    # ci-dessus. get_first_game_teams(season) -> pd.DataFrame (player_id, team, team_id du premier
    # match de la saison, voir nba.get_first_game_teams) : équipe des portraits de saison.
    get_mercato_lineup: Optional[Callable[..., pd.DataFrame]] = None
    get_team_identity: Optional[Callable[..., pd.DataFrame]] = None
    get_first_game_teams: Optional[Callable[..., pd.DataFrame]] = None
    # Compétitions d'un sport qui en a plusieurs (rugby : Top 14, Pro D2, Six Nations). Quand ce
    # champ est renseigné, les pages affichent un sélecteur "Compétition" sous le sélecteur Sport,
    # les saisons proposées sont celles de la compétition choisie (pas `seasons`) et les fonctions
    # du sport reçoivent competition=<clé> en argument nommé. Une compétition available=False est
    # affichée "bientôt disponible". None (NBA) : pas de sélecteur, comportement inchangé.
    competitions: Optional[list[CompetitionConfig]] = None
    # --- Réglages du Dashboard propres au sport. Tous optionnels : None = valeur NBA historique,
    # écrite en repli dans Dashboard.py, donc rendu NBA inchangé. ---
    # stats_periods : {libellé : period} du sélecteur "Statistiques utilisées", le premier par
    # défaut (et seul utilisé en mode "Toutes les saisons") ; None = saison régulière / playoffs.
    stats_periods: Optional[dict] = None
    # Défauts des sélecteurs (saison ; métriques en X, Y ; couleur, clé de métrique ou colonne de
    # categorical_colors). None : saison la plus récente, 1re et 2e métriques, pas de couleur.
    default_season: Optional[str] = None
    default_x: Optional[str] = None
    default_y: Optional[str] = None
    default_color: Optional[str] = None
    source_caption: Optional[str] = None      # encart "Sources" ; None = texte NBA
    loading_label: Optional[str] = None       # texte du chargement ; None = texte NBA
    # Curseurs des filtres avancés ; None = 40 min par match (défaut 8) et 82 matchs.
    minutes_slider_max: Optional[float] = None
    minutes_slider_default: Optional[float] = None
    games_slider_max: Optional[int] = None
    # Seuil "échantillon court" en clair (ex. "moins de 5 matchs ou 520 minutes") ; None = texte NBA.
    low_sample_label: Optional[str] = None
    # Case "Afficher les échantillons courts" et sa valeur par défaut ; None = pas de case, les
    # échantillons courts restent affichés en losange (NBA).
    show_low_sample_default: Optional[bool] = None
    # Colonne du nom affiché et recherché (homonymes : "Nom (Club)") ; None = "player".
    player_label_col: Optional[str] = None
    # Colonnes catégorielles proposées dans "Colorer selon", {colonne : libellé} ; None = équipe.
    categorical_colors: Optional[dict] = None
    # Couleurs fixes de ces colonnes, {colonne : {valeur : couleur}}, dans l'ordre de la légende ;
    # None = couleurs attribuées par plotly dans l'ordre d'apparition.
    category_colors: Optional[dict] = None
    # False : légende réduite aux couleurs, sans les entrées "Échantillon normal / court" (le
    # losange reste expliqué sous le graph) ; None = légende NBA.
    legend_symbols: Optional[bool] = None
    # True : pourcentages en "10 %" sur les axes et dans l'infobulle, tableau détaillé en virgule
    # décimale ; None = formats NBA.
    french_format: Optional[bool] = None
    # Filtre par poste des filtres avancés (colonne, ordre des options) ; None = pas de filtre.
    position_filter_col: Optional[str] = None
    position_order: Optional[list] = None
    # Tableau détaillé : {colonne : en-tête} avant et après les métriques choisies ; None = tableau
    # NBA (nom, équipe, métriques, matchs, échantillon, sans renommage).
    detail_lead_columns: Optional[dict] = None
    detail_tail_columns: Optional[dict] = None
    # Tri par défaut de ce tableau (colonnes, sans tenir compte des accents ni de la casse ; la
    # saison est ajoutée en mode "Toutes les saisons") ; None = tri sur Y décroissant.
    detail_sort_columns: Optional[list] = None


# --- Sport actif ---------------------------------------------------------
NBA = SportConfig(
    key="nba",
    label="Basketball (NBA)",
    available=True,
    get_player_stats=nba.get_player_stats,
    seasons=nba.SEASONS,
    metrics=nba.METRICS,
    champions_by_season=nba.CHAMPIONS_BY_SEASON,
    award_badges_fn=nba.get_award_badges,
    award_icons=nba.AWARD_ICONS,
    award_labels=nba.AWARD_LABELS,
    radar_axes=nba.RADAR_AXES,
    compute_radar_scores=nba.compute_radar_scores,
    radar_caveats=nba.RADAR_CAVEATS,
    get_team_ranking=nba.get_team_ranking,
    team_ranking_metrics=nba.TEAM_RANKING_METRICS,
    get_teams_static=nba.get_teams_static,
    get_mercato_lineup=nba.get_mercato_lineup,
    get_team_identity=nba.get_team_identity,
    get_first_game_teams=nba.get_first_game_teams,
    # "2024-25" (pas la saison la plus récente) : décision explicite, temporaire. Le dataset
    # Kaggle ratin21 ne couvre pas encore 2025-26 (100 % des salaires y sont un repli sur la
    # saison précédente, voir l'avertissement dynamique du Dashboard et METHODOLOGY.md). À
    # repasser sur la plus récente une fois ratin21 mis à jour.
    default_season="2024-25",
    default_x="salary_musd",
    default_y="points_per_game",
    # PIE : 3e dimension analytique (impact global du joueur) en dégradé continu, plus lisible
    # qu'un nuage à 30 couleurs par équipe.
    default_color="pie",
)

# Rugby : performance uniquement, sans salaires. Top 14 et Pro D2 livrés (lot 4), Six Nations
# "bientôt disponible". Radar et classement des équipes pas encore branchés (None). Voir
# data_sources/rugby/.
RUGBY = SportConfig(
    key="rugby",
    label="Rugby",
    available=True,
    get_player_stats=rugby.get_player_stats,
    metrics=rugby.METRICS,
    competitions=rugby.COMPETITIONS,
    stats_periods=rugby.STATS_PERIODS,
    default_x="tackles_per80",
    default_y="metres_per80",
    default_color="position_family",
    source_caption=rugby.SOURCE_CAPTION,
    loading_label="Chargement des données rugby...",
    minutes_slider_max=80.0,
    minutes_slider_default=0.0,
    # Pro D2 : 30 journées et 3 matchs de phases finales au plus.
    games_slider_max=34,
    low_sample_label=rugby.LOW_SAMPLE_LABEL,
    show_low_sample_default=False,
    player_label_col="player_label",
    categorical_colors={
        "position_family": "Famille de poste (avants / arrières)",
        "position_group": "Poste",
        "team": "Équipe",
    },
    category_colors={"position_family": {
        "Avants": "#1f77b4", "Arrières": "#d62728", "Indéterminé": "#9e9e9e",
    }},
    legend_symbols=False,
    french_format=True,
    position_filter_col="position_group",
    position_order=rugby.POSITION_FILTER_ORDER,
    detail_lead_columns=rugby.DETAIL_LEAD_COLUMNS,
    detail_tail_columns=rugby.DETAIL_TAIL_COLUMNS,
    detail_sort_columns=["last_name", "first_name"],
)

# --- Sports à venir (aucune implémentation, juste affichés "bientôt") ----
MMA = SportConfig(key="mma", label="MMA", available=False)
TENNIS = SportConfig(key="tennis", label="Tennis", available=False)

SPORTS: dict[str, SportConfig] = {
    s.key: s for s in [NBA, RUGBY, MMA, TENNIS]
}
