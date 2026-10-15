"""Instantanés NBA : vérifie que les pages NBA affichent exactement la même chose qu'un commit de
référence (par défaut HEAD), pour tout changement qui touche du code commun aux sports.

Rend 11 situations NBA avec AppTest (Dashboard, Radar, Effectifs), une fois dans une copie du
commit de référence (git archive, dossier temporaire supprimé à la fin) et une fois dans la copie
de travail, puis compare tout ce qui est affiché : titres, textes, messages, widgets (libellés,
options, aides), tableaux et graphs (empreinte SHA-1 de leur contenu complet). Les identifiants
internes des widgets sont ignorés (ils changent avec les clés, sans effet visible).

Lancer depuis la racine du projet, avant le commit d'un lot :
    .venv/bin/python scripts/instantanes_nba.py              # copie de travail contre HEAD
    .venv/bin/python scripts/instantanes_nba.py --ref f39b8ac
Code de sortie 0 si tout est identique, 1 sinon (les différences sont affichées). Lit les caches
de data_cache/ sans les modifier (écritures interceptées). Durée : quelques minutes.
"""

import argparse
import difflib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DASH, RADAR, EFFECTIFS = "Dashboard.py", "pages/1_Radar_de_comparaison.py", "pages/2_Effectifs.py"
FOUR = ["Shai Gilgeous-Alexander", "Luka Dončić", "Nikola Jokić", "Victor Wembanyama"]
KINDS = ("title", "header", "subheader", "markdown", "caption", "info", "warning", "error",
         "success", "metric", "selectbox", "multiselect", "radio", "slider", "checkbox", "toggle",
         "button", "text_input", "expander", "tabs")


def capture(out_path: str) -> None:
    """Rend les situations NBA du code du dossier courant et écrit leur contenu dans out_path."""
    sys.path.insert(0, os.getcwd())
    import data_sources.base as base
    import data_sources.nba as nba
    nba.write_cache = base.write_cache = lambda df, path, **k: None
    from streamlit.testing.v1 import AppTest

    lines = []

    def dump(at, name):
        lines.append(f"######## {name}")
        lines.append(f"exceptions : {[e.message for e in at.exception]}")
        for kind in KINDS:
            for e in at.get(kind):
                lines.append(f"[{kind}] {e.proto}".replace("\n", " | "))
        for d in at.dataframe:
            csv = d.value.to_csv()
            lines.append(f"[dataframe] colonnes={list(d.value.columns)} lignes={len(d.value)} "
                         f"sha1={hashlib.sha1(csv.encode()).hexdigest()}")
        for c in at.get("plotly_chart"):
            lines.append(f"[plotly] sha1={hashlib.sha1(c.proto.spec.encode()).hexdigest()}")

    def new(page, state=None):
        # Chemin absolu : AppTest résout un chemin relatif par rapport au fichier appelant.
        at = AppTest.from_file(str(Path.cwd() / page), default_timeout=300)
        for k, v in (state or {}).items():
            at.session_state[k] = v
        return at.run()

    def select(at, label):
        return next(s for s in at.selectbox if s.label == label)

    at = new(DASH); dump(at, "Dashboard par défaut")
    select(at, "Statistiques utilisées").set_value("Playoffs uniquement").run(); dump(at, "Dashboard playoffs")
    at = new(DASH); select(at, "Saison").set_value("2010-11").run(); dump(at, "Dashboard 2010-11")
    at = new(DASH); select(at, "Rechercher un joueur").set_value("Nikola Jokić").run(); dump(at, "Dashboard recherche Jokić")
    at = new(DASH); select(at, "Saison").set_value(select(at, "Saison").options[0]).run(); dump(at, "Dashboard toutes les saisons")
    at = new(RADAR); dump(at, "Radar par défaut")
    at.multiselect(key="radar_players").set_value(FOUR).run(); dump(at, "Radar 4 joueurs")
    next(r for r in at.radio if "Centile" in r.options).set_value("Centile").run(); dump(at, "Radar 4 joueurs, centile")
    at = new(RADAR); select(at, "Statistiques utilisées").set_value("Playoffs uniquement").run(); dump(at, "Radar playoffs")
    at = new(RADAR, {"radar_preselect_player": "Nikola Jokić", "radar_preselect_season": "2023-24"}); dump(at, "Radar présélection Jokić 2023-24")
    at = new(EFFECTIFS); dump(at, "Effectifs par défaut")
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalize(text: str) -> list[str]:
    """Retire les identifiants internes des widgets et les marques d'état sans effet visible."""
    text = re.sub(r'id: "[^"]*" \| ', "", text)
    text = re.sub(r'(set_value: true|raw_value: "[^"]*") \| ', "", text)
    return text.splitlines()


def run_capture(tree: Path, out: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(tree)}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--capture", str(out)],
                            cwd=tree, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"Échec du rendu dans {tree} :\n{result.stderr[-3000:]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ref", default="HEAD", help="commit de référence (défaut : HEAD)")
    parser.add_argument("--capture", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.capture:
        capture(args.capture)
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="instantanes_nba_"))
    try:
        ref_tree = tmp / "reference"
        ref_tree.mkdir()
        archive = subprocess.run(["git", "archive", args.ref], cwd=ROOT, capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(ref_tree)], input=archive.stdout, check=True)
        print(f"Rendu du commit {args.ref}...", flush=True)
        run_capture(ref_tree, tmp / "reference.txt")
        print("Rendu de la copie de travail...", flush=True)
        run_capture(ROOT, tmp / "travail.txt")
        before = normalize((tmp / "reference.txt").read_text(encoding="utf-8"))
        after = normalize((tmp / "travail.txt").read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    diff = list(difflib.unified_diff(before, after, f"commit {args.ref}", "copie de travail", lineterm="", n=0))
    if not diff:
        print(f"Identique : les 11 situations NBA affichent la même chose qu'au commit {args.ref}.")
        return 0
    print("\n".join(line[:400] for line in diff))
    print(f"\n{sum(1 for l in diff if l[:1] in '+-' and l[:3] not in ('+++', '---'))} lignes différentes.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
