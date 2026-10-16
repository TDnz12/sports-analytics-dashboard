"""Pilote de la liste de recherche de joueurs (player_picker) dans AppTest, comme la grille
Effectifs (tests/apptest_effectifs.py) : AppTest ne fait pas tourner le JavaScript du composant.
On lit les données que Python lui envoie (étiquette, options, sélection affichée, placeholder) et on
simule ce que le navigateur renvoie après un clic ou Entrée : le déclencheur "selection" avec la
nouvelle liste de clés. La recherche, le clavier et l'affichage sont testés à part, dans
tests/js/test_picker.mjs.

Usage :  data(at, "Rechercher un joueur")["selected"] ; choisir(at, "Joueurs (1 à 4)", [clés])
"""

import json

from streamlit.components.v2.bidi_component.main import _make_trigger_id


def _find(node, typ):
    kids = getattr(node, "children", None)
    if isinstance(kids, dict):
        for ch in kids.values():
            if ch.type == typ:
                yield ch
            yield from _find(ch, typ)


def _picker(at, label):
    for el in _find(at._tree, "bidi_component"):
        d = json.loads(el.proto.json)
        if isinstance(d, dict) and d.get("label") == label:
            return el, d
    raise AssertionError(f"liste de recherche « {label} » introuvable")


def data(at, label):
    """Données envoyées au composant d'étiquette `label` : options [[clé, libellé]], selected, max,
    placeholder, texts."""
    return _picker(at, label)[1]


def choisir(at, label, keys):
    """Simule un changement de sélection dans le navigateur (clic, Entrée ou croix)."""
    el, _ = _picker(at, label)
    ws = at._tree.get_widget_states()
    w = ws.widgets.add()
    w.id = _make_trigger_id(el.proto.id, "events")
    w.json_trigger_value = json.dumps([{"event": "selection", "value": list(keys)}])
    at._run(widget_state=ws)
    assert not at.exception, at.exception
