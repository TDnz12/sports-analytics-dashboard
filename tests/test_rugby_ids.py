"""Identifiants internes du rugby (data_sources/rugby/schema.py) : "{source}:{id natif}", pour ne
jamais confondre un identifiant InCrowd et un identifiant ESPN.

Aucun accès réseau ni disque.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import unittest

import numpy as np

from data_sources.rugby import schema


class MakeUidTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(schema.make_uid("icw", 122907), "icw:122907")
        self.assertEqual(schema.make_uid("espn", "238367"), "espn:238367")
        self.assertEqual(schema.make_uid("icw", np.int64(4188)), "icw:4188")

    def test_meme_nombre_deux_sources(self):
        self.assertNotEqual(schema.make_uid("icw", 9), schema.make_uid("espn", 9))

    def test_refus(self):
        # "122907.0" : id passé par un float pandas (NaN dans la colonne), "nan", vide, None,
        # source inconnue.
        for source, native in [("icw", "122907.0"), ("icw", 122907.0), ("icw", "nan"),
                               ("icw", ""), ("icw", None), ("opta", 1)]:
            with self.subTest(source=source, native=native):
                with self.assertRaises(ValueError):
                    schema.make_uid(source, native)


class ParseUidTest(unittest.TestCase):
    def test_aller_retour(self):
        for source, native in [("icw", "122907"), ("espn", "602516")]:
            self.assertEqual(schema.parse_uid(schema.make_uid(source, native)), (source, native))

    def test_refus(self):
        for uid in ["122907", "icw:", "icw:12a", "opta:1", "icw122907", None]:
            with self.subTest(uid=uid):
                with self.assertRaises(ValueError):
                    schema.parse_uid(uid)


if __name__ == "__main__":
    unittest.main()
