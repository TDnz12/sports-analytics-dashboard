"""Télécharge une fois les logos d'époque des équipes NBA (1996-97 -> 2025-26) dans
static/logos/nba/ et écrit la table saison -> fichier data_sources/nba_logos.csv, lue par
pages/2_Effectifs.py (team_logo_url). Le site ne dépend ainsi jamais de la source extérieure :
les fichiers sont servis par Streamlit (server.enableStaticServing, voir .streamlit/config.toml).

Source : https://logocdn.com/nba/ (une carte par franchise actuelle, avec ses logos historiques
et leur période). Exception : le logo Indiana 1990-2005, absent de logocdn (lien mort, 404 sur
leur propre page), pris sur SportsLogos.net (voir FALLBACKS). Aucune des deux sources n'accorde
de licence : les logos sont la propriété de la NBA et de ses équipes, utilisés ici à titre non
commercial (mention affichée en bas de la page Effectifs).

Règle saison -> logo : pour chaque (saison, équipe) de nba.get_team_identity (code + nom
d'époque), le logo de la période qui commence le plus tard, au plus tard l'année de début de
la saison, parmi les logos de la franchise dont le nom de fichier correspond au nom d'époque
(ex: "Seattle SuperSonics" -> seattle-supersonics). Les bornes de FIN des périodes sont
ignorées : logocdn n'a pas de convention unique (Raptors "1995 - 2008" puis "2008 - 2015", qui
se chevauchent ; Hawks "1995 - 2006" puis "2007 - 2014").

PNG réduits à MAX_SIDE px de côté maximum (les originaux @3x pèsent jusqu'à 860 Ko), en gardant
la transparence ; SVG copiés tels quels.

Usage :
    .venv/bin/python scripts/update_nba_logos.py --dry-run   # affiche la table, ne télécharge rien
    .venv/bin/python scripts/update_nba_logos.py             # télécharge et écrit fichiers + table
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_sources import nba  # noqa: E402

LOGOCDN_PAGE = "https://logocdn.com/nba/"
LOGOCDN_FILES = "https://i.logocdn.com/nba/"
OUT_DIR = ROOT / "static" / "logos" / "nba"
TABLE = ROOT / "data_sources" / "nba_logos.csv"
MAX_SIDE = 200  # px : grille 32 px, vue effectif ~80 px, écrans haute densité compris
PAUSE_SECONDS = 0.5  # entre deux téléchargements, par politesse envers la source
HEADERS = {"User-Agent": "Mozilla/5.0 (sports-analytics-dashboard; logos NBA, usage non commercial)"}

# Fichier logocdn indisponible -> autre source (même statut : aucune licence accordée).
# SportsLogos.net nomme par année de FIN de saison : "1991" = logo utilisé de 1990-91 à 2004-05.
FALLBACKS = {
    "1990/indiana-pacers@3x.png":
        "https://content.sportslogos.net/logos/6/224/full/indiana-pacers-logo-primary-1991-2451.png",
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _normalize_team_name(name: str) -> str:
    # nba_api écrit parfois "LA Clippers", logocdn "Los Angeles Clippers" : même franchise.
    return "Los Angeles " + name[3:] if name.startswith("LA ") else name


def parse_logocdn(html: str) -> dict[str, list[dict]]:
    """{nom actuel de la franchise: [{start, path, slug}, ...]} depuis la page logocdn."""
    franchises = {}
    for card in re.split(r'<div class="col-md-4">', html)[1:]:
        entries = re.findall(
            r'<img class="card-img-top" data-src="([^"]+)".*?font-weight: bold;">(.*?)</div>', card, re.S
        )
        if not entries:
            continue
        eras = []
        for url, label in entries:
            path = re.sub(r"\s+", "", url).split("/nba/", 1)[1]  # certaines adresses contiennent un \n
            label = re.sub(r"<[^>]+>", " ", label)
            since = re.search(r"Since (\d{4})", label)
            start = int(since.group(1)) if since else int(label.strip()[:4])
            eras.append({"start": start, "path": path,
                         "slug": re.sub(r"(@3x)?\.(svg|png)$", "", path.split("/")[1])})
        current = re.match(r"\s*(.*?)\s*\(Since", re.sub(r"<[^>]+>", " ", entries[0][1])).group(1)
        franchises[current] = eras
    return franchises


def build_table(franchises: dict[str, list[dict]]) -> list[dict]:
    """Une ligne par (saison, équipe) de nba.get_team_identity, toutes saisons de nba.SEASONS."""
    identities = {s: nba.get_team_identity(s) for s in nba.SEASONS}
    latest = max(identities, key=lambda s: int(s[:4]))
    current_name = {int(r["team_id"]): _normalize_team_name(r["team_name"])
                    for _, r in identities[latest].iterrows()}
    rows, missing = [], []
    for season in sorted(identities):
        year = int(season[:4])
        for _, r in identities[season].sort_values("team").iterrows():
            eras = franchises.get(current_name.get(int(r["team_id"]), ""), [])
            want = _slug(_normalize_team_name(r["team_name"]))
            candidates = [e for e in eras if e["start"] <= year and e["slug"] == want]
            if not candidates:
                missing.append(f"{season} {r['team']} {r['team_name']}")
                continue
            era = max(candidates, key=lambda e: e["start"])
            source = FALLBACKS.get(era["path"], LOGOCDN_FILES + era["path"])
            ext = "svg" if era["path"].endswith(".svg") else "png"
            rows.append({"season": season, "team": r["team"], "team_name": r["team_name"],
                         "file": f"{era['start']}_{era['slug']}.{ext}", "source_url": source})
    if missing:
        raise SystemExit("Aucun logo trouvé pour :\n  " + "\n  ".join(missing))
    return rows


def download(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.content


def to_small_png(content: bytes) -> bytes:
    """PNG réduit à MAX_SIDE px de côté maximum, transparence conservée (RGBA, jamais de fond)."""
    img = Image.open(io.BytesIO(content))
    img = img.convert("RGBA")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def embedded_png(svg: bytes) -> bytes | None:
    """PNG encapsulé d'un "faux" SVG (aucun tracé vectoriel, une seule image base64 : Cleveland
    2022, Orlando 2025, Utah 2025 chez logocdn, jusqu'à 510 Ko) ; None pour un vrai SVG."""
    images = re.findall(rb'href="data:image/png;base64,([^"]+)"', svg)
    if len(images) != 1 or re.search(rb"<(path|polygon|circle|rect|ellipse|polyline)\b", svg):
        return None
    return base64.b64decode(images[0])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Affiche la table sans rien télécharger ni écrire.")
    args = parser.parse_args()

    html = requests.get(LOGOCDN_PAGE, headers=HEADERS, timeout=30).text
    rows = build_table(parse_logocdn(html))
    files = {r["file"]: r["source_url"] for r in rows}
    print(f"{len(rows)} couples (saison, équipe), {len(files)} fichiers "
          f"({Counter(f.rsplit('.', 1)[1] for f in files)})")
    if args.dry_run:
        for r in rows:
            print(f"  {r['season']} {r['team']:4} {r['file']:45} {r['source_url']}")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    final_name = {}  # nom prévu -> nom écrit (un "faux" SVG devient .png)
    for i, (planned, url) in enumerate(sorted(files.items()), start=1):
        name = planned
        content = download(url)
        if name.endswith(".svg"):
            if not content.lstrip().startswith((b"<svg", b"<?xml")):
                raise SystemExit(f"{url} : pas un SVG")
            png = embedded_png(content)
            if png is not None:
                name, content = name[:-4] + ".png", png
        if name.endswith(".png"):
            content = to_small_png(content)
        final_name[planned] = name
        (OUT_DIR / name).write_bytes(content)
        print(f"  [{i}/{len(files)}] {name} ({len(content) / 1024:.0f} Ko)")
        time.sleep(PAUSE_SECONDS)
    for r in rows:
        r["file"] = final_name[r["file"]]

    # Fichiers d'une version précédente qui ne servent plus : retirés.
    for stale in sorted(set(p.name for p in OUT_DIR.iterdir()) - set(final_name.values())):
        (OUT_DIR / stale).unlink()
        print(f"  retiré : {stale}")

    with TABLE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["season", "team", "team_name", "file", "source_url"])
        writer.writeheader()
        writer.writerows(rows)
    total = sum(p.stat().st_size for p in OUT_DIR.iterdir())
    print(f"Table : {TABLE.relative_to(ROOT)} ({len(rows)} lignes). "
          f"Logos : {OUT_DIR.relative_to(ROOT)} ({len(files)} fichiers, {total / 1e6:.2f} Mo).")


if __name__ == "__main__":
    main()
