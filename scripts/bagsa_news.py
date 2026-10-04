"""Persistent cross-publisher news archive for BAGSA mentions."""
import hashlib
import re
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup

START = datetime(2026, 1, 1).date()
TERMS = '("BAGSA" OR "Buenos Aires Gas")'
MATCH = re.compile(r"\bBAGSA\b|buenos\s+aires\s+gas", re.I)

def clean(value):
    return re.sub(r"\s+", " ", BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)).strip()

def identity(row):
    title = unicodedata.normalize("NFKD", row.get("title", "")).encode("ascii", "ignore").decode().lower()
    title = re.sub(r"\W+", " ", title).strip()
    host = urllib.parse.urlparse(row.get("sourceUrl") or row.get("url") or "").hostname or row.get("source", "").lower()
    host = host.removeprefix("www.")
    return hashlib.sha256((host+"|"+title+"|"+row.get("publishedAt", "")[:10]).encode()).hexdigest()

def search_url(start, end):
    query = TERMS + " after:" + (start-timedelta(days=1)).isoformat() + " before:" + (end+timedelta(days=1)).isoformat()
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "es-419", "gl": "AR", "ceid": "AR:es-419"})

def read_feed(raw, start, end, checked):
    root = ET.fromstring(raw)
    out = []
    items = root.findall(".//item")
    for item in items:
        try:
            date = parsedate_to_datetime(item.findtext("pubDate"))
            if date.tzinfo is None: date = date.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError): continue
        if not start <= date.date() <= end: continue
        node = item.find("source")
        source = clean(node.text if node is not None else "") or "Medio no informado"
        title = clean(item.findtext("title"))
        suffix = " - " + source
        if title.endswith(suffix): title = title[:-len(suffix)]
        link = (item.findtext("link") or "").strip()
        if not title or not link.startswith(("https://", "http://")): continue
        row = {"title": title, "source": source, "sourceUrl": node.get("url", "") if node is not None else "",
               "publishedAt": date.isoformat(timespec="seconds"), "dateType": "published",
               "url": link, "provider": "Google News", "matchedBy": "Búsqueda BAGSA / Buenos Aires Gas",
               "firstSeenAt": checked, "lastSeenAt": checked, "desc": "", "edition": "national"}
        row["id"] = identity(row)
        out.append(row)
    return out, len(items)

def update_bagsa_news(d, now, iso):
    state = d.setdefault("bagsaNewsScan", {})
    archive = {row.get("id") or identity(row): row for row in d.get("bagsaNews", [])}
    # Mentions discovered by the existing media readers join the same permanent archive.
    for row in d.get("news", []):
        if not MATCH.search(row.get("title", "")+" "+row.get("desc", "")): continue
        if row.get("dateType") == "unknown": continue
        key = identity(row)
        if key not in archive:
            archive[key] = {**row, "id": key, "firstSeenAt": iso(), "lastSeenAt": iso(),
                            "matchedBy": "Mención en el título o resumen de una fuente consultada"}
    today = now().date()
    checked = iso()
    ranges = []
    if not state.get("initialBackfillComplete"):
        start = START
        while start <= today:
            next_month = (start.replace(day=28)+timedelta(days=4)).replace(day=1)
            ranges.append((start, min(today, next_month-timedelta(days=1))))
            start = next_month
    else:
        ranges = [(max(START, today-timedelta(days=7)), today)]
    def fetch_range(pair):
        start, end = pair
        url = search_url(start, end)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (GasData Argentina)"})
            with urllib.request.urlopen(request, timeout=25) as response: raw = response.read()
            rows, count = read_feed(raw, start, end, checked)
            return rows, None if count < 100 else "La búsqueda alcanzó 100 resultados: cobertura posiblemente incompleta"
        except Exception as error: return [], str(error)[:180]
    new_count = 0
    errors = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for pair, result in zip(ranges, pool.map(fetch_range, ranges)):
            rows, error = result
            if error: errors.append({"from": pair[0].isoformat(), "to": pair[1].isoformat(), "error": error})
            for row in rows:
                key = row["id"]
                if key in archive:
                    archive[key]["lastSeenAt"] = checked
                else:
                    archive[key] = row; new_count += 1
    # No length limit: older BAGSA items are never evicted by the general-news window.
    d["bagsaNews"] = sorted(archive.values(), key=lambda row: row.get("publishedAt", ""), reverse=True)
    state.update(checkedAt=checked, nextAt=iso(now()+timedelta(hours=1)),
                 startDate=START.isoformat(), newCount=new_count, total=len(archive), errors=errors,
                 status="partial" if errors else "updated" if new_count else "unchanged",
                 query=TERMS, provider="Google News · medios indexados")
    if not errors: state["initialBackfillComplete"] = True
    source = next((row for row in d.setdefault("sources", []) if row.get("name") == "Noticias BAGSA · búsqueda abierta"), None)
    values = {"name": "Noticias BAGSA · búsqueda abierta", "type": "Monitoreo de prensa",
              "url": search_url(START, today), "content": "BAGSA / Buenos Aires Gas en medios diversos · archivo persistente desde 01/01/2026",
              "cadence": "Cada hora", "checkedAt": checked, "status": "REVISAR" if errors else "ACTIVA"}
    if not errors: values["validatedAt"] = checked
    if source: source.update(values)
    else: d["sources"].append(values)
    update = next((row for row in d.get("updates", []) if row.get("name") == "Noticias"), None)
    if update:
        update["note"] = update.get("note", "") + f" BAGSA: {new_count} notas nuevas, {len(archive)} guardadas."
        if errors: update["status"] = "partial"
