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
changements de sélection (déclencheur "selection"), jamais la frappe. Synchronisation sans
relance ni clignotement : numéros seq et epoch, voir player_picker.
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
    on_change(nouvelle sélection : liste de clés, max_selected au plus). Les clés doivent être
    sérialisables en JSON.

    Synchronisation, sans relance forcée (une relance faisait clignoter la case en ligne : le
    joueur choisi s'affichait, disparaissait, puis réapparaissait). Le run qui reçoit un clic a déjà
    envoyé au composant l'ancienne sélection : le composant doit pouvoir l'ignorer.
    - seq : chaque changement envoyé par le composant porte un numéro croissant ; Python garde le
      dernier reçu et le renvoie avec la sélection. Le composant ignore une sélection dont le
      numéro est plus ancien que son dernier changement (player_picker.js, acceptSelection).
    - epoch : quand la sélection envoyée diffère de celle que le composant affiche (dernier choix
      reçu ou dernier envoi), c'est Python qui l'impose (présélection du bouton « Voir le profil
      radar », saison où le joueur n'existe pas, navigation) : epoch augmente, et le composant
      applique toujours une epoch plus récente.
    État dans st.session_state["_player_picker_sync_<key>"] (hors widget : gardé d'une page à
    l'autre, pour que les numéros continuent quand le composant est remonté)."""
    allowed = set(options)
    shown = [s for s in selected if s in allowed]
    sync = st.session_state.setdefault(f"_player_picker_sync_{key}",
                                       {"seq": 0, "epoch": 0, "shown": None})
    if sync["shown"] is not None and shown != sync["shown"]:
        sync["epoch"] += 1
    sync["shown"] = shown
    data = {
        "options": [[o, label_of(o)] for o in options],
        "selected": shown,
        "seq": sync["seq"],
        "epoch": sync["epoch"],
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
    event = result.selection
    if not isinstance(event, dict) or int(event.get("seq", 0)) <= sync["seq"]:
        return
    sync["seq"] = int(event["seq"])
    new = [k for k in event.get("keys", []) if k in allowed][:max_selected]
    sync["shown"] = new
    if new != shown:
        on_change(new)
