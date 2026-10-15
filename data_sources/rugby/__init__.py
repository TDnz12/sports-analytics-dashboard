"""
Rugby : Top 14 et Pro D2 (flux InCrowd), Six Nations (ESPN), regroupés sous une seule entrée
"Rugby" du sélecteur Sport, avec un sélecteur "Compétition" (voir SportConfig.competitions dans
data_sources/__init__.py).

Aucun appel réseau dans ce paquet (un test le vérifie) : les données sont téléchargées hors ligne
par scripts/rugby_download.py, transformées par scripts/rugby_build.py, puis seulement lues depuis
data_cache/. Le schéma commun aux deux sources est décrit dans schema.py.

État : Top 14 et Pro D2 disponibles dans le Dashboard (lot 4) et le Radar (lot 6, radar.py) ; Six
Nations "bientôt disponible" jusqu'au lot 8.
"""

from __future__ import annotations

from ..base import CompetitionConfig
from .positions import POSITION_GROUPS, UNDETERMINED
from .radar import (
    RADAR_AXES, RADAR_CAVEATS, RADAR_EXTRA_HELP, RADAR_MODE_HELP, RADAR_REFERENCE_CAPTION,
    compute_radar_scores, radar_axes_for, radar_card_lines, radar_extra_columns, radar_notes,
)
from .schema import COMPETITION_SPECS, season_labels
from .stats import (
    DETAIL_LEAD_COLUMNS, DETAIL_TAIL_COLUMNS, LOW_SAMPLE_LABEL, METRICS, SOURCE_CAPTION,
    get_player_stats,
)

# Compétitions livrées. Pro D2 ouvert au lot 4 avec le Top 14 (caches construits et contrôlés au
# lot 3), avant le Six Nations : décision du 13 octobre 2026, qui avance le lot 9.
AVAILABLE_COMPETITIONS = {"top14", "prod2"}

COMPETITIONS: list[CompetitionConfig] = [
    CompetitionConfig(
        key=spec.key, label=spec.label, mode=spec.mode,
        available=spec.key in AVAILABLE_COMPETITIONS, seasons=season_labels(spec.key),
    )
    for spec in COMPETITION_SPECS.values()
]

# Libellés des périodes du sélecteur "Statistiques utilisées" (clés de schema.PERIODS). La première
# est le défaut, et la seule utilisée en mode "Toutes les saisons".
STATS_PERIODS = {
    "Saison complète (phases finales incluses)": "all",
    "Phase régulière": "regular",
}

# Ordre des postes dans le filtre "poste" du Dashboard : avants puis arrières, du 1 au 15.
POSITION_FILTER_ORDER = POSITION_GROUPS + [UNDETERMINED]
