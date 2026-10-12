"""
Rugby : Top 14 et Pro D2 (flux InCrowd), Six Nations (ESPN), regroupés sous une seule entrée
"Rugby" du sélecteur Sport, avec un sélecteur "Compétition" (voir SportConfig.competitions dans
data_sources/__init__.py).

Aucun appel réseau dans ce paquet (un test le vérifie) : les données sont téléchargées hors ligne
par scripts/rugby_download.py, transformées par scripts/rugby_build.py, puis seulement lues depuis
data_cache/. Le schéma commun aux deux sources est décrit dans schema.py.

État : squelette. Aucune compétition n'est encore disponible (available=False) ; elles passent à
True au fur et à mesure que leurs données et leurs pages sont livrées.
"""

from __future__ import annotations

from ..base import CompetitionConfig
from .schema import COMPETITION_SPECS, season_labels

COMPETITIONS: list[CompetitionConfig] = [
    CompetitionConfig(
        key=spec.key, label=spec.label, mode=spec.mode, available=False,
        seasons=season_labels(spec.key),
    )
    for spec in COMPETITION_SPECS.values()
]
