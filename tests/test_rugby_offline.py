"""Le paquet data_sources/rugby/ ne fait aucun appel réseau : le site en ligne ne lit que les caches
de data_cache/, le téléchargement vit uniquement dans scripts/rugby_download.py.

Deux vérifications : aucun module du paquet n'importe une bibliothèque réseau (lecture du code,
sans l'exécuter), et le paquet s'importe avec toute ouverture de connexion interdite.

Lancer depuis la racine du projet : .venv/bin/python -m unittest discover -s tests -t .
"""

import ast
import importlib
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

import data_sources

RUGBY_DIR = Path(data_sources.__file__).resolve().parent / "rugby"
NETWORK_MODULES = {"requests", "urllib", "http", "socket", "httpx", "aiohttp", "nba_api", "kagglehub"}


def _imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


class SansReseauTest(unittest.TestCase):
    def test_aucun_import_reseau(self):
        files = sorted(RUGBY_DIR.glob("*.py"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(fichier=path.name):
                self.assertFalse(_imported_roots(path) & NETWORK_MODULES)

    def test_import_sans_connexion(self):
        def interdit(*args, **kwargs):
            raise AssertionError("connexion réseau tentée")

        for name in [m for m in sys.modules if m.startswith("data_sources.rugby")]:
            del sys.modules[name]
        with mock.patch.object(socket, "socket", interdit), \
                mock.patch.object(socket, "create_connection", interdit):
            importlib.import_module("data_sources.rugby")
            importlib.import_module("data_sources.rugby.schema")


if __name__ == "__main__":
    unittest.main()
