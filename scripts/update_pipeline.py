# Pipeline v2.0
from __future__ import annotations
import json, re, html, io, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    raw=fetch(url); out=[]
    try:
        root=ET.fromstring(raw)
        items=root.findall(".//item")[:60]
        parsed=[]
        for it in items:
            parsed.append((
              (it.findtext("title") or "").strip(),
              clean(it.findtext("description") or ""),
              it.findtext("pubDate") or "",
              (it.findtext("link") or "").strip()
            ))
    except Exception:
        # Several energy-sector feeds contain invalid entities or small HTML
        # fragments. Fall back to a tolerant parser instead of dropping the source.
        soup=BeautifulSoup(raw.decode("utf-8","ignore"),"html.parser")
        parsed=[]
        for it in soup.find_all("item")[:60]:
            def tx(*names):
                node=next((it.find(n) for n in names if it.find(n)),None)
                return clean(node.get_text(" ",strip=True)) if node else ""
            link=it.find("link")
            href=(link.get("href") if link and link.get("href") else (link.get_text(strip=True) if link else ""))
            parsed.append((tx("title"),tx("description","summary","content:encoded"),tx("pubdate","pubDate","published"),href))
    for title,desc,pub,link in parsed:
        hay=(title+" "+desc).lower()
        if not title or not any(k in hay for k in KEYWORDS): continue
        out.append({
          "source":source,"sourceType":"PRESS",
          "publishedAt":iso(pdate(pub)),"feedValidatedAt":iso(),
          "title":title,"desc":desc[:520],"tags":["Gas"],"url":link
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
      ("RunRun Energético","https://runrunenergetico.com/feed/"),
      ("RunRun Energético · Gas","https://runrunenergetico.com/category/oil-gas/gas/feed/"),
      ("Revista Petroquímica","https://revistapetroquimica.com/feed/"),
      ("TGS","https://www.tgs.com.ar/feed/")
    ]
    html_sources=[
      ("Mejor Energía","https://www.mejorenergia.com.ar/"),
      ("TGN","https://www.tgn.com.ar/prensa-y-novedades/comunicaciones/"),
      ("Más Energía · LM Neuquén","https://mase.lmneuquen.com/"),
      ("América GLP","https://www.americaglp.com/"),
      ("ENReGE · Noticias","https://www.enargas.gob.ar/secciones/noticias/noticias.php"),
      ("Secretaría de Energía","https://www.argentina.gob.ar/economia/energia/noticias")
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
    new_keys={(x.get("url") or "").rstrip("/") for x in fresh if x.get("url") and (x.get("url") or "").rstrip("/") not in existing}
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
        seen.add(k); merged.append(x)
    if merged:
        d["news"]=merged[:80]
    u=next((x for x in d["updates"] if x["name"]=="Noticias"),None)
    if u:
        u.update(last=iso(),next=iso(now()+timedelta(hours=1)),
                 status="pending" if not ok_sources else ("partial" if len(ok_sources)<len(feeds)+len(html_sources) else ("updated" if new_keys else "unchanged")),
                 note=(f"{len(new_keys)} noticias nuevas · " if new_keys else "Sin noticias nuevas · ")+"Fuentes consultadas: "+(", ".join(sorted(set(ok_sources))) if ok_sources else "ninguna disponible"))

def official_series(series_id):
    qs=urllib.parse.urlencode({"ids":series_id,"last":1,"metadata":"full"})
    return json.loads(fetch("https://apis.datos.gob.ar/series/api/series?"+qs).decode("utf-8"))

def production(d):
    u=next((x for x in d["updates"] if x["name"] in ("Producción","Producción nacional")),None)
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


def _format_ar(v,decimals=2):
    return f"{float(v):.{decimals}f}".replace(".",",")

def _series_rows(series_ids,last=24):
    qs=urllib.parse.urlencode({"ids":",".join(series_ids),"last":last,"metadata":"full"})
    payload=json.loads(fetch("https://apis.datos.gob.ar/series/api/series/?"+qs,timeout=30).decode("utf-8"))
    rows=payload.get("data") or []
    if not rows: raise ValueError("API Series sin observaciones")
    out=[]
    for row in rows:
        if not isinstance(row,list) or len(row)<len(series_ids)+1: continue
        period=str(row[0])[:7]
        vals=[]
        for value in row[1:len(series_ids)+1]:
            try: vals.append(float(value) if value is not None else None)
            except Exception: vals.append(None)
        if len(period)==7 and all(v is not None for v in vals):
            out.append((period,vals))
    if not out: raise ValueError("API Series devolvió filas sin formato esperado")
    return out

def _month_days(period):
    dt=datetime.strptime(period+"-01","%Y-%m-%d")
    nxt=(dt.replace(day=28)+timedelta(days=4)).replace(day=1)
    return (nxt-dt).days

def _ar_decimal(text):
    return float(str(text).strip().replace("−","-").replace(",", "."))

def _latest_hydrocarbon_board():
    home="https://todohidrocarburos.com/"
    soup=BeautifulSoup(fetch(home,timeout=25),"html.parser")
    months={"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12}
    found=[]
    for a in soup.find_all("a",href=True):
        label=clean(a.get_text(" ",strip=True)).lower()
        m=re.search(r"tablero de control de(?:l)?\s+("+ "|".join(months) +r")\s+de\s+(20\d{2})",label,re.I)
        if not m: continue
        month=months[m.group(1).lower()]; year=int(m.group(2))
        found.append((year,month,urllib.parse.urljoin(home,a["href"])))
    if not found: raise ValueError("no se encontró tablero mensual en TodoHidrocarburos")
    year,month,url=max(found)
    return f"{year:04d}-{month:02d}",url

def _board_segment(text,start_label,end_label):
    m=re.search(re.escape(start_label)+r"(.*?)"+re.escape(end_label),text,re.I|re.S)
    if not m: raise ValueError("no se encontró bloque "+start_label)
    return m.group(1)

def _board_row(segment,label):
    p=re.escape(label).replace(r"\ ",r"\s+")
    m=re.search(p+r"\s+([\d,]+)\s+([+\-−]?\d+(?:\.\d+)?%)\s+([+\-−]?\d+(?:\.\d+)?%)",segment,re.I)
    if not m: raise ValueError("fila no encontrada: "+label)
    raw=m.group(1)
    value=_ar_decimal(raw)
    # The HTML export keeps three-decimal precision but suppresses leading
    # zeroes/separators for sub-1 MMm3/d values: Cuyana 0.076 is rendered
    # as "76", Formosa 0.009 as "9", etc.
    if ',' not in raw and value>=1:
        value=value/1000
    return value,m.group(2).replace("−","-"),m.group(3).replace("−","-")

def update_basin_production(d):
    u=next((x for x in d.get("updates",[]) if x.get("name")=="Producción por cuenca/provincia"),None)
    current=d.get("basinMonthlyMeta",{}).get("latest","")
    api_error=""
    # First try the official historical series. It is useful as an integrity
    # check, but at present its public API may lag the current-year dashboards.
    try:
        ids=["PROD_GAS_SESCO_1","PROD_GAS_SESCO_2","PROD_GAS_SESCO_3","PROD_GAS_SESCO_4","PROD_GAS_SESCO_5"]
        rows=_series_rows(ids,30)
        api_latest=max((p for p,_ in rows),default="")
        if api_latest>=current and api_latest.startswith("2026-"):
            raise ValueError("lector API vigente aún no implementado para reemplazo directo")
        api_error="API SESCO histórica disponible hasta "+api_latest
    except Exception as e:
        api_error=str(e)[:120]
    try:
        period,url=_latest_hydrocarbon_board()
        if current and period<current:
            raise ValueError("el último tablero publicado es anterior al período ya validado")
        raw=fetch(url,timeout=30)
        soup=BeautifulSoup(raw,"html.parser")
        text=clean(soup.get_text(" ",strip=True))
        basin_seg=_board_segment(text,"PRODUCCIÓN DE GAS NATURAL (Mm3/día)","PRODUCCIÓN DE GAS NATURAL POR PROVINCIA (Mm3/mes)")
        province_seg=_board_segment(text,"PRODUCCIÓN DE GAS NATURAL POR PROVINCIA (Mm3/día)","PRODUCCIÓN DE GAS NATURAL NO CONVENCIONAL POR PROVINCIA (Mm3/mes)")
        total,_,total_yoy=_board_row(basin_seg,"TOTAL PAIS")
        basin_labels=[
          ("Cuenca Neuquina","CUENCA NEUQUINA"),
          ("Cuenca Austral","CUENCA AUSTRAL"),
          ("Golfo San Jorge","CUENCA DEL GOLFO SAN JORGE"),
          ("Cuenca Noroeste","CUENCA NOROESTE"),
          ("Cuenca Cuyana","CUENCA CUYANA")
        ]
        basins=[]
        for display,label in basin_labels:
            value,mom,yoy=_board_row(basin_seg,label)
            basins.append({"name":display,"value":_format_ar(value,3),"unit":"MMm³/d",
                           "share":_format_ar(value/total*100,1)+"%","trend":yoy})
        if abs(sum(_ar_decimal(x["value"]) for x in basins)-total)>0.08:
            raise ValueError("la suma por cuencas no cierra con el total país")
        month_names=("Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre")
        label=month_names[int(period[-2:])-1]
        existing={x.get("month"):x for x in d.get("basinMonthly2026",[])}
        existing[period]={
          **existing.get(period,{}),"month":period,"label":label,"total":_format_ar(total,3),
          "reference":label+" "+period[:4]+" · promedio diario","validatedAt":iso(),
          "source":"SESCO / Secretaría de Energía · consolidado TodoHidrocarburos",
          "sourceUrl":url,"basins":basins
        }
        d["basinMonthly2026"]=sorted(existing.values(),key=lambda x:x.get("month",""))
        d.setdefault("basinMonthlyMeta",{}).update(
          year=2026,latest=max(existing),source="Producción promedio diaria por cuenca · SESCO/Secretaría de Energía",
          officialUrl="https://www.argentina.gob.ar/produccion/energia/planeamiento-energetico/panel-de-indicadores/produccion-gas-prom-diaria-cuenca",
          note="Actualización automática desde el tablero mensual que consolida estadísticas SESCO. Se valida el cierre contra el total país antes de publicar.",
          checkedAt=iso(),validatedAt=iso(),auto=True,readerVersion=2
        )
        province_names=["Chubut","Estado Nacional","Formosa","Jujuy","La Pampa","Mendoza","Neuquén","Rio Negro","SALTA","Santa Cruz","Tierra del Fuego"]
        provinces=[]
        for name in province_names:
            value,mom,yoy=_board_row(province_seg,name)
            display={"Rio Negro":"Río Negro","SALTA":"Salta"}.get(name,name)
            provinces.append({"name":display,"value":_format_ar(value,3),
                              "share":("<0,1%" if value/total*100<0.05 else _format_ar(value/total*100,1)+"%"),
                              "reference":label+" "+period[:4],"mom":mom,"yoy":yoy})
        ptotal,_,_=_board_row(province_seg,"Total general")
        if abs(sum(_ar_decimal(x["value"]) for x in provinces)-ptotal)>0.08 or abs(ptotal-total)>0.08:
            raise ValueError("la suma por provincias no cierra con el total país")
        d["provinces"]=provinces
        d.setdefault("provincesMeta",{}).update(
          total=_format_ar(total,3),reference=label+" "+period[:4]+" · promedio diario",
          source="SESCO / Secretaría de Energía · consolidado TodoHidrocarburos",sourceUrl=url,
          officialUrl="https://www.argentina.gob.ar/economia/energia/planeamiento-energetico/panel-de-indicadores/produccion-de-gas-promedio-diaria-por",
          note="Estado Nacional agrupa producción bajo jurisdicción nacional/offshore. Cuencas y provincias se publican sólo si ambos cierres coinciden con el total país.",
          checkedAt=iso(),validatedAt=iso(),auto=True
        )
        if u:
            u.update(last=iso(),next=iso(now()+timedelta(days=1)),
                     status="updated" if period>current else "unchanged",mode="Automática",
                     strategy="Último tablero mensual + validación de cierres",
                     scope="Detecta automáticamente el último mes, extrae gas por cuenca y provincia y valida ambas sumas contra el total país antes de reemplazar datos.",
                     note="Cuencas y provincias validadas automáticamente hasta "+period+". "+api_error+".")
        print("BASIN/PROVINCE",period,total,url)
    except Exception as e:
        print("BASIN/PROVINCE",e)
        if u:
            u.update(last=iso(),next=iso(now()+timedelta(days=1)),status="partial",mode="Automática",
                     note="Lectura mensual no validada; se conservan los últimos datos: "+str(e)[:180])


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
        u=next((x for x in d.get("updates",[]) if x.get("name")=="Demanda prioritaria"),None)
        if u: u.update(last=iso(),next=iso(now()+timedelta(hours=1)),status="updated" if old!=disp else "unchanged",
                       note="Ventana oficial de 5 días revalidada.")
    except Exception as e:
        print("DEMAND",e)
        u=next((x for x in d.get("updates",[]) if x.get("name")=="Demanda prioritaria"),None)
        if u: u.update(last=iso(),next=iso(now()+timedelta(hours=1)),status="pending",
                       note="No se pudo leer la ventana oficial; se conservan los últimos valores.")

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
                    k["statusText"]="NUEVO REPORTE · REVISAR"
                    k["note"]="Reporte disponible: "+latest+". No se pudo extraer el total; se conservan el valor anterior y su fecha de referencia."
            elif latest in oldref:
                k["validatedAt"]=iso()
            else:
                k["statusText"]="NUEVO REPORTE · REVISAR"
                k["note"]="ENReGE publicó un gráfico más reciente ("+latest+"). Se conserva el último total del sistema validado hasta recalcular TGN + TGS; la fecha de validación del valor no cambia."
        except Exception as e:
            print("SYSTEM",kid,e)
    u=next((x for x in d.get("updates",[]) if x.get("name")=="Sistema gasífero diario"),None)
    if u:
        newest=max((x.get("validatedAt","") for x in d.get("systemKpis",[]) if x.get("id") in ("linepack","injection")),default="")
        u.update(last=iso(),next=iso(now()+timedelta(hours=1)),status="unchanged",
                 note="Últimos reportes ENReGE revisados; inyección se extrae automáticamente y Linepack conserva el último total validado si requiere recálculo.")


def _number_ar(value):
    return float(str(value).replace(".","").replace(",","."))

def _format_ar(value,decimals=2):
    return f"{float(value):.{decimals}f}".replace(".",",")

def _monthly_pdf_url(month):
    return "https://www.enargas.gob.ar/secciones/transporte-y-distribucion/datos-operativos-despacho/graficos-programacion/9/PEI_"+month.replace("-","")+".pdf"

def _read_monthly_flows_pdf(month):
    from automatic_sources import monthly_values
    import pdfplumber
    with pdfplumber.open(io.BytesIO(fetch(_monthly_pdf_url(month),timeout=40))) as pdf:
        return monthly_values(pdf.pages[0].extract_words())

def _legacy_read_monthly_flows_pdf(month):
    from pypdf import PdfReader
    pdf=fetch(_monthly_pdf_url(month),timeout=40)
    text=" ".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(pdf)).pages)
    results={}
    names=r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
    for section,key in (("Exportaciones","exports"),("Importaciones","imports")):
        match=re.search(r"\b"+section+r"\b(.+?)\bPais\b",text,re.I|re.S)
        if not match: raise ValueError("falta el gráfico de "+section)
        segment=match.group(1)
        years=list(re.finditer(r"\b20\d{2}\b",segment))
        if not years: raise ValueError("falta el año del gráfico de "+section)
        headline=segment[:years[-1].start()]
        count=len(re.findall(r"\b"+names+r"\b",headline,re.I))
        if count<1: raise ValueError("faltan meses del gráfico de "+section)
        values=re.findall(r"\b\d{1,3},\d{2}\b",segment[years[-1].end():])
        if len(values)<count: raise ValueError("faltan totales mensuales de "+section)
        results[key]=_number_ar(values[count-1])
    return results

def monthly_flows_status(d):
    """Read the published monthly PDF when its chart text can be verified."""
    url="https://www.enargas.gob.ar/secciones/transporte-y-distribucion/dod-graficos-de-programacion-items.php?cat=9"
    months_names={
      "enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
      "julio":"07","agosto":"08","septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"
    }
    try:
        txt=clean(fetch(url).decode("utf-8","ignore")).lower()
        found=[]
        for name,num in months_names.items():
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
            # Check the parser against the already verified July report before trusting a new PDF.
            baseline=next((x for x in d.get("systemMonthly2026",[]) if x.get("month")==current),None)
            if not baseline: raise ValueError("falta un mes previamente validado para contrastar el lector")
            parsed_baseline=_read_monthly_flows_pdf(current)
            if any(abs(parsed_baseline[k]-_number_ar(baseline[k]))>0.02 for k in ("imports","exports")):
                raise ValueError("el diseño del PDF cambió: no coincide con el mes validado")
            months={x.get("month"):x for x in d.get("systemMonthly2026",[])}
            for month in sorted(x for x in found if x>current):
                values=_read_monthly_flows_pdf(month)
                previous=months[max(months)]
                for key in ("imports","exports"):
                    if not 0<=values[key]<100 or abs(values[key]-_number_ar(previous[key]))>60:
                        raise ValueError("valor mensual fuera de rango; requiere revisión")
                row={"month":month,"label":next(n.capitalize() for n,num in months_names.items() if num==month[-2:]),
                     "imports":_format_ar(values["imports"]),"exports":_format_ar(values["exports"]),
                     "validatedAt":iso(),"sourceUrl":_monthly_pdf_url(month)}
                months[month]=row
                # Keep the GNL/Chile figures at their own period until they have a verified parser.
                for item_id,key in (("imports_month","imports"),("exports_month","exports")):
                    k=next((x for x in d.get("systemKpis",[]) if x.get("id")==item_id),None)
                    if k: k.update(value=row[key],reference="Promedio · "+row["label"]+" "+month[:4],
                                   validatedAt=iso(),sourceUrl=row["sourceUrl"],statusText="OFICIAL")
            d["systemMonthly2026"]=sorted(months.values(),key=lambda x:x["month"])
            meta["latest"]=latest
            meta.pop("pendingMonth",None)
            meta["status"]="updated"
            meta["note"]="Importaciones y exportaciones totales extraídas del PDF oficial y contrastadas con el último mes validado. Desgloses GNL/Chile quedan con su propio período hasta validarlos."
        else:
            meta.pop("pendingMonth",None)
            meta["status"]="current"
        u=next((x for x in d.get("updates",[]) if x.get("name")=="Flujos mensuales"),None)
        if u:
            changed=meta.get("status")=="updated"
            u.update(last=iso(),next=iso(now()+timedelta(hours=1)),status="new_report" if changed else "unchanged",
                     note=meta.get("note") or ("Último mes publicado: "+str(meta.get("latest","—"))))
    except Exception as e:
        print("MONTHLY FLOWS",e)
        meta=d.setdefault("systemMonthlyMeta",{})
        if 'latest' in locals() and latest>str(meta.get("latest","")):
            meta.update(pendingMonth=latest,status="new_report",checkedAt=iso(),note="Reporte nuevo disponible; no se alteran los valores hasta poder verificar sus cifras: "+str(e)[:180])
        u=next((x for x in d.get("updates",[]) if x.get("name")=="Flujos mensuales"),None)
        if u: u.update(last=iso(),next=iso(now()+timedelta(hours=1)),status="pending",
                       note="No se pudo verificar el nuevo informe mensual; se conservan los últimos valores validados.")

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


REGULATION_START=datetime(2026,1,1,tzinfo=ART)
REGULATION_SEARCH_TERMS=(
    "gas natural","gasoducto","subdistribucion","GLP","GNL",
    "Plan Gas","PIST","comercializadores de gas","transporte de gas","distribucion de gas"
)
REGULATION_GAS_SIGNALS=(
    "gas natural","gas licuado","glp","gnl","lng","gasoduct","subdistrib",
    "propano","butano","plan gas","pist","comercializador",
    "transporte de gas","distribución de gas","distribucion de gas",
    "camuzzi","naturgy","metrogas","litoral gas","gasnea","gas nea","gasnor",
    "tgs","tgn","transportadora de gas","energía argentina sociedad anónima",
    "energia argentina sociedad anonima"
)
REGULATION_CATEGORY_RULES=(
    ("Subdistribución",("subdistrib","subdistribuidor","sdb")),
    ("GLP",("glp","gas licuado de petróleo","gas licuado de petroleo","propano","butano")),
    ("GNL",("gnl","lng","gas natural licuado")),
    ("Tarifas",("cuadro tarifario","cuadros tarifarios","tarifa","revisión tarifaria","revision tarifaria")),
    ("Precios",("precio anual uniforme"," pau ","pist","precio de gas","precio de paridad de exportación","precio de paridad de exportacion","ppe")),
    ("Subsidios",("subsid","bonificación","bonificacion","sef","segmentación","segmentacion")),
    ("Comercialización",("comercializador","comercialización","comercializacion","registro de comercializadores")),
    ("Transporte",("transporte de gas","transportista","capacidad firme","tgs","tgn","gasoducto norandino","energía argentina sociedad anónima","energia argentina sociedad anonima")),
    ("Distribución",("distribución de gas","distribucion de gas","distribuidora","camuzzi","naturgy","metrogas","litoral gas","gasnea","gas nea","gasnor")),
    ("Infraestructura",("gasoducto","planta compresora","infraestructura","ampliación","ampliacion","refuerzo","obra")),
    ("Técnica / operativa",("nag-","norma técnica","norma tecnica","reglamento","seguridad","integridad","odoriz","medición","medicion","calidad de gas","operación","operacion"))
)

def _norm_url(u):
    if not u: return ""
    u=urllib.parse.urljoin("https://www.argentina.gob.ar",u)
    u=u.split("#",1)[0].rstrip("/")
    for suffix in ("/texto","/actualizacion"):
        if u.endswith(suffix): u=u[:-len(suffix)]
    return u

def _reg_categories(text):
    low=(" "+(text or "").lower()+" ")
    cats=[]
    for name,terms in REGULATION_CATEGORY_RULES:
        if any(t in low for t in terms):
            cats.append(name)
    if not cats and ("mercado" in low or "registro" in low):
        cats.append("Mercado")
    return cats

def _reg_relevant(text):
    low=(text or "").lower()
    return any(k in low for k in REGULATION_GAS_SIGNALS)

def _reg_number(name):
    name=clean(name)
    m=re.search(r"(Resoluci[oó]n General|Resoluci[oó]n|Decreto|Disposici[oó]n|Decisi[oó]n Administrativa)\s+(\d+)\s*/\s*(\d{2,4})",name,re.I)
    if not m: return name[:90] or "Norma"
    kind=m.group(1)
    kind=kind[0].upper()+kind[1:]
    year=m.group(3)
    if len(year)==2: year="20"+year
    return f"{kind} {m.group(2)}/{year}"

def _reg_date(text):
    patterns=(
      r"Publicada en el Bolet[ií]n Oficial:\s*(\d{2}-\d{2}-\d{4})",
      r"Fecha de publicaci[oó]n\s*(\d{2}/\d{2}/\d{4})",
      r"Publicaci[oó]n:\s*(\d{2}-\d{2}-\d{4})"
    )
    for p in patterns:
        m=re.search(p,text,re.I)
        if m:
            raw=m.group(1)
            for fmtx in ("%d-%m-%Y","%d/%m/%Y"):
                try: return datetime.strptime(raw,fmtx).replace(tzinfo=ART)
                except Exception: pass
    return None

def _operative_section(text):
    text=clean(text or "")
    if not text: return ""
    markers=list(re.finditer(r"\b(?:RESUELVE|RESUELVEN|DECRETA|DISPONE|DISPONEN|DECIDE)\s*:",text,re.I))
    if markers:
        return text[markers[-1].end():]
    por_ello=list(re.finditer(r"\bPOR\s+ELLO\b",text,re.I))
    if por_ello:
        tail=text[por_ello[-1].end():]
        first=re.search(r"\bART[ÍI]CULO\s+1(?:[°ºo])?\s*[\.\-–—:]+",tail,re.I)
        if first: return tail[first.start():]
    return ""

def _first_article(text):
    section=_operative_section(text)
    if not section: return ""
    m=re.search(r"\bART[ÍI]CULO\s+1(?:[°ºo])?\s*[\.\-–—:]*\s*(.*?)(?=\s+\bART[ÍI]CULO\s+(?:2|2[°ºo]|SEGUNDO)\b|$)",section,re.I|re.S)
    if not m: return ""
    value=clean(m.group(1)).strip(" -–—")
    return value[:900]

def _disposition_summary(first_article,title="",fallback=""):
    text=clean(first_article or "")
    if not text:
        candidate=clean(title or fallback or "")
        generic=bool(re.search(r"^(?:ENTE |MINISTERIO |SECRETAR[IÍ]A |Resoluci[oó]n\s+\d|Decreto\s+\d)",candidate,re.I))
        return "" if generic else candidate[:360]
    # The operative first article usually starts with the action itself
    # (Apruébase, Autorízase, Fíjase, Convócase, etc.). Keep that action
    # rather than summarising the recitals.
    limit=360
    if len(text)<=limit: return text
    head=text[:limit+80]
    stops=[m.end() for m in re.finditer(r"\.(?=\s+[A-ZÁÉÍÓÚÑ])",head)]
    stop=max((x for x in stops if 120<=x<=limit+40),default=0)
    if stop: return head[:stop].strip()
    return text[:limit].rsplit(" ",1)[0].strip()+"…"


def _discover_regulation_urls():
    base="https://www.argentina.gob.ar/normativa/busqueda-avanzada"
    since=REGULATION_START.strftime("%Y-%m-%d")
    until=now().strftime("%Y-%m-%d")
    found={}
    successful=0
    for term in REGULATION_SEARCH_TERMS:
        page=1
        previous_page=set()
        while page<=3:
            params={
              "jurisdiccion":"nacional","tipo_norma":"legislaciones",
              "publicacion_desde":since,"publicacion_hasta":until,
              "texto":term,"limit":"50","offset":str(page)
            }
            try:
                raw=fetch(base+"?"+urllib.parse.urlencode(params),timeout=20)
                successful+=1
            except Exception as e:
                print("NORM SEARCH",term,page,e); break
            soup=BeautifulSoup(raw,"html.parser")
            table=soup.find("table")
            if not table: break
            rows=table.find_all("tr")[1:]
            if not rows: break
            this_page=set()
            for row in rows:
                cells=row.find_all("td")
                if not cells: continue
                link=row.find("a",href=True)
                if not link: continue
                url=_norm_url(link.get("href"))
                if "/normativa/nacional/" not in url: continue
                snippet=clean(cells[2].get_text(" ",strip=True)) if len(cells)>=3 else clean(row.get_text(" ",strip=True))
                found.setdefault(url,{"url":url,"snippet":snippet,"term":term})
                this_page.add(url)
            if not this_page or this_page==previous_page or len(rows)<50: break
            previous_page=this_page
            page+=1
    return found,successful

def _parse_regulation(url,hint=None):
    raw=fetch(url,timeout=35)
    soup=BeautifulSoup(raw,"html.parser")
    name=clean((soup.find("h1",class_="h5") or soup.find("h1") or "").get_text(" ",strip=True) if (soup.find("h1",class_="h5") or soup.find("h1")) else "")
    title_node=soup.find("h2",class_="h5") or soup.find("h2")
    title=clean(title_node.get_text(" ",strip=True)) if title_node else ""
    lead=soup.find("p",class_="lead m-b-0")
    issuer=""
    if lead:
        small=lead.find("small")
        issuer=clean(small.get_text(" ",strip=True)) if small else clean(lead.get_text(" ",strip=True))
    article=soup.find("article")
    summary=clean(article.get_text(" ",strip=True)) if article else clean(soup.get_text(" ",strip=True))
    text=" ".join(x for x in (name,title,issuer,(hint or {}).get("snippet",""),summary[:6500]) if x)
    if not _reg_relevant(text): return None
    dt=_reg_date(clean(soup.get_text(" ",strip=True)))
    if not dt or dt<REGULATION_START or dt>now()+timedelta(days=1): return None
    cats=_reg_categories(text)
    primary=cats[0] if cats else "Mercado"
    tags=list(dict.fromkeys(cats))
    low=text.lower()
    if "bagsa" in low or "subdistrib" in low: tags.append("BAGSA")
    first_article=_first_article(summary)
    disposition=_disposition_summary(first_article,title,(hint or {}).get("snippet",""))
    desc=(hint or {}).get("snippet") or title or disposition or summary[:280]
    desc=clean(desc)[:420]
    return {
      "num":_reg_number(name),"category":primary,"title":title or _reg_number(name),
      "publishedAt":iso(dt),"validatedAt":iso(),"sourceType":"OFFICIAL",
      "status":"updated","desc":desc,"firstArticle":first_article,"disposition":disposition,"operativePreview":bool(first_article),
      "tags":list(dict.fromkeys(tags)),
      "url":url,"issuer":issuer or "Organismo oficial","auto":True
    }


BORA_DISCOVERY_SIGNALS=REGULATION_GAS_SIGNALS+(
    "ente nacional regulador del gas","enrege","enargas","secretaría de energía","secretaria de energia"
)

def _reg_family(x):
    low=(" ".join(str(x.get(k,"")) for k in ("issuer","title","desc","num"))).lower()
    if any(k in low for k in ("enrege","enargas","ente nacional regulador del gas","camuzzi","naturgy","metrogas","litoral gas","gasnea","gas nea","gasnor","tgs","tgn")):
        return "enrege"
    if any(k in low for k in ("secretaría de energía","secretaria de energia","plan gas","precio de paridad","ppe","sef")):
        return "energia"
    return re.sub(r"\W+","",str(x.get("issuer") or "otro").lower())[:48] or "otro"

def _reg_identity(x):
    if x.get('jurisdiction') == 'PBA':
        return 'pba|' + str(x.get('url'))
    return _reg_family(x)+"|"+re.sub(r"\s+","",str(x.get("num","")).lower())

def _bora_label(a):
    label=clean(a.get_text(" ",strip=True))
    if len(label)<18 and a.parent:
        label=clean(a.parent.get_text(" ",strip=True))
    return label[:1200]

def _bora_issuer(label):
    m=re.search(r"(Resoluci[oó]n General|Resoluci[oó]n|Decreto|Disposici[oó]n|Decisi[oó]n Administrativa)\s+\d+\s*/\s*\d{2,4}",label,re.I)
    if not m: return ""
    return clean(label[:m.start()].strip(" -–—"))[:180]

def _bora_title(label):
    parts=re.split(r"\s+-\s+",label,maxsplit=1)
    if len(parts)>1 and len(parts[1].strip())>3:
        return clean(parts[1])[:260]
    m=re.search(r"(?:RESOL|RESFC|DECTO|DI|DA)-?\d{4}[^\s]*",label,re.I)
    if m and clean(label[m.end():].strip(" -–—")):
        return clean(label[m.end():].strip(" -–—"))[:260]
    return clean(label)[:260]

def _parse_bora_detail(url,day,label):
    raw=fetch(url,timeout=25)
    soup=BeautifulSoup(raw,"html.parser")
    article=soup.find("article")
    body=clean(article.get_text(" ",strip=True)) if article else clean(soup.get_text(" ",strip=True))
    title=_bora_title(label)
    issuer=_bora_issuer(label)
    text=" ".join((label,issuer,title,body[:10000]))
    if not _reg_relevant(text): return None
    cats=_reg_categories(text)
    primary=cats[0] if cats else "Mercado"
    tags=list(dict.fromkeys(cats))
    low=text.lower()
    if "bagsa" in low or "subdistrib" in low: tags.append("BAGSA")
    num=_reg_number(label)
    if not num or num=="Norma": return None
    first_article=_first_article(body)
    disposition=_disposition_summary(first_article,title,body[:380])
    desc=title
    if not desc or desc==label[:260]:
        desc=disposition or body[:380]
    return {
      "num":num,"category":primary,"title":title or num,
      "publishedAt":iso(datetime.combine(day,datetime.min.time(),tzinfo=ART)),
      "validatedAt":iso(),"sourceType":"OFFICIAL","status":"updated",
      "desc":clean(desc)[:420],"firstArticle":first_article,"disposition":disposition,"operativePreview":bool(first_article),
      "tags":list(dict.fromkeys(tags)),
      "url":url,"issuer":issuer or "Organismo oficial","auto":True
    }

def _scan_bora_dates(start_day,end_day,retry_dates=()):
    days=set(retry_dates); cur=start_day
    while cur<=end_day:
        if cur.weekday()<5: days.add(cur)
        cur+=timedelta(days=1)
    pages=[]; failed=[]
    def load(day):
        url="https://www.boletinoficial.gob.ar/seccion/primera/"+day.strftime("%Y%m%d")
        try: return day,fetch(url,timeout=20),None
        except Exception as e: return day,None,e
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(load,d) for d in days]
        for fut in as_completed(futs):
            day,raw,err=fut.result()
            if raw is not None: pages.append((day,raw))
            else: failed.append(day.isoformat())
    candidates={}
    for day,raw in pages:
        soup=BeautifulSoup(raw,"html.parser")
        # A successful HTTP request may still be an error/challenge or an unreadable index.
        links=soup.find_all("a",href=True)
        if not any("/detalleAviso/primera/" in a.get("href","") for a in links):
            page_text=clean(soup.get_text(" ",strip=True)).lower()
            if not any(message in page_text for message in ("no se encontraron avisos","no hay edición","sin publicaciones","no se publica")):
                failed.append(day.isoformat())
                continue
        for a in links:
            href=a.get("href","")
            if "/detalleAviso/primera/" not in href: continue
            label=_bora_label(a)
            low=label.lower()
            if not any(k in low for k in BORA_DISCOVERY_SIGNALS): continue
            url=urllib.parse.urljoin("https://www.boletinoficial.gob.ar",href)
            candidates[url]={"url":url,"day":day,"label":label}
    return candidates,len(days)-len(failed),sorted(failed)

def update_regulations(d):
    existing=[]
    for x in d.get("regulations",[]):
        try: dt=datetime.fromisoformat(x.get("publishedAt",""))
        except Exception: dt=None
        if dt and dt>=REGULATION_START:
            if not x.get("issuer") and "/normativa/nacional/" in str(x.get("url","")):
                try:
                    p=_parse_regulation(_norm_url(x["url"]),{"snippet":x.get("desc","")})
                except Exception: p=None
                if p: x={**x,"issuer":p.get("issuer",x.get("issuer"))}
            # Old previews were extracted before the parser was restricted to
            # the operative section. Clear them progressively and rebuild them.
            if x.get("firstArticle") and not x.get("operativePreview"):
                x.pop("firstArticle",None)
                x.pop("disposition",None)
            existing.append(x)
    state=d.setdefault("regulationScan",{})
    try:
        last=datetime.strptime(state.get("lastScannedDate",""),"%Y-%m-%d").date()
    except Exception:
        last=None
    start_day=REGULATION_START.date() if not last else max(REGULATION_START.date(),last-timedelta(days=2))
    end_day=now().date()
    retry_dates=[datetime.strptime(x,"%Y-%m-%d").date() for x in state.get("pendingDates",[])]
    candidates,pages_ok,failed_dates=_scan_bora_dates(start_day,end_day,retry_dates)
    # Keep failed detail requests even after their edition leaves the overlap window.
    for entry in state.get("pendingDetails",[]):
        entry={**entry,"day":datetime.strptime(entry["day"],"%Y-%m-%d").date()}
        candidates.setdefault(entry["url"],entry)
    known={_reg_identity(x):x for x in existing if x.get("num")}
    added=0; refreshed=0
    to_fetch=[]
    for entry in candidates.values():
        num=_reg_number(entry["label"])
        probe={"num":num,"issuer":_bora_issuer(entry["label"]),"title":_bora_title(entry["label"]),"desc":entry["label"]}
        key=_reg_identity(probe)
        if key in known:
            known[key]["validatedAt"]=iso(); known[key]["auto"]=True
            if not known[key].get("issuer"): known[key]["issuer"]=probe.get("issuer")
            refreshed+=1
        else:
            to_fetch.append(entry)
    failed_details=[]
    def parse_entry(entry):
        try: return entry,_parse_bora_detail(entry["url"],entry["day"],entry["label"]),False
        except Exception as e:
            print("BORA DETAIL",entry["url"],e); return entry,None,True
    if to_fetch:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs=[ex.submit(parse_entry,e) for e in to_fetch]
            for fut in as_completed(futs):
                entry,item,failed=fut.result()
                if failed: failed_details.append({**entry,"day":entry["day"].isoformat()})
                if not item: continue
                key=_reg_identity(item)
                if key in known:
                    refreshed+=1
                    continue
                known[key]=item; added+=1
    preview_backfilled=0
    preview_targets=sorted(
        (x for x in known.values() if x.get("url") and x.get("jurisdiction")!="PBA" and not x.get("firstArticle")),
        key=lambda x:x.get("publishedAt",""),reverse=True
    )[:80]
    def load_preview(item):
        try:
            raw=fetch(item["url"],timeout=15)
            soup=BeautifulSoup(raw,"html.parser")
            article=soup.find("article")
            body=clean(article.get_text(" ",strip=True)) if article else clean(soup.get_text(" ",strip=True))
            first=_first_article(body)
            return item,first,_disposition_summary(first,item.get("title",""),item.get("desc",""))
        except Exception as e:
            print("REG PREVIEW",item.get("url"),e)
            return item,"",""
    if preview_targets:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs=[ex.submit(load_preview,x) for x in preview_targets]
            for fut in as_completed(futs):
                item,preview,disposition=fut.result()
                if preview:
                    item["firstArticle"]=preview
                    item["disposition"]=disposition
                    item["operativePreview"]=True
                    item["validatedAt"]=iso()
                    preview_backfilled+=1

    items=list(known.values())
    items.sort(key=lambda x:x.get("publishedAt",""),reverse=True)
    d["regulations"]=items
    incomplete=bool(failed_dates or failed_details)
    state.update(lastScannedDate=end_day.isoformat(),source="Boletín Oficial de la República Argentina · Primera Sección",
                 lastRun=iso(),pagesOk=pages_ok,pagesError=len(failed_dates),candidates=len(candidates),
                 pendingDates=failed_dates,pendingDetails=failed_details,
                 complete=not incomplete,lastRange={"from":start_day.isoformat(),"to":end_day.isoformat()},
                 added=added,revalidated=refreshed,previewBackfilled=preview_backfilled)
    if not incomplete: state["lastSuccessfulAt"]=iso()
    d["regulationCriteria"]={
      "title":"Criterio GasData",
      "text":"Listado automático de normativa oficial relevante para gas natural/GLP/GNL desde el 01/01/2026. Se consulta la Primera Sección del Boletín Oficial y se clasifica por Subdistribución, Transporte, Distribución, Tarifas, Precios, Subsidios, Comercialización, GLP, GNL, Infraestructura y Técnica/operativa. Cada 3 horas se revisan nuevamente los últimos días y se incorporan las normas nuevas detectadas.",
      "updatedAt":iso()
    }
    src=next((x for x in d.get("sources",[]) if x.get("name")=="Boletín Oficial Nación · Normativa gas"),None)
    payload={
      "name":"Boletín Oficial Nación · Normativa gas","type":"Oficial",
      "content":"Primera Sección · normativa gas desde 01/01/2026",
      "cadence":"Cada 3 h","status":"REVISAR" if incomplete else "ACTIVA",
      "url":"https://www.boletinoficial.gob.ar/seccion/primera","checkedAt":iso(),
      "lastResult":f"{len(items)} normas · {added} nuevas · {refreshed} revalidadas · {preview_backfilled} vistas enriquecidas · {pages_ok} ediciones consultadas"
    }
    if not incomplete: payload["validatedAt"]=iso()
    if src: src.update(payload)
    else: d.setdefault("sources",[]).append(payload)
    oldsrc=next((x for x in d.get("sources",[]) if x.get("name")=="Argentina.gob.ar · Normativa gas"),None)
    if oldsrc: oldsrc["status"]="REFERENCIA"
    u=next((x for x in d.get("updates",[]) if x.get("name")=="Normativa"),None)
    if u:
        u.update(last=iso(),next=iso(now()+timedelta(hours=3)),
                 status=("partial" if pages_ok else "pending") if incomplete else ("updated" if added else "unchanged"),
                 note=f"Consulta {start_day:%d/%m/%Y}–{end_day:%d/%m/%Y} · {len(items)} normas guardadas · {added} nuevas · {preview_backfilled} fichas enriquecidas con Art. 1° · {len(failed_dates)} ediciones y {len(failed_details)} documentos pendientes de reintento.")


def _update_due(d,name,hours):
    u=next((x for x in d.get("updates",[]) if x.get("name")==name),None)
    if not u or not u.get("last"): return True
    try: last=datetime.fromisoformat(u["last"])
    except Exception: return True
    return now()>=last+timedelta(hours=hours)

def validate_pages(d):
    checks=[
      ("Tarifas ENReGE/BAGSA","https://www.enargas.gob.ar/secciones/precios-y-tarifas/resoluciones-tarifas-vigentes.php",24),
      ("Sistema gasífero diario","https://www.enargas.gob.ar/secciones/transporte-y-distribucion/datos-operativos.php",24)
    ]
    for name,url,h in checks:
        if not _update_due(d,name,h): continue
        try:
            fetch(url); ok=True
        except Exception as e:
            print(name,e); ok=False
        u=next((x for x in d.get("updates",[]) if x.get("name")==name),None)
        if u:
            u.update(last=iso(),next=iso(now()+timedelta(hours=h)),
                     status="unchanged" if ok else "pending")
    # Reachability check only: do not stamp every tariff row as newly validated.
    if _update_due(d,"Tarifas ENReGE/BAGSA",24):
        try: fetch("https://www.bagsa.com.ar/index.php/tarifas/")
        except Exception as e: print("BAGSA",e)

def sync_tariffs_from_regulations(d):
    regs=d.get("regulations",[])
    mapping=(
      ("TGN",("tgn","transportadora de gas del norte")),
      ("TGS",("tgs","transportadora de gas del sur")),
      ("Naturgy BAN",("naturgy","gas natural ban")),
      ("Camuzzi Gas Pampeana",("camuzzi gas pampeana",)),
      ("Camuzzi Gas del Sur",("camuzzi gas del sur",)),
      ("Litoral Gas",("litoral gas",))
    )
    for row in d.get("tariffs",[]):
        names=next((terms for label,terms in mapping if label==row.get("name")),())
        if not names: continue
        candidates=[]
        for r in regs:
            hay=(str(r.get("title",""))+" "+str(r.get("desc",""))+" "+str(r.get("issuer",""))).lower()
            cats=[str(r.get("category","")).lower()]+[str(t).lower() for t in r.get("tags",[])]
            if "tarifas" not in cats and "tarifa" not in hay: continue
            if any(n in hay for n in names): candidates.append(r)
        if not candidates: continue
        latest=max(candidates,key=lambda x:x.get("publishedAt",""))
        m=re.search(r"(\d+/\d{4})",str(latest.get("num","")))
        resolution=m.group(1) if m else latest.get("num",row.get("res"))
        if resolution!=row.get("res"):
            # Publication and tariff-effective dates are not interchangeable.
            row["pendingResolution"]=resolution
            row["pendingUrl"]=latest.get("url")
            row["status"]="review_effective_date"
            continue
        row["validatedAt"]=latest.get("validatedAt") or row.get("validatedAt")
        row["url"]=latest.get("url",row.get("url"))
        row["auto"]=True

def bopba_monitor(d):
    """Check only the Provincial Official Gazette results relevant to GasData."""
    base="https://boletinoficial.gba.gob.ar/buscar"
    since=REGULATION_START.strftime("%d/%m/%Y")
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
        src["checkedAt"]=iso()
        if all(v["ok"] for v in results.values()): src["validatedAt"]=iso()
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
                 status="pending" if not any(v["ok"] for v in results.values()) else ("partial" if not all(v["ok"] for v in results.values()) else "monitored"),
                 note="Monitoreo desde 01/01/2026: se consulta la primera página de resultados para “gas natural” y “BAGSA”; no se incorporan actos provinciales al listado. Coincidencias visibles: "+str(sum(v["matches"] for v in results.values()))+".")

def sync_update_catalog(d):
    existing={x.get("name"):x for x in d.get("updates",[]) if x.get("name")}
    specs=[
      ("Noticias","Cada 60 min","Automática","Ventana reciente + deduplicación","Consulta RSS (hasta 60 entradas por fuente) y portadas; incorpora URLs nuevas y conserva hasta 80 noticias."),
      ("Normativa","Cada 3 h","Automática incremental","Backfill 01/01/2026 + solapamiento de 2 días","Primera ejecución recorre el año; luego consulta sólo desde la última fecha procesada menos 2 días para capturar publicaciones tardías."),
      ("Tarifas ENReGE/BAGSA","Diaria","Automática","Cuadros BAGSA + normativa","Detecta automáticamente los cuadros vigentes, resolución y fecha de vigencia para GN/GLP. Si un documento no puede verificarse, conserva la última referencia válida."),
      ("Producción nacional","Cada 15 días","Automática","Último período publicado","Busca la publicación oficial más reciente y nunca reemplaza un período por otro más antiguo."),
      ("Producción por cuenca/provincia","Diaria","Automática","Último tablero mensual + validación de cierres","Detecta el último tablero mensual, extrae gas por cuenca y provincia y sólo publica si ambas sumas cierran contra el total país."),
      ("Demanda prioritaria","Cada 60 min","Automática","Relectura de ventana vigente","Relee la ventana oficial de 5 días y reemplaza la serie cuando cambia."),
      ("Sistema gasífero diario","Cada 60 min","Automática parcial","Último reporte disponible","Inyección se extrae del PDF oficial; Linepack detecta nuevos reportes y conserva el último total validado si no puede recalcularlo."),
      ("Flujos mensuales","Cada 60 min","Automática parcial","Totales del PDF verificados","Si aparece un mes nuevo, compara el lector con el mes ya validado y actualiza importaciones/exportaciones totales. Los desgloses GNL/Chile se muestran sólo para meses con cifras validadas."),
      ("Capacidad de transporte","Cada 3 h","Automática","Estado vigente","Relee concursos ENReGE y reventas MEGSA; mezcla por identificador y conserva concursos verificados si la página dinámica no expone el listado."),
      ("Boletín Oficial PBA","Cada 3 h","Automática incremental","Backfill 01/01/2026 + solapamiento de 2 días","Consulta “gas natural” y “BAGSA”, pagina los resultados, verifica coincidencias por texto e incorpora automáticamente publicaciones nuevas al listado de Normativa."),
      ("Precios de mercado","Cada 60 min","Automática parcial","EIA diaria + Banco Mundial mensual","Henry Hub y propano: EIA. Gas Europa y GNL Japón: Banco Mundial. Las demás referencias se identifican como manuales y conservan su fecha.")
    ]
    out=[]
    for name,cadence,mode,strategy,scope in specs:
        old=existing.get(name,{})
        # Compatibility with the previous generic production update.
        if name=="Producción nacional" and not old:
            old=existing.get("Producción",{})
        item={**old,"name":name,"cadence":cadence,"mode":mode,"strategy":strategy,"scope":scope}
        out.append(item)
    d["updates"]=out


def refresh_source_status(d):
    for src in d.get("sources",[]):
        try:
            fetch(src["url"],timeout=20)
            src["availability"]="DISPONIBLE"
            src["checkedAt"]=iso()
        except Exception:
            src["availability"]="NO DISPONIBLE"
            src["checkedAt"]=iso()

def main():
    from automatic_sources import update_market, update_bagsa, update_bopba
    d=json.loads(DATA.read_text(encoding="utf-8"))
    sync_update_catalog(d)
    update_news(d)
    scan=d.get("regulationScan",{})
    needs_reg_migration=any(x.get("firstArticle") and not x.get("operativePreview") for x in d.get("regulations",[]))
    needs_reg_backfill=any(x.get("jurisdiction")!="PBA" and x.get("url") and not x.get("firstArticle") for x in d.get("regulations",[]))
    if not scan.get("lastScannedDate") or scan.get("pendingDates") or scan.get("pendingDetails") or needs_reg_migration or needs_reg_backfill or _update_due(d,"Normativa",3): update_regulations(d)
    sync_tariffs_from_regulations(d)
    if d.get("tariffAutomation",{}).get("readerVersion")!=4 or _update_due(d,"Tarifas ENReGE/BAGSA",24) or not d.get('tariffAutomation'):
        update_bagsa(d,fetch,iso)
    update_market(d,fetch,iso)
    validate_pages(d)
    production(d)
    if d.get("basinMonthlyMeta",{}).get("readerVersion")!=2 or _update_due(d,"Producción por cuenca/provincia",24): update_basin_production(d)
    demand_priority(d)
    system_market(d)
    monthly_flows_status(d)
    if _update_due(d,"Capacidad de transporte",3): transport_capacity(d)
    needs_pba_migration=d.get("bopbaScan",{}).get("cleanupVersion")!=5 or any(x.get("jurisdiction")=="PBA" and not x.get("disposition") for x in d.get("regulations",[]))
    if not d.get("bopbaScan") or needs_pba_migration or _update_due(d,"Boletín Oficial PBA",3): update_bopba(d,fetch,iso,now())
    refresh_source_status(d)
    sync_update_catalog(d)
    d["meta"]["updatedAt"]=iso()
    d["meta"]["version"]="2.0.0"
    DATA.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
