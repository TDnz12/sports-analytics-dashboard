"""Recherche des listes de joueurs sans accents ni casse (base.search_key, base.filter_options) :
le filtre intégré des listes Streamlit ne fait que des minuscules. Lit les caches de data_cache/."""

import unittest

import pandas as pd

from data_sources.base import filter_options, search_key
from data_sources.rugby import stats as rugby_stats


class SearchKeyTest(unittest.TestCase):
    def test_accents_et_casse(self):
        self.assertEqual(search_key("Gaël Fickou"), "gael fickou")
        self.assertEqual(search_key("Luka DONČIĆ"), "luka doncic")


class FilterOptionsTest(unittest.TestCase):
    def test_gael_trouve_fickou_en_rugby(self):
        names = sorted(rugby_stats.get_player_stats("2025-26", competition="top14")["player"])
        self.assertIn("Gaël Fickou", filter_options(names, "gael"))
        self.assertEqual(filter_options(names, "gael f"), ["Gaël Fickou"])

    def test_doncic_trouve_doncic_en_nba(self):
        names = sorted(pd.read_parquet("data_cache/processed/nba/2024-25.parquet")["player"])
        self.assertEqual(filter_options(names, "doncic"), ["Luka Dončić"])
        self.assertEqual(filter_options(names, "DONČIĆ"), ["Luka Dončić"])

    def test_beziers(self):
        teams = sorted(set(rugby_stats.get_player_stats("2025-26", competition="prod2")["team"]))
        self.assertEqual(filter_options(teams, "beziers"), ["Béziers"])

    def test_selections_gardees_a_leur_place(self):
        options = ["Aucun", "Antoine Dupont", "Gaël Fickou", "Romain Ntamack"]
        self.assertEqual(filter_options(options, "gael", keep={"Aucun", "Romain Ntamack"}),
                         ["Aucun", "Gaël Fickou", "Romain Ntamack"])

    def test_requete_vide(self):
        options = ["Gaël Fickou", "Antoine Dupont"]
        for query in ("", "   ", None):
            self.assertEqual(filter_options(options, query), options)

    def test_libelle_personnalise(self):
        labels = {"icw:1": "Gaël Fickou (Racing 92) · Centre", "icw:2": "Antoine Dupont (Toulouse) · Demi de mêlée"}
        self.assertEqual(filter_options(list(labels), "racing", label=labels.get), ["icw:1"])
        self.assertEqual(filter_options(list(labels), "demi de melee", label=labels.get), ["icw:2"])


if __name__ == "__main__":
    unittest.main()
