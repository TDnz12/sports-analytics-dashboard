"""Logos d'époque de la page Effectifs : table data_sources/nba_logos.csv et fichiers
static/logos/nba/ (générés par scripts/update_nba_logos.py). Aucun accès réseau : les
identités d'équipe viennent des caches de data_cache/.

Lancer depuis la racine du projet : .venv/bin/python -m unittest tests.test_nba_logos
"""

import csv
import socket
import unittest
from unittest import mock
from pathlib import Path

from PIL import Image

from data_sources import nba

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "data_sources" / "nba_logos.csv"
LOGO_DIR = ROOT / "static" / "logos" / "nba"


def _no_network(*args, **kwargs):
    raise RuntimeError("réseau interdit dans ce test")


class NbaLogosTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with TABLE.open(encoding="utf-8") as f:
            cls.rows = list(csv.DictReader(f))
        cls.by_key = {(r["season"], r["team"]): r for r in cls.rows}

    def test_une_ligne_par_saison_et_equipe_sans_doublon(self):
        self.assertEqual(len(self.by_key), len(self.rows))
        self.assertEqual(list(self.rows[0]), ["season", "team", "team_name", "file", "source_url"])

    def test_couvre_toutes_les_equipes_de_chaque_saison(self):
        # Mêmes (saison, équipe) que nba.get_team_identity, lu depuis les caches (réseau coupé).
        with mock.patch.object(socket.socket, "connect", _no_network):
            for season in nba.SEASONS:
                teams = set(nba.get_team_identity(season)["team"])
                in_table = {team for (s, team) in self.by_key if s == season}
                self.assertEqual(in_table, teams, season)

    def test_chaque_fichier_existe_et_aucun_fichier_orphelin(self):
        used = {r["file"] for r in self.rows}
        present = {p.name for p in LOGO_DIR.iterdir()}
        self.assertEqual(used, present)

    def test_png_reduits_et_transparents(self):
        for path in sorted(LOGO_DIR.glob("*.png")):
            with Image.open(path) as img:
                self.assertEqual(img.mode, "RGBA", path.name)
                self.assertLessEqual(max(img.size), 200, path.name)
                self.assertLess(img.getchannel("A").getextrema()[0], 255, f"{path.name} sans transparence")

    def test_svg_valides_et_vraiment_vectoriels(self):
        for path in sorted(LOGO_DIR.glob("*.svg")):
            content = path.read_bytes()
            self.assertTrue(content.lstrip().startswith((b"<svg", b"<?xml")), path.name)
            self.assertNotIn(b"data:image/png;base64", content, f"{path.name} : image encapsulée")

    def test_source_notee_pour_chaque_fichier(self):
        for r in self.rows:
            host = r["source_url"].split("/")[2]
            if r["team"] == "IND" and r["file"] == "1990_indiana-pacers.png":
                self.assertEqual(host, "content.sportslogos.net")
            else:
                self.assertEqual(host, "i.logocdn.com", (r["season"], r["team"]))

    def test_logos_d_epoque_connus(self):
        expected = {
            ("2003-04", "TOR"): "1995_toronto-raptors.png",       # dinosaure
            ("2008-09", "TOR"): "2008_toronto-raptors.png",
            ("2003-04", "UTA"): "1996_utah-jazz.png",
            ("2004-05", "SEA"): "2001_seattle-supersonics.png",
            ("2008-09", "OKC"): "2008_oklahoma-city-thunder.svg",
            ("1999-00", "VAN"): "1995_vancouver-grizzlies.png",
            ("2005-06", "CHA"): "2004_charlotte-bobcats.png",
            ("1998-99", "CHH"): "1988_charlotte-hornets.png",
            ("2006-07", "NOK"): "2005_new-orleans-oklahoma-city-hornets.png",
            ("1996-97", "WAS"): "1987_washington-bullets.png",
            ("1996-97", "NJN"): "1990_new-jersey-nets.png",
            ("2000-01", "IND"): "1990_indiana-pacers.png",
            ("2005-06", "IND"): "2005_indiana-pacers.png",
            ("2025-26", "HOU"): "2019_houston-rockets.png",       # logo "Since 2026" = 2026-27
        }
        for key, file in expected.items():
            self.assertEqual(self.by_key[key]["file"], file, key)


if __name__ == "__main__":
    unittest.main()
