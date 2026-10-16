"""
Liste de recherche de joueurs, partagée par le Dashboard (un joueur) et le Radar (jusqu'à 4) :
composant maison st.components.v2 (sans iframe, styles isolés dans un shadow DOM), sur le modèle
de la grille Effectifs (pages/2_Effectifs.py). Code dans player_picker.js et player_picker.css.

Une seule case : la recherche se fait dans le navigateur à chaque lettre, sans relancer la page,
accents et casse ignorés, mots dans n'importe quel ordre (même normalisation que la grille
Effectifs). Le filtre intégré des listes Streamlit (selectbox, multiselect) ne fait que des
minuscules (« gael » ne trouve pas « Gaël »), d'où ce composant.

La sélection vit côté Python (st.session_state de la page) et part dans les données à chaque run :
présélection, saison et navigation passent donc par Python. Le composant ne renvoie que les vrais
changements de sélection (déclencheur "selection"), jamais la frappe ; chaque changement relance
le run une fois (voir player_picker).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import streamlit as st

_DIR = Path(__file__).parent
_CSS = (_DIR / "player_picker.css").read_text(encoding="utf-8")
_JS = (_DIR / "player_picker.js").read_text(encoding="utf-8")

TEXTS = {
    "empty": "Aucun joueur trouvé",
    "remove": "Retirer",
    "clear": "Désélectionner",
}


def player_picker(options: list, selected: list, on_change: Callable[[list], None], *, key: str,
                  label: str, max_selected: int, placeholder: str | None = None,
                  label_of: Callable[[Any], str] = str) -> None:
    """Monte la liste de recherche parmi `options` (clés, libellés : label_of), avec `selected`
    affiché. Quand l'utilisateur change la sélection (clic, Entrée ou croix), appelle
    on_change(nouvelle sélection : liste de clés, max_selected au plus) puis relance le run : le
    composant reçoit ainsi tout de suite la sélection à jour. Sans relance, il recevrait encore
    l'ancienne pendant un run, et l'afficherait de nouveau si l'utilisateur agissait avant le run
    suivant (choisir un joueur puis cliquer sa croix le faisait réapparaître). Le rappel du
    déclencheur ne peut pas servir : la valeur n'y est pas lisible (KeyError, vérifié). Les clés
    doivent être sérialisables en JSON."""
    allowed = set(options)
    data = {
        "options": [[o, label_of(o)] for o in options],
        "selected": [s for s in selected if s in allowed],
        "max": max_selected,
        "label": label,
        "placeholder": placeholder or "",
        "texts": {**TEXTS, "full": f"{max_selected} joueurs au maximum : retire un joueur pour en "
                                   "ajouter un." if max_selected > 1 else ""},
    }
    # Enregistré à chaque run avec une définition identique, comme la grille Effectifs : Streamlit
    # ne signale qu'une définition DIFFÉRENTE sous le même nom.
    component = st.components.v2.component("player_picker", css=_CSS, js=_JS)
    # on_selection_change : nécessaire pour déclarer le déclencheur ; sa valeur est lue dans le
    # résultat (comme grid.open_team dans pages/2_Effectifs.py).
    result = component(key=key, data=data, height="content", on_selection_change=lambda: None)
    new = result.selection
    if new is None:
        return
    new = [k for k in new if k in allowed][:max_selected]
    if new != data["selected"]:
        on_change(new)
        st.rerun()
