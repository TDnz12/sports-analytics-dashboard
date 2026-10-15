"""Garde-fou des tests censés tourner sans réseau. get_player_stats avale volontairement les
erreurs réseau (repli sans cache écrit) : un appel non remplacé par une doublure ferait donc
échouer le test plus loin, sans dire pourquoi. Ici, chaque tentative de connexion est notée et
le test échoue à la fin avec la liste des appels.

Usage, dans setUp : sans_reseau.couper_reseau(self)
"""

import socket
from unittest import mock


def couper_reseau(test_case):
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(args[:2])
        raise OSError("réseau coupé par tests/sans_reseau.py")

    # Vérification enregistrée avant les patchs : addCleanup est dépilé à l'envers, elle passe
    # donc après leur retrait.
    test_case.addCleanup(lambda: test_case.assertEqual(
        attempts, [], "accès réseau dans un test sans réseau : une fonction _fetch_* n'est pas remplacée"))
    for target in ("socket.socket.connect", "socket.getaddrinfo", "socket.create_connection"):
        patcher = mock.patch(target, refuse)
        patcher.start()
        test_case.addCleanup(patcher.stop)
