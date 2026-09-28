# Pipeline v1.2
from __future__ import annotations
import json, re, html, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from email.utils import parsedate_to_datetime

BASE=Path(__file__).resolve().parents[1]
DATA=BASE/"data"/"data.json"
ART=timezone(timedelta(hours=-3))
UA={"User-Agent":"GasDataArgentina/1.2 (+https://github.com/arielurrutipi-crypto/gasdata-argentina)"}
KEYWORDS=(
 "gas","vaca muerta","gnl","lng","tgs","tgn","bagsa","camuzzi","metrogas","naturgy",
 "enrege","enargas","tarifa","gasoducto","subdistrib","exportacion","exportación",
 "importacion","importación","shale","tight","gas natural","gas licuado","gasoducto perito moreno"
)

def now(): return datetime.now(ART)
def iso(d=None): return (d or now()).isoformat(timespec="minutes")
def fetch(url,timeout=30):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=timeout) as r: return r.read()
def clean(s):
    s=re.sub(r"<[^>]+>"," ",s or "")
    return re.sub(r"\s+"," ",html.unescape(s)).strip()
def pdate(s):
    try:
        d=parsedate_to_datetime(s)
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(ART)
    except Exception:
        return now()
def upsert_kpi(d,item):
    for i,x in enumerate(d.setdefault("kpis",[])):
        if x.get("id")==item["id"]:
            d["kpis"][i]={**x,**item}; return
    d["kpis"].append(item)

def rss(source,url):
    root=ET.fromstring(fetch(url)); out=[]
    for it in root.findall(".//item")[:60]:
        title=(it.findtext("title") or "").strip()
        desc=clean(it.findtext("description") or "")
        hay=(title+" "+desc).lower()
        if not any(k in hay for k in KEYWORDS): continue
        out.append({
          "source":source,"sourceType":"PRESS",
          "publishedAt":iso(pdate(it.findtext("pubDate") or "")),
          "feedValidatedAt":iso(),"title":title,"desc":desc[:520],
          "tags":["Gas"],"url":(it.findtext("link") or "").strip()
        })
    return out

def update_news(d):
    feeds=[
      ("EconoJournal","https://econojournal.com.ar/feed/"),
      ("Mejor Energía","https://www.mejorenergia.com.ar/feed/"),
      ("RunRun Energético","https://runrunenergetico.com/feed/"),
      ("RunRun Energético · Gas","https://runrunenergetico.com/category/oil-gas/gas/feed/"),
      ("TGS","https://www.tgs.com.ar/feed/"),
      ("TGN","https://www.tgn.com.ar/feed/")
    ]
    fresh=[]; ok_sources=[]
    for source,url in feeds:
        try:
            items=rss(source,url)
            fresh+=items
            ok_sources.append(source)
        except Exception as e:
            print("RSS",source,e)
    if fresh:
        seen=set(); merged=[]
        for x in sorted(fresh+d.get("news",[]),key=lambda z:z.get("publishedAt",""),reverse=True):
            k=(x.get("url") or x.get("title") or "").rstrip("/")
            if not k or k in seen: continue
            seen.add(k); x["feedValidatedAt"]=iso(); merged.append(x)
        d["news"]=merged[:60]
    u=next((x for x in d["updates"] if x["name"]=="Noticias"),None)
    if u:
        u.update(last=iso(),next=iso(now()+timedelta(hours=1)),
                 status="updated" if fresh else "unchanged",
                 note="Fuentes consultadas: "+(", ".join(sorted(set(ok_sources))) if ok_sources else "ninguna disponible"))

def official_series(series_id):
    qs=urllib.parse.urlencode({"ids":series_id,"last":1,"metadata":"full"})
    return json.loads(fetch("https://apis.datos.gob.ar/series/api/series?"+qs).decode("utf-8"))

def production(d):
    u=next((x for x in d["updates"] if x["name"]=="Producción"),None)
    k=next((x for x in d.get("kpis",[]) if x.get("id")=="national_prod"),None)
    try: last=datetime.fromisoformat(u["last"]) if u and u.get("last") else None
    except Exception: last=None
    if k and k.get("status")!="pending" and last and now()<last+timedelta(days=15):
        return
    months=("enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre")
    try:
        hub="https://www.argentina.gob.ar/economia/energia/noticias"
        raw=fetch(hub).decode("utf-8","ignore")
        links=[]
        for href,label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',raw,re.I|re.S):
            title=clean(label)
            h=(title+" "+href).lower()
            if "produccion" in h or "producción" in h or "gas" in h:
                links.append((urllib.parse.urljoin(hub,href),title))
        found=None
        for url,title in links[:30]:
            try:
                article=clean(fetch(url).decode("utf-8","ignore"))
            except Exception:
                continue
            m=re.search(r"gas natural.{0,180}?producci[oó]n nacional (?:fue|alcanz[oó])(?: de)?\s*([\d.,]+)\s+millones de metros c[uú]bicos diarios",article,re.I)
            if not m:
                continue
            val=float(m.group(1).replace(".","").replace(",","."))
            year_m=re.search(r"\b(20\d{2})\b",article)
            year=year_m.group(1) if year_m else str(now().year)
            month=next((x for x in months if x in title.lower()),None)
            if not month:
                month=next((x for x in months if re.search(r"\ben "+x+r"\b",article,re.I)),None)
            ref=(month.capitalize()+" "+year) if month else year
            found=(val,ref,url,title)
            break
        if not found:
            raise RuntimeError("no se halló una publicación oficial reciente con producción nacional de gas")
        val,ref,url,title=found
        disp=f"{val:.1f}".replace(".",",")
        old=(k or {}).get("value")
        item={
          "id":"national_prod","label":"Producción nacional de gas",
          "value":disp,"unit":"MMm³/d","reference":ref,
          "validatedAt":iso(),"nextValidation":iso(now()+timedelta(days=15)),
          "status":"updated" if old!=disp else "unchanged",
          "statusText":"ACTUALIZADO" if old!=disp else "SIN CAMBIOS",
          "sourceType":"OFFICIAL","source":"Secretaría de Energía",
          "sourceUrl":url,"note":title
        }
        upsert_kpi(d,item)
        if u: u.update(last=iso(),next=iso(now()+timedelta(days=15)),status=item["status"],
                       note="Producción validada contra la publicación oficial más reciente de Secretaría de Energía.")
    except Exception as e:
        print("PROD",e)
        if u: u.update(last=iso(),next=iso(now()+timedelta(days=15)),status="pending",
                       note="Consulta oficial fallida; se conserva el último valor y su período de referencia.")

def demand_priority(d):
    url="https://www.enargas.gob.ar/secciones/transporte-y-distribucion/dod-estimacion-demanda-prioritaria.php"
    try:
        txt=clean(fetch(url).decode("utf-8","ignore"))
        # La fila TOTALES contiene cinco valores diarios; tomamos el último.
        m=re.search(r"TOTALES:\s*((?:\d{1,3}\.\d{3,4}\s*){2,8})",txt,re.I)
        if not m:
            raise RuntimeError("fila TOTALES no identificada")
        vals=re.findall(r"\d{1,3}\.\d{3,4}",m.group(1))
        if not vals: raise RuntimeError("sin valores")
        dates=re.findall(r"\b\d{2}/\d{2}/\d{2}\b",txt)
        ref=dates[-1] if dates else now().strftime("%d/%m/%y")
        val=float(vals[-1]); disp=f"{val:.4f}".replace(".",",")
        old=next((x.get("value") for x in d.get("kpis",[]) if x.get("id")=="demand_priority"),None)
        upsert_kpi(d,{
          "id":"demand_priority","label":"Demanda prioritaria",
          "value":disp,"unit":"MMm³/d","reference":ref,
          "validatedAt":iso(),"nextValidation":iso(now()+timedelta(days=1)),
          "status":"updated" if old!=disp else "unchanged",
          "statusText":"ACTUALIZADO" if old!=disp else "SIN CAMBIOS",
          "sourceType":"OFFICIAL","source":"ENReGE · Estimación de la Demanda Prioritaria"
        })
        # quitamos el placeholder anterior
        d["kpis"]=[x for x in d["kpis"] if x.get("id")!="system_daily"]
    except Exception as e:
        print("DEMAND",e)

def validate_pages(d):
    checks=[
      ("Normativa","https://www.enargas.gob.ar/secciones/normativa/resoluciones.php",3),
      ("Tarifas ENReGE/BAGSA","https://www.enargas.gob.ar/secciones/precios-y-tarifas/resoluciones-tarifas-vigentes.php",24),
      ("Datos operativos","https://www.enargas.gob.ar/secciones/transporte-y-distribucion/datos-operativos.php",24)
    ]
    for name,url,h in checks:
        try:
            fetch(url); ok=True
        except Exception as e:
            print(name,e); ok=False
        u=next((x for x in d["updates"] if x["name"]==name),None)
        if u and ok: u.update(last=iso(),next=iso(now()+timedelta(hours=h)),status="unchanged")
    try:
        fetch("https://www.bagsa.com.ar/index.php/tarifas/")
        t=iso()
        for x in d.get("tariffs",[]): x["validatedAt"]=t
    except Exception as e:
        print("BAGSA",e)

def refresh_source_status(d):
    for src in d.get("sources",[]):
        try:
            fetch(src["url"],timeout=20)
            src["status"]="ACTIVA"
            src["validatedAt"]=iso()
        except Exception:
            src["status"]="REVISAR"

def main():
    d=json.loads(DATA.read_text(encoding="utf-8"))
    update_news(d)
    validate_pages(d)
    production(d)
    demand_priority(d)
    refresh_source_status(d)
    d["meta"]["updatedAt"]=iso()
    d["meta"]["version"]="1.2.0"
    DATA.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
