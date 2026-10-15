"""Weekly public GIS snapshots; keep last valid geometry after failures."""
from __future__ import annotations
import csv, io, json, math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
csv.field_size_limit(8_000_000)
BASE=Path(__file__).resolve().parents[1]
OUTPUT=BASE/'data/infrastructure-layers.json'
GIS='https://sig.enargas.gov.ar/arcgis/rest/services/Enargas_ext/'
BASINS='https://datos.energia.gob.ar/dataset/0d4a18ee-9371-439a-8a94-4f53a9822664/resource/04263302-626d-4a81-9564-106e08b975a3/download/exploracin-hidrocarburos-cuencas-sedimentarias.csv'
SPECS=[('network','Gasoductos publicados',GIS+'Gsoductos_de_Transporte/MapServer/0','ENARGAS / ENReGE'),('enarsa','Gasoductos ENARSA',GIS+'Gsoductos_de_Transporte/MapServer/1','ENARGAS / ENReGE'),('international','Importación / exportación',GIS+'Gsoductos_de_Transporte/MapServer/2','ENARGAS / ENReGE'),('compressors','Plantas compresoras',GIS+'Plantas_Compresoras/MapServer/0','ENARGAS / ENReGE'),('basins','Cuencas sedimentarias productivas',BASINS,'Secretaría de Energía')]

def dt(s):
    try:
        v=datetime.fromisoformat(s);return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v
    except (ValueError,TypeError):return None

def due(layer,now):
    limit=dt(layer.get('retryAt')) if layer.get('status')=='error' else dt(layer.get('nextCheckAt'))
    return not limit or now>=limit

def valid_geometry(g):
    if not isinstance(g,dict) or g.get('type') not in ('Point','LineString','MultiLineString','Polygon','MultiPolygon'):return False
    def valid(c):
        if not isinstance(c,list) or not c:return False
        if isinstance(c[0],(int,float)):
            return len(c)>=2 and all(isinstance(x,(int,float)) and math.isfinite(x) for x in c[:2]) and -180<=c[0]<=180 and -90<=c[1]<=90
        return all(valid(x) for x in c)
    return valid(g.get('coordinates'))

def round_coords(c):
    return [round(x,5) if isinstance(x,(int,float)) else round_coords(x) for x in c]

def decode(properties,fields):
    p=dict(properties)
    for f in fields:
        vals={x['code']:x['name'] for x in (f.get('domain') or {}).get('codedValues',[])}
        if f['name'] in p:p[f['name']]=vals.get(p[f['name']],p[f['name']])
    return p

def prop(p,*names):
    for name in names:
        if p.get(name) not in (None,'',' '):return p[name]
        for key,value in p.items():
            if key.endswith('.'+name) and value not in (None,'',' '):return value
    return None

def arcgis(fetch,url,kind):
    meta=json.loads(fetch(url+'?f=json',timeout=25))
    if meta.get('error'):raise ValueError('Metadatos ArcGIS no disponibles')
    fields='*' if kind=='compressors' else ','.join(f['name'] for f in meta.get('fields',[]) if f['name'] in ['Nombre','Gasoducto','Tramo','Diametro','Licenciataria','Fuente','Licenciata']) or '*'
    params={'where':'1=1','outFields':fields,'outSR':4326,'returnGeometry':'true','geometryPrecision':5,'maxAllowableOffset':0.001,'f':'geojson'}
    payload=json.loads(fetch(url+'/query?'+urlencode(params),timeout=40))
    if payload.get('error'):raise ValueError('Respuesta ArcGIS inválida; no se reemplaza la capa')
    if payload.get('exceededTransferLimit'):
        ids=json.loads(fetch(url+'/query?'+urlencode({'where':'1=1','returnIdsOnly':'true','f':'json'}),timeout=30)).get('objectIds')
        if not ids:raise ValueError('No se pudieron resolver los identificadores completos')
        complete=[]
        for start in range(0,len(ids),400):
            batch={**params,'objectIds':','.join(map(str,ids[start:start+400]))};batch.pop('where',None)
            part=json.loads(fetch(url+'/query?'+urlencode(batch),timeout=40))
            if part.get('error') or part.get('exceededTransferLimit'):raise ValueError('Lote ArcGIS truncado')
            complete.extend(part.get('features',[]))
        if len(complete)!=len(ids):raise ValueError('Conteo ArcGIS incompleto')
        payload={'features':complete}
    features=payload.get('features',[])
    if not features:raise ValueError('Capa vacía; se conserva la anterior')
    out=[]
    for f in features:
        g=f.get('geometry')
        if not valid_geometry(g):raise ValueError('Geometría inválida; no se reemplaza la capa')
        p=decode(f.get('properties',{}),meta.get('fields',[]))
        owner=prop(p,'Licenciataria','Licenciata') or ('Energía Argentina S.A.' if kind=='enarsa' else 'No disponible')
        name=prop(p,'sig_enargas.SDE.TM_PC.Nombre','Nombre','Gasoducto') or 'Sin nombre publicado'
        out.append({'type':'Feature','geometry':{'type':g['type'],'coordinates':round_coords(g['coordinates'])},'properties':{'name':str(name),'operator':str(owner),'section':str(prop(p,'Tramo') or ''),'diameter':prop(p,'Diametro')}})
    return out,meta.get('editingInfo',{}).get('lastEditDate')

def simplify_ring(points,tolerance=0.003):
    if len(points)<5:return points
    keep={0,len(points)-1};stack=[(0,len(points)-1)]
    while stack:
        start,end=stack.pop();a,b=points[start],points[end];dx,dy=b[0]-a[0],b[1]-a[1];den=dx*dx+dy*dy;best=0;index=None
        for i in range(start+1,end):
            p=points[i];t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)) if den else 0
            dist=(p[0]-a[0]-t*dx)**2+(p[1]-a[1]-t*dy)**2
            if dist>best:best,index=dist,i
        if index is not None and best>tolerance*tolerance:keep.add(index);stack.extend([(start,index),(index,end)])
    out=[points[i] for i in sorted(keep)]
    return out if len(out)>=4 and out[0]==out[-1] else points

def basin_coordinates(g):
    if g['type']=='Polygon':return [simplify_ring(r) for r in g['coordinates']]
    return [[simplify_ring(r) for r in poly] for poly in g['coordinates']]

def read_basins(fetch):
    rows=list(csv.DictReader(io.StringIO(fetch(BASINS,timeout=40).decode('utf-8-sig'))));out=[]
    for row in rows:
        if row.get('tipo','').strip().lower()!='productiva':continue
        g=json.loads(row['geojson'])
        if g.get('type')=='Feature':g=g['geometry']
        if not valid_geometry(g):raise ValueError('Geometría de cuenca inválida')
        out.append({'type':'Feature','geometry':{'type':g['type'],'coordinates':round_coords(basin_coordinates(g))},'properties':{'name':row['cuenca'],'type':row['tipo'],'location':row.get('ubicacion','')}})
    if len(out)<5:raise ValueError('No se hallaron las cinco cuencas productivas')
    return out,None

def refresh_layers(fetch,now,path=OUTPUT):
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):data={'meta':{'schemaVersion':1},'layers':[]}
    old={x['id']:x for x in data.get('layers',[])};changed=False;layers=[]
    for key,label,url,source in SPECS:
        item=old.get(key,{'id':key,'label':label,'source':source,'sourceUrl':url,'features':[]})
        if due(item,now):
            changed=True;item={**item,'checkedAt':now.isoformat(timespec='minutes')}
            try:
                features,source_date=read_basins(fetch) if key=='basins' else arcgis(fetch,url,key)
                item.update(features=features,status='ok',lastSuccessAt=item['checkedAt'],sourceUpdatedAt=source_date,nextCheckAt=(now+timedelta(days=7)).isoformat(timespec='minutes'),retryAt=None,error=None)
            except Exception as e:
                item.update(status='error',error=str(e)[:200],retryAt=(now+timedelta(hours=6)).isoformat(timespec='minutes'))
        layers.append(item)
    if changed:
        data={'meta':{'schemaVersion':1,'checkedAt':now.isoformat(timespec='minutes'),'cadence':'Semanal; reintento a las 6 h si falla','geometryNote':'Geometrías oficiales generalizadas para visualización, sin certificar ubicación de ingeniería ni estado operativo. La fecha de consulta no es la fecha de edición de la fuente.'},'layers':layers}
        path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n');tmp.replace(path)
    return data

def update_layers(d,fetch,now,iso):
    try:
        data=refresh_layers(fetch,now());d['infrastructureLayersMeta']={**data['meta'],'errors':sum(x.get('status')=='error' for x in data['layers'])}
    except Exception as e:print('INFRA GIS',str(e)[:200])
