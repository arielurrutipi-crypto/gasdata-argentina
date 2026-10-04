"""Complete official regulator catalogue; deliberately no topic filtering."""
import re
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

SOURCE = "https://www.enargas.gob.ar/secciones/normativa/resoluciones.php"
ENDPOINT = "https://www.enargas.gob.ar/secciones/normativa/includes/get-normas.php"

def parse_catalogue(raw, year, issuer):
    soup = BeautifulSoup(raw, "html.parser")
    table = soup.find("table", id="tableFiltro")
    if table is None:
        if "sin resultados" in soup.get_text(" ", strip=True).lower(): return []
        raise ValueError("El catálogo oficial no devolvió su tabla de resoluciones")
    out = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        if len(cells) < 5: raise ValueError("Fila incompleta en el catálogo oficial")
        number, date, desc, kind = [c.get_text(" ", strip=True) for c in cells[:4]]
        day = datetime.strptime(date.strip(), "%d/%m/%Y").date().isoformat()
        link = cells[4].find("a", href=True)
        desc = re.sub(r"\s+", " ", desc)
        brief = re.sub(r"^(?:RESUELVE:\s*)?(?:ART[ÍI]CULO\s*1[°º]?[.\-:\s]*)?", "", desc, flags=re.I).strip()
        brief = re.split(r"ART[ÍI]CULO\s*2[°º]?", brief, flags=re.I)[0].strip()
        if len(brief) > 360: brief = brief[:360].rsplit(" ", 1)[0] + "…"
        label = kind if issuer.lower() in kind.lower() else issuer + " " + kind
        out.append({"num": f"{label} {number}/{year}", "number": number,
                    "issuer": issuer, "type": kind, "date": day,
                    "desc": brief or desc[:360], "url": link["href"] if link else SOURCE})
    return out

def update_resolution_export(d, now, iso):
    state = d.setdefault("resolutionExport", {})
    try:
        if state.get("complete") and now()-datetime.fromisoformat(state["checkedAt"]) < timedelta(hours=3): return
    except (KeyError, ValueError, TypeError): pass
    year = now().year
    specs = [(6, "ENReGE"), (1, "ENARGAS")]
    def load(spec):
        kind, issuer = spec
        req = urllib.request.Request(ENDPOINT, data=urllib.parse.urlencode({"tipo":kind,"ano":year,"numero":0}).encode(),
                                     headers={"User-Agent":"Mozilla/5.0 (GasData Argentina)"})
        with urllib.request.urlopen(req, timeout=35) as response: raw = response.read()
        return parse_catalogue(raw, year, issuer)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(load, specs))
        rows = [r for group in results for r in group]
        if not rows: raise ValueError("El catálogo anual está vacío; se conserva la versión anterior")
        state.update(rows=sorted(rows,key=lambda r:(r["date"],r["num"]),reverse=True),
                     checkedAt=iso(), complete=True, sourceUrl=SOURCE,
                     fromDate=f"{year}-01-01", toDate=now().date().isoformat(),
                     dateMeaning="Fecha de la resolución en el catálogo oficial", error=None)
    except Exception as e:
        state.update(checkedAt=iso(), complete=False, error=str(e)[:240], sourceUrl=SOURCE)
