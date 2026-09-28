# Pipeline v2.0
from __future__ import annotations
import json, re, html, io, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from email.utils import parsedate_to_datetime

BASE=Path(__file__).resolve().parents[1]
DATA=BASE/"data"/"data.json"
ART=timezone(timedelta(hours=-3))
UA={"User-Agent":"GasDataArgentina/2.0 (+https://github.com/arielurrutipi-crypto/gasdata-argentina)"}
KEYWORDS=(
 "gas","vaca muerta","gnl","lng","tgs","tgn","bagsa","camuzzi","metrogas","naturgy",
 "enrege","enargas","tarifa","gasoducto","subdistrib","exportacion","exportación",
 "importacion","importación","shale","tight","glp","propano","butano","gas natural","gas licuado","gasoducto perito moreno"
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


def html_news(source,url,limit=12):
    """Fallback for sites without a stable RSS. Date shown is first detection time."""
    raw=fetch(url).decode("utf-8","ignore")
    out=[]; seen=set()
    for href,label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',raw,re.I|re.S):
        title=clean(label)
        if len(title)<28 or len(title)>180: continue
        hay=title.lower()
        if not any(k in hay for k in KEYWORDS): continue
        full=urllib.parse.urljoin(url,href)
        if not full.startswith(("http://","https://")) or full in seen: continue
        if any(x in full.lower() for x in ("/tag/","/category/","/autor/","/author/","#")): continue
        seen.add(full)
        out.append({
          "source":source,"sourceType":"PRESS","publishedAt":iso(),"dateType":"detected",
          "feedValidatedAt":iso(),"title":title,
          "desc":"Artículo detectado en la portada de la fuente; consultar el enlace para la fecha de publicación original.",
          "tags":["Gas"],"url":full
        })
        if len(out)>=limit: break
    return out

def update_news(d):
    feeds=[
      ("EconoJournal","https://econojournal.com.ar/feed/"),
      ("Mejor Energía","https://www.mejorenergia.com.ar/feed/"),
      ("RunRun Energético","https://runrunenergetico.com/feed/"),
      ("RunRun Energético · Gas","https://runrunenergetico.com/category/oil-gas/gas/feed/"),
      ("Revista Petroquímica","https://revistapetroquimica.com/feed/"),
      ("TGS","https://www.tgs.com.ar/feed/"),
      ("TGN","https://www.tgn.com.ar/feed/")
    ]
    html_sources=[
      ("Más Energía · LM Neuquén","https://mase.lmneuquen.com/"),
      ("América GLP","https://www.americaglp.com/")
    ]
    fresh=[]; ok_sources=[]
    for source,url in feeds:
        try:
            fresh+=rss(source,url); ok_sources.append(source)
        except Exception as e:
            print("RSS",source,e)
    for source,url in html_sources:
        try:
            fresh+=html_news(source,url); ok_sources.append(source)
        except Exception as e:
            print("HTML NEWS",source,e)

    existing={(x.get("url") or "").rstrip("/"):x for x in d.get("news",[]) if x.get("url")}
    prepared=[]
    for x in fresh:
        key=(x.get("url") or "").rstrip("/")
        if x.get("dateType")=="detected" and key in existing:
            # Don't make an old homepage item look new every hour.
            x["publishedAt"]=existing[key].get("publishedAt",x["publishedAt"])
        prepared.append(x)

    seen=set(); merged=[]
    for x in sorted(prepared+d.get("news",[]),key=lambda z:z.get("publishedAt",""),reverse=True):
        k=(x.get("url") or x.get("title") or "").rstrip("/")
        if not k or k in seen: continue
        seen.add(k); x["feedValidatedAt"]=iso(); merged.append(x)
    if merged:
        d["news"]=merged[:80]
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
    def period_key(text):
        low=(text or "").lower()
        y=re.search(r"\b(20\d{2})\b",low)
        m=next((i+1 for i,x in enumerate(months) if x in low),0)
        return (int(y.group(1)) if y else 0,m)
    try:
        hub="https://www.argentina.gob.ar/economia/energia/noticias"
        raw=fetch(hub).decode("utf-8","ignore")
        links=[]
        for href,label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',raw,re.I|re.S):
            title=clean(label); h=(title+" "+href).lower()
            if "produccion" in h or "producción" in h or "gas" in h:
                links.append((urllib.parse.urljoin(hub,href),title))
        found=None
        for url,title in links[:40]:
            try: article=clean(fetch(url).decode("utf-8","ignore"))
            except Exception: continue
            m=re.search(r"gas natural.{0,180}?producci[oó]n nacional (?:fue|alcanz[oó])(?: de)?\s*([\d.,]+)\s+millones de metros c[uú]bicos diarios",article,re.I)
            if not m: continue
            val=float(m.group(1).replace(".","").replace(",","."))
            year_m=re.search(r"\b(20\d{2})\b",article); year=year_m.group(1) if year_m else str(now().year)
            month=next((x for x in months if x in title.lower()),None) or next((x for x in months if re.search(r"\ben "+x+r"\b",article,re.I)),None)
            ref=(month.capitalize()+" "+year) if month else year
            found=(val,ref,url,title); break
        if not found: raise RuntimeError("no se halló una publicación oficial reciente con producción nacional de gas")
        val,ref,url,title=found
        current_key=period_key((k or {}).get("reference",""))
        candidate_key=period_key(ref)
        if current_key and candidate_key and candidate_key<current_key:
            # Existing data is newer (e.g. a later monthly filing reported by a specialized source).
            if k:
                k["validatedAt"]=iso()
                k["nextValidation"]=iso(now()+timedelta(days=15))
                k["status"]="unchanged"; k["statusText"]="SIN CAMBIOS"
            if u: u.update(last=iso(),next=iso(now()+timedelta(days=15)),status="unchanged",
                           note="Fuente oficial consultada; no reemplaza el dato porque el tablero ya posee un período mensual más reciente.")
            return
        disp=f"{val:.2f}".rstrip("0").rstrip(".").replace(".",",")
        old=(k or {}).get("value")
        item={
          "id":"national_prod","label":"Producción nacional de gas","value":disp,"unit":"MMm³/d",
          "reference":"Promedio diario · "+ref,"validatedAt":iso(),"nextValidation":iso(now()+timedelta(days=15)),
          "status":"updated" if old!=disp else "unchanged","statusText":"ACTUALIZADO" if old!=disp else "SIN CAMBIOS",
          "sourceType":"OFFICIAL","source":"Secretaría de Energía","sourceUrl":url,
          "note":"Promedio de producción durante el mes; no corresponde a un día puntual."
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
        raw=fetch(url).decode("utf-8","ignore")
        txt=clean(raw)

        # ENReGE publishes a five-day window. The first column is marked (1)
        # actual consumption and the following columns (2) estimated consumption.
        dates=[]
        for x in re.findall(r"\b\d{2}/\d{2}/\d{2}\b",txt):
            if x not in dates:
                dates.append(x)
            if len(dates)>=5: break

        m=re.search(r"TOTALES:\s*((?:\d{1,3}\.\d{3,4}\s*){2,8})",txt,re.I)
        if not m: raise RuntimeError("fila TOTALES no identificada")
        vals=re.findall(r"\d{1,3}\.\d{3,4}",m.group(1))[:5]
        if len(dates)<5 or len(vals)<5:
            raise RuntimeError(f"ventana incompleta: {len(dates)} fechas / {len(vals)} valores")

        def display_date(x,with_day=False):
            dt=datetime.strptime(x,"%d/%m/%y")
            days=("lun","mar","mié","jue","vie","sáb","dom")
            return (days[dt.weekday()].capitalize()+" " if with_day else "")+dt.strftime("%d/%m/%Y")

        series=[]
        for i,(dt,v) in enumerate(zip(dates,vals)):
            series.append({
              "date":datetime.strptime(dt,"%d/%m/%y").strftime("%d/%m"),
              "fullDate":display_date(dt,True),
              "value":v.replace(".",","),
              "kind":"REAL" if i==0 else "PROY."
            })

        ref=dates[-1]; val=float(vals[-1]); disp=f"{val:.4f}".replace(".",",")
        old=next((x.get("value") for x in d.get("kpis",[]) if x.get("id")=="demand_priority"),None)
        upsert_kpi(d,{
          "id":"demand_priority","label":"Proyección demanda prioritaria",
          "value":disp,"unit":"MMm³/d","reference":display_date(ref,True)+" · PROYECCIÓN",
          "validatedAt":iso(),"nextValidation":iso(now()+timedelta(days=1)),
          "status":"updated" if old!=disp else "unchanged",
          "statusText":"ACTUALIZADO" if old!=disp else "SIN CAMBIOS",
          "sourceType":"OFFICIAL","source":"ENReGE · Estimación de la Demanda Prioritaria","sourceUrl":url,
          "series":series,
          "note":"Ventana de 5 días de ENReGE: primera columna = consumo real (1); cuatro columnas siguientes = consumo estimado (2)."
        })
        d["kpis"]=[x for x in d["kpis"] if x.get("id")!="system_daily"]
    except Exception as e:
        print("DEMAND",e)

def system_market(d):
    """Refresh report availability without replacing validated values with unparsed chart data."""
    refs={
      "linepack":("https://www.enargas.gob.ar/secciones/transporte-y-distribucion/dod-graficos-de-programacion-items.php?cat=5","date"),
      "injection":("https://www.enargas.gob.ar/secciones/transporte-y-distribucion/dod-graficos-de-programacion-items.php?cat=6","date")
    }
    items={x.get("id"):x for x in d.get("systemKpis",[])}
    for kid,(url,_) in refs.items():
        try:
            txt=clean(fetch(url).decode("utf-8","ignore"))
            m=re.search(r"\b(\d{2}/\d{2}/\d{4})\b",txt)
            if not m: continue
            latest=m.group(1)
            k=items.get(kid)
            if not k: continue
            oldref=k.get("reference","")
            if kid=="injection":
                try:
                    from pypdf import PdfReader
                    dt=datetime.strptime(latest,"%d/%m/%Y")
                    pdf_url="https://www.enargas.gob.ar/secciones/transporte-y-distribucion/datos-operativos-despacho/graficos-programacion/6/ING_"+dt.strftime("%Y%m%d")+".pdf"
                    pdf=fetch(pdf_url,timeout=40)
                    reader=PdfReader(io.BytesIO(pdf))
                    ptxt=" ".join((p.extract_text() or "") for p in reader.pages)
                    ptxt=re.sub(r"\s+"," ",ptxt)
                    chart_dates=re.findall(r"\b\d{1,2}/\d{1,2}/\d{2}\b",ptxt)
                    if not chart_dates:
                        raise RuntimeError("sin fechas en gráfico")
                    last_date=chart_dates[-1]
                    pos=ptxt.find(last_date)
                    totals=re.findall(r"\b\d{2,3},\d\b",ptxt[pos+len(last_date):])[:len(chart_dates)]
                    short_latest=dt.strftime("%-d/%-m/%y")
                    if short_latest not in chart_dates or len(totals)<len(chart_dates):
                        raise RuntimeError("no se pudo alinear serie nacional")
                    idx=chart_dates.index(short_latest)
                    val=totals[idx]
                    k["value"]=val
                    k["unit"]="MMm³/d"
                    k["reference"]=latest+" · REAL"
                    k["validatedAt"]=iso()
                    k["sourceUrl"]=pdf_url
                    k["statusText"]="OFICIAL"
                    k["note"]="Inyección nacional total del gráfico oficial ENReGE. El mismo reporte abre el total por San Martín, Neuba I, Neuba II, GPFM, Centro Oeste y Norte."
                except Exception as pe:
                    print("INJECTION PDF",pe)
                    k["reference"]=latest+" · último reporte"
                    k["statusText"]="REPORTE"
                    k["note"]="ENReGE publicó el reporte; aún no se pudo extraer automáticamente el total nacional."
            elif latest in oldref:
                k["validatedAt"]=iso()
            else:
                k["statusText"]="NUEVO REPORTE · REVISAR"
                k["note"]="ENReGE publicó un gráfico más reciente ("+latest+"). Se conserva el último total del sistema validado hasta recalcular TGN + TGS; la fecha de validación del valor no cambia."
        except Exception as e:
            print("SYSTEM",kid,e)


def monthly_flows_status(d):
    """Detect new monthly ENReGE reports without replacing validated history blindly."""
    url="https://www.enargas.gob.ar/secciones/transporte-y-distribucion/dod-graficos-de-programacion-items.php?cat=9"
    months={
      "enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
      "julio":"07","agosto":"08","septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"
    }
    try:
        txt=clean(fetch(url).decode("utf-8","ignore")).lower()
        found=[]
        for name,num in months.items():
            if re.search(r"\b"+name+r"\s+2026\b",txt):
                found.append("2026-"+num)
        if not found:
            return
        latest=max(found)
        meta=d.setdefault("systemMonthlyMeta",{})
        current=meta.get("latest")
        meta["sourceUrl"]=url
        meta["checkedAt"]=iso()
        if not current or latest>current:
            meta["pendingMonth"]=latest
            meta["status"]="new_report"
            meta["note"]="ENReGE publicó "+latest+". Se conserva el último mes validado hasta extraer y verificar sus valores."
        else:
            meta.pop("pendingMonth",None)
            meta["status"]="current"
    except Exception as e:
        print("MONTHLY FLOWS",e)

def transport_capacity(d):
    existing={x.get("id"):x for x in d.get("transportCapacity",[]) if x.get("id")}
    existing_open=[x for x in existing.values() if x.get("kind")=="CONCURSO ABIERTO"]
    out=[]
    # Official open contests
    en_url="https://www.enargas.gob.ar/secciones/transporte-y-distribucion/concursos-reventas.php"
    try:
        txt=clean(fetch(en_url).decode("utf-8","ignore"))
        for company,num in re.findall(r"Concurso abierto\s+(TGN|TGS).*?(\d+/\d{4})",txt,re.I):
            out.append({
              "id":("open_"+company+"_"+num).lower().replace("/","_"),
              "kind":"CONCURSO ABIERTO","company":company.upper(),
              "title":f"Concurso Abierto {company.upper()} N.º {num}",
              "volume":"Capacidad firme","period":"Vigente","published":str(now().year),
              "status":"VIGENTE","source":"ENReGE · Concursos y reventas","url":en_url,
              "note":"Concurso vigente detectado en la página oficial."
            })
    except Exception as e:
        print("CAPACITY ENREGE",e)

    if not any(x.get("kind")=="CONCURSO ABIERTO" for x in out):
        # ENReGE renders parts of the current contest list dynamically; retain the
        # last officially verified contest instead of silently deleting it.
        out.extend(existing_open)

    # MEGSA firm transport resale board
    meg_url="https://negociacion.megsa.ar/Usuario/VisualizacionReventa.aspx?tipo=2"
    try:
        txt=clean(fetch(meg_url).decode("utf-8","ignore"))
        m=re.search(r"(T\d+)\s+TRANSPORTADORA DE GAS DEL (SUR|NORTE) S\.A\.\s+([\d.]+)\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})(?:\s+(DESIERTA))?",txt,re.I)
        if m:
            code,side,vol,dfrom,dto,pub,act,des=m.groups()
            comp="TGS" if side.upper()=="SUR" else "TGN"
            out.append({
              "id":"megsa_"+code.lower(),"kind":"REVENTA TF","company":comp,
              "title":f"Oferta {code}","volume":vol+" m³/d",
              "period":dfrom+"–"+dto,"published":pub,
              "status":"DESIERTA" if des else "CERRADO",
              "source":"MEGSA · Reventa de transporte firme","url":meg_url,
              "publishedAt":datetime.strptime(pub,"%d/%m/%Y").replace(tzinfo=ART).isoformat(),
              "deadline":act,
              "deadlineAt":datetime.strptime(act,"%d/%m/%Y").replace(hour=23,minute=59,second=59,tzinfo=ART).isoformat(),
              "deadlineLabel":"Acto de lectura / cierre",
              "note":"Última oferta visible en la pantalla pública de reventas."
            })
    except Exception as e:
        print("CAPACITY MEGSA",e)

    if out:
        merged=[]
        for item in out:
            old=existing.get(item.get("id"),{})
            z={**old,**item}
            if z.get("published") and not z.get("publishedAt"):
                try:
                    dt=datetime.strptime(z["published"],"%d/%m/%Y")
                    z["publishedAt"]=dt.replace(tzinfo=ART).isoformat()
                except Exception:
                    pass
            if z.get("kind")=="REVENTA TF" and z.get("status","").startswith("ACTO ") and not z.get("deadlineAt"):
                try:
                    act=item.get("period_act") or None
                except Exception:
                    act=None
            merged.append(z)
        d["transportCapacity"]=merged
    meta=d.setdefault("transportCapacityMeta",{})
    meta.update(validatedAt=iso(),cadence="Cada 3 horas",
                note="GasData separa concursos abiertos de capacidad firme de reventas de capacidad existente. Ambos pueden ser relevantes para detectar disponibilidad de transporte.")
    u=next((x for x in d.get("updates",[]) if x.get("name")=="Capacidad de transporte"),None)
    if u:
        u.update(last=iso(),next=iso(now()+timedelta(hours=3)),status="updated" if out else "unchanged",
                 note="ENReGE concursos abiertos + MEGSA reventas de transporte firme.")

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


def bopba_monitor(d):
    """Check only the Provincial Official Gazette results relevant to GasData."""
    base="https://boletinoficial.gba.gob.ar/buscar"
    since=(now()-timedelta(days=45)).strftime("%d/%m/%Y")
    results={}
    urls={}
    for term in ("gas natural","BAGSA"):
        params={
          "commit":"Buscar","search[date_gteq]":since,"search[date_lteq]":"",
          "search[section]":"OFICIAL","search[sort]":"by_match_desc",
          "search[words]":term,"utf8":"✓"
        }
        url=base+"?"+urllib.parse.urlencode(params)
        urls[term]=url
        try:
            txt=clean(fetch(url).decode("utf-8","ignore"))
            dates=re.findall(r"fecha de publicación:\s*(\d{2}/\d{2}/\d{4})",txt,re.I)
            results[term]={"ok":True,"matches":len(dates),"latest":dates[0] if dates else None}
        except Exception as e:
            print("BOPBA",term,e)
            results[term]={"ok":False,"matches":0,"latest":None}

    src=next((x for x in d.get("sources",[]) if x.get("name")=="Boletín Oficial PBA · Gas/BAGSA"),None)
    if src:
        src["validatedAt"]=iso()
        src["status"]="ACTIVA" if any(v["ok"] for v in results.values()) else "REVISAR"
        src["url"]=urls["gas natural"]
        src["secondaryUrl"]=urls["BAGSA"]
        src["content"]="Filtro exclusivo: “gas natural” OR “BAGSA”"
        src["lastResult"]=" · ".join(
          f"{k}: {v['matches']} coincid."+(f" · última {v['latest']}" if v["latest"] else "")
          for k,v in results.items()
        )

    u=next((x for x in d.get("updates",[]) if x.get("name")=="Boletín Oficial PBA"),None)
    if u:
        u.update(last=iso(),next=iso(now()+timedelta(hours=3)),
                 status="updated" if any(v["matches"] for v in results.values()) else "unchanged",
                 note="Sección Oficial PBA; sólo búsquedas “gas natural” y “BAGSA”.")

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
    system_market(d)
    monthly_flows_status(d)
    transport_capacity(d)
    bopba_monitor(d)
    refresh_source_status(d)
    d["meta"]["updatedAt"]=iso()
    d["meta"]["version"]="2.0.0"
    DATA.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
