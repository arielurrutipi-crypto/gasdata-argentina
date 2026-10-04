"""Publication-dated news with source metadata; detection never counts as publication."""
import json
import re
import html
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from news_translation import translate_news

SOURCES = [
    ("EconoJournal", "https://econojournal.com.ar/", "https://econojournal.com.ar/feed/"),
    ("RunRun Energético", "https://runrunenergetico.com/", "https://runrunenergetico.com/feed/"),
    ("Más Energía · LM Neuquén", "https://mase.lmneuquen.com/", None),
    ("Mejor Energía", "https://www.mejorenergia.com.ar/", None),
    ("Revista Petroquímica", "https://revistapetroquimica.com/", "https://revistapetroquimica.com/feed/"),
    ("América GLP", "https://www.americaglp.com/", None),
    ("TGS", "https://www.tgs.com.ar/", None),
    ("TGN", "https://www.tgn.com.ar/prensa-y-novedades/comunicaciones/", None),
    ("ENReGE · Noticias", "https://www.enargas.gob.ar/secciones/noticias/noticias.php", None),
    ("Secretaría de Energía", "https://www.argentina.gob.ar/economia/energia/noticias", None),
    ("LNG Industry", "https://www.lngindustry.com/", "https://www.lngindustry.com/rss/lngindustry.xml"),
    ("Offshore Energy", "https://www.offshore-energy.biz/", "https://www.offshore-energy.biz/feed/"),
    ("Energy Global", "https://www.energyglobal.com/", "https://www.energyglobal.com/rss/energyglobal.xml"),
]

INTERNATIONAL = {"LNG Industry", "Offshore Energy", "Energy Global"}

def text(value):
    return re.sub(r"\s+", " ", BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)).strip()

def published(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(str(value))
        except (ValueError, TypeError):
            return None
    # A calendar day without a time cannot substantiate a rolling 24-hour window.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value).strip()):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone(timedelta(hours=-3)))
    return d.isoformat(timespec="seconds")

def web_url(value, base):
    url = urllib.parse.urljoin(base, html.unescape(str(value or "")))
    return url if urllib.parse.urlparse(url).scheme in ("http", "https") else ""

def metadata(raw, url):
    soup = BeautifulSoup(raw, "html.parser")
    out = {}
    for key, names in {
        "publishedAt": ("article:published_time", "datePublished", "pubdate", "date"),
        "imageUrl": ("og:image", "twitter:image"),
        "desc": ("og:description", "description", "twitter:description"),
    }.items():
        for name in names:
            node = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"itemprop": name})
            if node and node.get("content"):
                out[key] = node["content"]
                break
    def visit(obj):
        if isinstance(obj, list):
            for child in obj: visit(child)
        elif isinstance(obj, dict):
            if obj.get("datePublished"): out.setdefault("publishedAt", obj["datePublished"])
            if obj.get("headline"):
                out.setdefault("title", text(obj["headline"]))
                out.setdefault("desc", obj.get("description", ""))
                img = obj.get("image")
                if isinstance(img, list): img = img[0] if img else None
                if isinstance(img, dict): img = img.get("url") or img.get("contentUrl")
                if img: out.setdefault("imageUrl", img)
            for child in obj.values():
                if isinstance(child, (list, dict)): visit(child)
    for node in soup.find_all("script", type="application/ld+json"):
        try: visit(json.loads(node.string or node.get_text()))
        except (ValueError, TypeError): pass
    if not out.get("publishedAt"):
        node = soup.find("time", datetime=True)
        if node: out["publishedAt"] = node["datetime"]
    out["publishedAt"] = published(out.get("publishedAt"))
    out["imageUrl"] = web_url(out.get("imageUrl"), url)
    out["desc"] = text(out.get("desc"))[:240]
    return out

def feed_items(raw, source):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        decoded = raw.decode("utf-8", "replace")
        decoded = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)", "&amp;", decoded)
        root = ET.fromstring(decoded)
    out = []
    for node in root.findall(".//item")[:60]:
        url = (node.findtext("link") or "").strip()
        title = text(node.findtext("title"))
        if not url or not title: continue
        content = node.findtext("description") or ""
        encoded = node.find("{http://purl.org/rss/1.0/modules/content/}encoded")
        if encoded is not None: content += encoded.text or ""
        image = ""
        for child in node.iter():
            if child.tag.split("}")[-1] in ("content", "thumbnail", "enclosure") and child.get("url"):
                if child.get("medium") == "image" or child.get("type", "").startswith("image/") or child.tag.endswith("thumbnail"):
                    image = child.get("url"); break
        if not image:
            img = BeautifulSoup(content, "html.parser").find("img")
            if img: image = img.get("src") or img.get("data-src") or ""
        out.append({"source": source, "title": title, "url": url,
                    "desc": text(node.findtext("description"))[:240],
                    "publishedAt": published(node.findtext("pubDate")),
                    "imageUrl": web_url(image, url), "dateType": "published" if published(node.findtext("pubDate")) else "unknown"})
    return out

def is_article(row):
    return not re.search(r"sportsbook|casino|bet-label|leon.?bet|amazonslots|grams-bets|gambling|glücksspiel|στοίχημα", row.get("title", "")+" "+row.get("desc", ""), re.I)

def update_news(d, fetch, now, iso):
    existing = {x.get("url", "").rstrip("/"): x for x in d.get("news", []) if is_article(x) and x.get("source") != "Energy Voice"}
    checked = iso()
    statuses = []
    fresh = []
    def collect(spec):
        source, home, feed = spec
        try:
            try:
                raw = fetch(feed or home, timeout=15)
            except Exception:
                req = urllib.request.Request(feed or home, headers={"User-Agent": "Mozilla/5.0 (GasData Argentina)"})
                with urllib.request.urlopen(req, timeout=15) as response: raw = response.read()
            if feed:
                rows = feed_items(raw, source)
            else:
                soup = BeautifulSoup(raw, "html.parser")
                rows, seen = [], set()
                for a in soup.find_all("a", href=True):
                    title = text(str(a))
                    url = web_url(a["href"], home)
                    if not 28 <= len(title) <= 220 or not url or url in seen: continue
                    if urllib.parse.urlparse(url).netloc != urllib.parse.urlparse(home).netloc: continue
                    if any(s in url for s in ("/tag/", "/category/", "/author/", "/autor/", "#")): continue
                    seen.add(url)
                    rows.append({"source": source, "title": title, "url": url, "dateType": "unknown"})
                    if len(rows) >= 16: break
            edition = "international" if source in INTERNATIONAL else "national"
            if edition == "international": rows = rows[:12]
            for row in rows:
                row.update(edition=edition, language="en" if edition == "international" else "es")
            return rows, {"name": source, "url": home, "checkedAt": checked, "status": "ok", "edition": edition, "language": "en" if edition == "international" else "es"}
        except Exception as e:
            return [], {"name": source, "url": home, "checkedAt": checked, "status": "error", "error": str(e)[:180], "edition": "international" if source in INTERNATIONAL else "national"}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for rows, status in pool.map(collect, SOURCES):
            fresh.extend(row for row in rows if is_article(row)); statuses.append(status)
    unique = {}
    for row in fresh: unique.setdefault(row["url"].rstrip("/"), row)
    def enrich(row):
        old = existing.get(row["url"].rstrip("/"), {})
        for key in ("titleEs", "descEs", "translatedAt", "translationHash", "translationEngine"):
            if old.get(key): row[key] = old[key]
        # Cached article metadata is reused; feed metadata is still checked hourly.
        if row.get("edition") == "international" and all(row.get(key) for key in ("publishedAt", "desc", "imageUrl")):
            row["metadataSource"] = "RSS"
        elif old.get("articleMetadataCheckedAt"):
            for key in ("imageUrl", "desc", "articleMetadataCheckedAt"):
                if not row.get(key) and old.get(key): row[key] = old[key]
            if old.get("dateType") == "published" and not row.get("publishedAt"):
                row.update(publishedAt=old.get("publishedAt"), dateType="published")
        else:
            try:
                try:
                    raw = fetch(row["url"], timeout=12)
                except Exception:
                    req = urllib.request.Request(row["url"], headers={"User-Agent": "Mozilla/5.0 (GasData Argentina)"})
                    with urllib.request.urlopen(req, timeout=12) as response: raw = response.read()
                meta = metadata(raw, row["url"])
                if meta.get("publishedAt"): row.update(publishedAt=meta["publishedAt"], dateType="published")
                for key in ("imageUrl", "desc"):
                    if meta.get(key): row[key] = meta[key]
                row["articleMetadataCheckedAt"] = checked
            except Exception:
                pass
        row.update(sourceType="PRESS", feedValidatedAt=checked, tags=["Energía"])
        if not row.get("publishedAt"): row["publishedAt"] = old.get("publishedAt") or checked
        return row
    with ThreadPoolExecutor(max_workers=6) as pool:
        prepared = list(pool.map(enrich, unique.values()))
    merged = dict(existing)
    for row in prepared: merged[row["url"].rstrip("/")] = row
    d["news"] = sorted(merged.values(), key=lambda x: x.get("publishedAt", ""), reverse=True)[:600]
    d["sources"] = [x for x in d.get("sources", []) if x.get("name") != "Energy Voice"]
    translate_news(d, iso)
    d["newsSources"] = statuses
    for status in statuses:
        if status.get("edition") != "international": continue
        item = next((x for x in d.setdefault("sources", []) if x.get("name") == status["name"]), None)
        values = {"name": status["name"], "type": "Prensa internacional", "url": status["url"],
                  "content": "Noticias energéticas internacionales · inglés", "cadence": "Cada hora",
                  "checkedAt": checked, "status": "ACTIVA" if status["status"] == "ok" else "REVISAR"}
        if status["status"] == "ok": values["validatedAt"] = checked
        if item: item.update(values)
        else: d["sources"].append(values)
    new_count = sum(row["url"].rstrip("/") not in existing for row in prepared)
    u = next((x for x in d.get("updates", []) if x.get("name") == "Noticias"), None)
    if u:
        failures = [x["name"] for x in statuses if x["status"] == "error"]
        u.update(last=checked, next=iso(now()+timedelta(hours=1)),
                 status="partial" if failures else ("updated" if new_count else "unchanged"),
                 note=f"{new_count} URLs nuevas. Fecha original, resumen e imagen de la fuente; metadatos reutilizados por URL. Traducción automática al español guardada para las internacionales." + (" Fuentes con error: " + ", ".join(failures) if failures else ""))

        if d.get("newsTranslation", {}).get("status") == "pending":
            u["status"] = "partial"
            u["note"] += " Traducción pendiente: " + d["newsTranslation"].get("error", "reintentando en la próxima consulta")
