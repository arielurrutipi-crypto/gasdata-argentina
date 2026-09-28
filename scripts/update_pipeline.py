from __future__ import annotations
import json, re, html, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from email.utils import parsedate_to_datetime

BASE=Path(__file__).resolve().parents[1]
DATA=BASE/"data"/"data.json"
ART=timezone(timedelta(hours=-3))
UA={"User-Agent":"GasDataArgentina/1.0"}
KEYWORDS=("gas","vaca muerta","gnl","lng","tgs","tgn","bagsa","camuzzi","metrogas","naturgy","enrege","enargas","tarifa","gasoducto","subdistrib")

def now(): return datetime.now(ART)
def iso(d=None): return (d or now()).isoformat(timespec="minutes")
def fetch(url,timeout=25):
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
    except: return now()

def rss(source,url):
    root=ET.fromstring(fetch(url)); out=[]
    for it in root.findall(".//item")[:30]:
        title=(it.findtext("title") or "").strip()
        desc=clean(it.findtext("description") or "")
        hay=(title+" "+desc).lower()
        if not any(k in hay for k in KEYWORDS): continue
        out.append({"source":source,"sourceType":"PRESS","publishedAt":iso(pdate(it.findtext("pubDate") or "")),
          "feedValidatedAt":iso(),"title":title,"desc":desc[:500],"tags":["Gas"],
          "url":(it.findtext("link") or "").strip()})
    return out

def update_news(d):
    feeds=[("EconoJournal","https://econojournal.com.ar/feed/"),("Mejor Energía","https://www.mejorenergia.com.ar/feed/")]
    fresh=[]; ok=0
    for source,url in feeds:
        try: fresh+=rss(source,url); ok+=1
        except Exception as e: print("RSS",source,e)
    if fresh:
        seen=set(); merged=[]
        for x in sorted(fresh+d.get("news",[]),key=lambda z:z.get("publishedAt",""),reverse=True):
            k=x.get("url") or x.get("title")
            if k in seen: continue
            seen.add(k); x["feedValidatedAt"]=iso(); merged.append(x)
        d["news"]=merged[:30]
    u=next((x for x in d["updates"] if x["name"]=="Noticias"),None)
    if u and ok: u.update(last=iso(),next=iso(now()+timedelta(hours=1)),status="updated" if fresh else "unchanged")

def validate_pages(d):
    checks=[
      ("Normativa","https://www.enargas.gob.ar/secciones/normativa/resoluciones.php",3),
      ("Tarifas ENReGE/BAGSA","https://www.enargas.gob.ar/secciones/precios-y-tarifas/resoluciones-tarifas-vigentes.php",24),
      ("Datos operativos","https://www.enargas.gob.ar/secciones/transporte-y-distribucion/datos-operativos.php",24)]
    for name,url,h in checks:
        try: fetch(url); ok=True
        except Exception as e: print(name,e); ok=False
        u=next((x for x in d["updates"] if x["name"]==name),None)
        if u and ok: u.update(last=iso(),next=iso(now()+timedelta(hours=h)),status="unchanged")
    try:
        fetch("https://www.bagsa.com.ar/index.php/tarifas/")
        t=iso()
        for x in d.get("tariffs",[]): x["validatedAt"]=t
    except Exception as e: print("BAGSA",e)

def candidates(obj):
    out=[]
    if isinstance(obj,dict):
        field=obj.get("field") if isinstance(obj.get("field"),dict) else obj
        sid=field.get("id") or field.get("serie_id") or obj.get("serie_id")
        if sid:
            ds=obj.get("dataset") if isinstance(obj.get("dataset"),dict) else {}
            text=" ".join(str(v) for v in (field.get("description",""),field.get("title",""),obj.get("title",""),obj.get("description",""),ds.get("title","")))
            out.append((str(sid),text))
        for v in obj.values(): out+=candidates(v)
    elif isinstance(obj,list):
        for v in obj: out+=candidates(v)
    return out

def production(d):
    u=next((x for x in d["updates"] if x["name"]=="Producción"),None)
    try: last=datetime.fromisoformat(u["last"]) if u and u.get("last") else None
    except: last=None
    if last and now()<last+timedelta(days=15): return
    try:
        qs=urllib.parse.urlencode({"q":"producción gas natural total país","catalog_id":"energia","limit":100})
        sr=json.loads(fetch("https://apis.datos.gob.ar/series/api/search/?"+qs).decode())
        best=None
        for sid,txt in candidates(sr):
            s=txt.lower(); score=sum(p for w,p in [("gas natural",8),("producción",6),("produccion",6),("total",4),("país",4),("pais",4),("mensual",2)] if w in s)
            if any(w in s for w in ("petróleo","petroleo","líquido","liquido")): score-=5
            if best is None or score>best[0]: best=(score,sid,txt)
        if not best or best[0]<10: raise RuntimeError("serie no identificada con suficiente confianza")
        sid,title=best[1],best[2]
        qs=urllib.parse.urlencode({"ids":sid,"last":1,"metadata":"full"})
        raw=json.loads(fetch("https://apis.datos.gob.ar/series/api/series?"+qs).decode())
        ref,val=raw["data"][0][0],raw["data"][0][1]
        k=next(x for x in d["kpis"] if x["id"]=="national_prod")
        old=(k.get("value"),k.get("reference"))
        disp=f"{float(val):,.2f}".replace(",","X").replace(".",",").replace("X",".")
        meta=json.dumps(raw.get("meta",[]),ensure_ascii=False).lower()
        unit="MMm³/d" if any(x in meta for x in ("m3/d","m³/d","mm3/d")) else ""
        k.update(value=disp,unit=unit,reference=ref[:7],validatedAt=iso(),nextValidation=iso(now()+timedelta(days=15)),
          sourceType="OFFICIAL",source="Secretaría de Energía · API Series de Tiempo",note=f"Serie oficial: {sid}. {title[:160]}")
        k["status"]="updated" if old!=(disp,ref[:7]) else "unchanged"
        k["statusText"]="ACTUALIZADO" if k["status"]=="updated" else "SIN CAMBIOS"
        if u: u.update(last=iso(),next=iso(now()+timedelta(days=15)),status=k["status"],note=f"Fuente oficial validada. Serie {sid}.")
    except Exception as e:
        print("PROD",e)
        if u: u.update(last=iso(),next=iso(now()+timedelta(days=15)),status="pending",note="La fuente fue consultada pero no pudo validarse automáticamente; se conserva el último dato.")

def main():
    d=json.loads(DATA.read_text(encoding="utf-8"))
    update_news(d); validate_pages(d); production(d)
    d["meta"]["updatedAt"]=iso(); d["meta"]["version"]="1.1.0"
    DATA.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__": main()
