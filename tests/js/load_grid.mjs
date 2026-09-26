// Charge le JS de la grille (constante MERCATO_GRID_JS de pages/2_Effectifs.py) comme un module
// ES : le code testé est exactement celui de la page, sans copie à tenir à jour. Utilisé par
// test_state.mjs et test_dom.mjs.

import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const PAGE = new URL("../../pages/2_Effectifs.py", import.meta.url);

export async function loadGrid() {
  const source = readFileSync(PAGE, "utf8");
  const match = source.match(/^MERCATO_GRID_JS = r"""\n([\s\S]*?)^"""/m);
  if (!match) throw new Error("MERCATO_GRID_JS introuvable dans pages/2_Effectifs.py");
  const file = join(mkdtempSync(join(tmpdir(), "grille-")), "grid.mjs");
  writeFileSync(file, match[1]);
  return import(pathToFileURL(file).href);
}
