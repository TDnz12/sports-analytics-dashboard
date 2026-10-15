"""Bandeau "données partielles" (data_sources.base.incomplete_data_warning) : texte affiché par le
Dashboard et le Radar quand get_player_stats n'a pas pu charger une partie des données.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import unittest

import pandas as pd

from data_sources.base import INCOMPLETE_DATA_ATTR, incomplete_data_warning


def _frame(missing=None):
    df = pd.DataFrame({"player": ["A"]})
    if missing is not None:
        df.attrs[INCOMPLETE_DATA_ATTR] = missing
    return df


class DonneesPartiellesTest(unittest.TestCase):
    def test_rien_ne_manque(self):
        self.assertIsNone(incomplete_data_warning(_frame(), "2024-25"))
        self.assertIsNone(incomplete_data_warning(_frame([]), "2024-25"))

    def test_un_manque(self):
        self.assertEqual(
            incomplete_data_warning(_frame(["fiabilité"]), "2024-25"),
            "Données partielles pour 2024-25 : fiabilité indisponible. Les autres stats ne sont pas concernées.",
        )

    def test_trois_manques(self):
        self.assertEqual(
            incomplete_data_warning(_frame(["totaux de tirs", "fiabilité", "équipe du dernier match"]), "2022-23"),
            "Données partielles pour 2022-23 : 3PT% et LF% ajustés indisponibles ; fiabilité indisponible ; "
            "équipe affichée = équipe d'inscription, pas forcément la dernière. "
            "Les autres stats ne sont pas concernées.",
        )


if __name__ == "__main__":
    unittest.main()
