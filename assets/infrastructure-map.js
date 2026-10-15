/* Geographic references are curated separately from automated project facts. */
(() => {
 'use strict';
 const root=document.getElementById('infraestructura');if(!root)return;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const link=u=>/^https:\/\//.test(u||'')?esc(u):'#';
 const color=p=>p.products.includes('GNL')?'#7954a4':p.products.includes('Petróleo / líquidos')?'#bb751d':'#147e8a';
 let geography=null,basemap=null,last=null,overview=null,detailMap=null,detailNode=null,active=null,frame=null,baseError=false;
 let systems=null,systemsPromise=null;
 const systemOptions={network:false,compressors:false,basins:false,operator:''},systemMaps=new Map();
 const allBounds=[[-56,-75],[-21,-52]];
 const valid=p=>p&&Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&p.lat>=-90&&p.lat<=90&&p.lon>=-180&&p.lon<=180;
 const points=p=>(geography?.projects[p.id]?.points||[]).filter(valid);
 const label=p=>p.products.includes('GNL')?'GNL':p.products.includes('Petróleo / líquidos')?'Petróleo / líquidos':'Gas';
 const coords=ps=>ps.map(p=>[p.lat,p.lon]);
 function mapAt(node){
   const m=L.map(node,{scrollWheelZoom:false,zoomSnap:0.25,zoomDelta:0.5,minZoom:3,maxZoom:14,zoomControl:true,attributionControl:true});
   m.createPane('infraSystem');m.getPane('infraSystem').style.zIndex=350;
   systemMaps.set(m,L.layerGroup().addTo(m));m.on('unload',()=>systemMaps.delete(m));
   m.createPane('infraReference');m.getPane('infraReference').style.zIndex=150;
   if(basemap)L.geoJSON(basemap,{pane:'infraReference',style:f=>({color:'#9bafb4',weight:1,fillColor:f.properties.name==='Argentina'?'#edf4f0':'#f5f4ef',fillOpacity:1}),interactive:false}).addTo(m);
   m.attributionControl.addAttribution('<a href="https://www.naturalearthdata.com/">Natural Earth</a>');
   const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',updateWhenIdle:true,keepBuffer:1});
   tiles.on('tileerror',()=>{const n=node.parentElement?.querySelector('.infra-tile-status');if(n)n.textContent='El fondo detallado no respondió. Se conserva la cartografía de referencia y los proyectos.';});
   tiles.addTo(m);m.fitBounds(allBounds,{padding:[18,18]});installSystemControls(node);drawSystem(m);return m;
 }
 function operator(p){const v=String(p.operator||'');return /gas del norte|\btgn\b/i.test(v)?'TGN':/gas del sur|\btgs\b/i.test(v)?'TGS':/energ[ií]a argentina|enarsa/i.test(v)?'ENARSA':'Otras';}
 const networkColor=p=>({TGS:'#306bb3',TGN:'#c35649',ENARSA:'#448568',Otras:'#727c85'})[operator(p)];
 function systemDate(v){if(!v)return 'No informada';const d=new Date(v);return isNaN(d)?'No informada':new Intl.DateTimeFormat('es-AR',{dateStyle:'short',timeZone:'America/Argentina/Buenos_Aires'}).format(d);}
 function installSystemControls(node){
   const container=node.parentElement;if(container.querySelector('[data-system-controls]'))return;
   node.insertAdjacentHTML('beforebegin',`<details class="gd-system-controls" data-system-controls><summary>Capas del sistema gasífero <span data-system-count></span></summary><div class="gd-layer-choices"><label><input type="checkbox" data-system-layer="network" ${systemOptions.network?'checked':''}> Gasoductos publicados</label><label><input type="checkbox" data-system-layer="compressors" ${systemOptions.compressors?'checked':''}> Plantas compresoras</label><label><input type="checkbox" data-system-layer="basins" ${systemOptions.basins?'checked':''}> Cuencas productivas</label><label>Transportista<select data-system-operator><option value="">Todas</option>${['TGS','TGN','ENARSA','Otras'].map(v=>`<option value="${v}" ${systemOptions.operator===v?'selected':''}>${v}</option>`).join('')}</select></label></div><p class="gd-network-legend"><span style="--pin:#306bb3">TGS</span><span style="--pin:#c35649">TGN</span><span style="--pin:#448568">ENARSA</span><span style="--pin:#727c85">Otras</span> · colores de las líneas; los proyectos conservan sus colores por energía.</p><p class="gd-layer-status" role="status"></p><details class="gd-layer-evidence"><summary>Fuentes y vigencia de las capas</summary><div data-system-sources></div></details></details>`);
   systemMetadata();
 }
 function systemMetadata(){
   root.querySelectorAll('[data-system-controls]').forEach(el=>{
     el.querySelectorAll('[data-system-layer]').forEach(x=>x.checked=systemOptions[x.dataset.systemLayer]);el.querySelector('[data-system-operator]').value=systemOptions.operator;
     el.querySelector('[data-system-count]').textContent=Object.keys(systemOptions).filter(k=>k!=='operator'&&systemOptions[k]).length+' activas';
     el.querySelector('[data-system-sources]').innerHTML=systems?`<p>${esc(systems.meta.geometryNote)}</p>`+systems.layers.map(l=>`<p><a href="${link(l.sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(l.label)} · ${esc(l.source)} ↗</a><br>${l.features.length} elementos · última consulta ${systemDate(l.checkedAt)} · última válida ${systemDate(l.lastSuccessAt)} · edición de la fuente ${systemDate(l.sourceUpdatedAt)}${l.status==='error'?' · error: se conserva la última capa válida':''}</p>`).join('')+'<p>Actualización semanal; ante fallos se reintenta a las 6 horas. Las capas publicadas no certifican que cada instalación esté operativa.</p>':'Las capas se consultan al activarlas. Se descargan desde GasData, sin consultar los servicios oficiales desde tu navegador.';
   });
 }
 function drawSystem(m){
   const group=systemMaps.get(m);if(!group)return;group.clearLayers();if(!systems)return;
   const selected=systems.layers.filter(l=>l.id==='basins'?systemOptions.basins:l.id==='compressors'?systemOptions.compressors:systemOptions.network).sort((a,b)=>(a.id==='basins'?-1:0)-(b.id==='basins'?-1:0));
   for(const layer of selected){const fs=layer.features.filter(f=>layer.id==='basins'||!systemOptions.operator||operator(f.properties)===systemOptions.operator);
     L.geoJSON({type:'FeatureCollection',features:fs},{pane:'infraSystem',style:f=>layer.id==='basins'?{color:'#8e6d48',weight:1,fillColor:'#d7bd85',fillOpacity:.18}:{color:networkColor(f.properties),weight:2.2,opacity:.75},pointToLayer:(f,ll)=>L.circleMarker(ll,{pane:'infraSystem',radius:5,color:'#253d46',weight:1.5,fillColor:networkColor(f.properties),fillOpacity:1}),onEachFeature:(f,path)=>{const p=f.properties;path.bindPopup(`<div class="infra-map-popup"><b>${esc(p.name)}</b><p>${esc(layer.label)}</p>${p.operator?`<p>Operador publicado: ${esc(p.operator)}</p>`:''}${p.section?`<p>Tramo: ${esc(p.section)}</p>`:''}${p.diameter!=null?`<p>Diámetro publicado: ${esc(p.diameter)} pulgadas</p>`:''}<small>Geometría oficial generalizada para visualización. No certifica estado operativo ni un plano de ingeniería.</small><a href="${link(layer.sourceUrl)}" target="_blank" rel="noopener noreferrer">Fuente oficial ↗</a></div>`);}}).addTo(group);
   }
 }
 async function loadSystems(force=false){
   if(systems&&!force){systemMaps.forEach((g,m)=>drawSystem(m));return;}if(systemsPromise)return systemsPromise;
   const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),25000);
   root.querySelectorAll('.gd-layer-status').forEach(n=>n.textContent='Cargando capas oficiales…');
   systemsPromise=(async()=>{try{const res=await fetch('data/infrastructure-layers.json',{cache:'no-cache',signal:abort.signal});if(!res.ok)throw Error('HTTP '+res.status);const d=await res.json();if(d.meta?.schemaVersion!==1||!Array.isArray(d.layers))throw Error('Formato desconocido');systems=d;systemMaps.forEach((g,m)=>drawSystem(m));systemMetadata();root.querySelectorAll('.gd-layer-status').forEach(n=>n.textContent=d.layers.some(l=>l.status==='error')?'Hay fuentes con error. Se conserva la última geometría válida.':'Capas oficiales listas. Activá sólo las que quieras visualizar.');}catch(e){root.querySelectorAll('.gd-layer-status').forEach(n=>n.textContent='No se pudieron renovar las capas. Se conserva la última versión cargada; los proyectos siguen disponibles.');}finally{clearTimeout(timer);systemsPromise=null;}})();return systemsPromise;
 }
 root.addEventListener('change',e=>{
   if(e.target.dataset.systemLayer){systemOptions[e.target.dataset.systemLayer]=e.target.checked;systemMetadata();loadSystems();}
   if(e.target.hasAttribute('data-system-operator')){systemOptions.operator=e.target.value;if(systemOptions.operator)systemOptions.network=true;systemMetadata();loadSystems();}
 });
 setInterval(()=>{if(systems&&!document.hidden)loadSystems(true);},3600000);
 function popup(p){return `<div class="infra-map-popup"><span>${esc(p.id)} · ${esc(label(p))}</span><b>${esc(p.name)}</b><p>${esc(p.verifiedStatus)}</p><small>Ubicación aproximada · ${esc(p.provinces.join(' / '))}</small><button type="button" data-infra-open="${esc(p.id)}">Abrir ficha →</button><button type="button" data-project-follow="${esc(p.id)}">☆ Seguir obra</button></div>`;}
 function fit(m,ps){if(ps.length===1)m.setView([ps[0].lat,ps[0].lon],9);else if(ps.length)m.fitBounds(coords(ps),{padding:[35,35],maxZoom:10});}
 function drawOverview(){
   if(!overview||!last)return;
   overview.layers.clearLayers();
   // Group nearby references on screen, retaining all project IDs without artificial offsets.
   const groups=[];
   last.projects.forEach(p=>{
     const ps=points(p);if(!ps.length)return;
     const center=L.latLng(ps.reduce((s,q)=>s+q.lat,0)/ps.length,ps.reduce((s,q)=>s+q.lon,0)/ps.length);
     const pixel=overview.map.latLngToLayerPoint(center);
     let group=groups.find(g=>g.pixel.distanceTo(pixel)<32);
     if(!group){group={center,pixel,projects:[]};groups.push(group);}group.projects.push(p);
   });
   groups.forEach(g=>{
     const multi=g.projects.length>1,p=g.projects[0],selected=g.projects.some(x=>x.id===active);
     const icon=L.divIcon({className:'infra-map-icon',html:`<span class="infra-pin${multi?' cluster':''}${selected?' selected':''}" style="--pin:${multi?'#385b66':color(p)}">${multi?g.projects.length:esc(p.id)}</span>`,iconSize:[38,32],iconAnchor:[19,16]});
     const marker=L.marker(g.center,{icon,title:multi?g.projects.length+' proyectos próximos':p.name,keyboard:true}).addTo(overview.layers);
     marker.bindPopup(multi?`<div class="infra-map-popup"><b>${g.projects.length} proyectos en esta zona</b><p>Acercá el mapa o elegí una ficha.</p>${g.projects.map(x=>`<button type="button" data-infra-open="${esc(x.id)}">${esc(x.id)} · ${esc(x.name)}</button>`).join('')}</div>`:popup(p),{maxWidth:330,maxHeight:300});
   });
   if(active){const p=last.projects.find(x=>x.id===active);if(p)points(p).forEach((pt,i)=>L.circleMarker([pt.lat,pt.lon],{radius:7,color:color(p),weight:3,fillColor:'#fff',fillOpacity:1}).bindTooltip(`${i+1}. ${esc(pt.label)} · aproximado`).addTo(overview.layers));}
 }
 function focus(id){
   const p=last?.projects.find(x=>x.id===id);if(!p||!overview)return;
   active=id;fit(overview.map,points(p));drawOverview();
   const geo=geography.projects[id];
   root.querySelector('#infraMapSelection').innerHTML=`<b>${esc(p.name)}</b><span>${esc(p.verifiedStatus)} · ${esc(p.provinces.join(' / '))}</span><small>${esc(geo.note)}</small><button type="button" data-infra-open="${esc(p.id)}">Abrir ficha →</button><button type="button" data-project-follow="${esc(p.id)}">☆ Seguir obra</button>`;
   overview.map.closePopup();
 }
 function sidebar(){
   const n=root.querySelector('#infraMapProjects');if(!n)return;
   n.innerHTML=last.projects.map(p=>`<button type="button" class="infra-map-project" data-infra-locate="${esc(p.id)}" style="--pin:${color(p)}"><span>${esc(p.id)} · ${esc(label(p))}</span><b>${esc(p.name)}</b><small>${esc(p.stage)} · ${esc(p.provinces.join(' / '))}</small></button>`).join('')||'<p class="infra-muted">Sin proyectos para estos filtros.</p>';
   root.querySelector('#infraMapTotal').textContent=`${last.projects.filter(p=>points(p).length).length} proyectos ubicados · mismos filtros del listado`;
 }
 function documentView(p,g){
   const docs=g.documents||[];
   return `<div class="infra-geo-evidence"><h4>Mapas, croquis y documentación de origen</h4>${docs.map(d=>`<article>${d.image?`<a href="${link(d.url)}" target="_blank" rel="noopener noreferrer"><img class="infra-source-map" src="${esc(d.image)}" alt="${esc(d.title)}" loading="lazy"></a>`:''}<b>${esc(d.title)}</b><p>${esc(d.publisher)} · ${esc(d.note||'')}</p><a href="${link(d.url)}" target="_blank" rel="noopener noreferrer">Consultar en la fuente ↗</a>${d.license?`<small>Licencia: <a href="${link(d.licenseUrl)}" target="_blank" rel="noopener noreferrer">${esc(d.license)}</a></small>`:''}</article>`).join('')}${!docs.length?'<p class="infra-muted">Todavía no hay un mapa o croquis documental verificado para esta ficha. Se muestra la ubicación aproximada y se conserva el esquema conceptual.</p>':''}<details><summary>Referencias de ubicación y precisión</summary><p>${esc(g.note)}</p><p>Los puntos corresponden a localidades o áreas de referencia, no a coordenadas relevadas de los equipos. No se dibuja una traza exacta a partir de ellos.</p>${g.sourceUrls.map((u,i)=>`<a href="${link(u)}" target="_blank" rel="noopener noreferrer">Documento de ubicación ${i+1} ↗</a>`).join(' · ')}<small>Revisión cartográfica: ${esc(geography.meta.verifiedAt)}. La actualización de noticias no modifica estas referencias.</small></details></div>`;
 }
 function renderDetail(){
   const node=root.querySelector('#infraProjectMap');
   if(detailNode===node&&detailMap){detailMap.invalidateSize();return;}
   if(detailMap){detailMap.remove();detailMap=null;}detailNode=node;
   if(!node||!last.selected)return;
   const p=last.all.find(x=>x.id===last.selected),g=geography.projects[last.selected];
   if(!p||!g){node.innerHTML='<p>Ubicación pendiente de verificación.</p>';return;}
   detailMap=mapAt(node);const ps=points(p);fit(detailMap,ps);
   ps.forEach((pt,i)=>L.circleMarker([pt.lat,pt.lon],{radius:9,color:color(p),weight:3,fillColor:'#fff',fillOpacity:1}).bindTooltip(`${i+1}. ${esc(pt.label)}`,{direction:'top'}).bindPopup(`<b>${esc(pt.label)}</b><p>Referencia aproximada; no es una coordenada de instalación.</p>`).addTo(detailMap));
   root.querySelector('#infraProjectPlaces').innerHTML=ps.map((pt,i)=>`<li>${i+1}. ${esc(pt.label)}</li>`).join('');
   root.querySelector('#infraProjectMapSources').innerHTML=documentView(p,g);
 }
 function update(){
   if(!last||!geography)return;
   if(!window.L){root.querySelector('#infraMapError').textContent='No se pudo iniciar el mapa. El listado y las fichas siguen disponibles.';return;}
   if(!root.classList.contains('active'))return;
   const container=root.querySelector('#infraArgentinaMap');
   if(container&&!overview){const m=mapAt(container);overview={map:m,layers:L.layerGroup().addTo(m)};m.on('zoomend',drawOverview);}
   if(overview){overview.map.invalidateSize();if(active&&!last.projects.some(p=>p.id===active))active=null;sidebar();drawOverview();}
   renderDetail();
   const error=root.querySelector('#infraMapError');if(error)error.textContent=baseError?'Cartografía de referencia no disponible. Podés seguir utilizando los puntos y el listado.':'';
 }
 const schedule=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(update);};
 window.addEventListener('gasdata:infrastructure',e=>{last=e.detail;schedule();});
 new MutationObserver(schedule).observe(root,{attributes:true,attributeFilter:['class']});
 root.addEventListener('click',e=>{
   const locate=e.target.closest('[data-infra-locate]');if(locate){focus(locate.dataset.infraLocate);return;}
   if(e.target.closest('#infraMapReset')&&overview){active=null;overview.map.fitBounds(allBounds,{padding:[18,18]});root.querySelector('#infraMapSelection').innerHTML='<span>Elegí un punto o un proyecto para explorar su ubicación.</span>';drawOverview();}
   const view=e.target.closest('[data-infra-map-view]');if(view){const shown=view.dataset.infraMapView==='map';root.querySelector('#infraMapExplorer').hidden=!shown;root.querySelectorAll('[data-infra-map-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===view)));schedule();}
 });
 async function init(){
   try{
     const response=await fetch('data/infrastructure-geography.json?v=20261015-01');if(!response.ok)throw Error('HTTP '+response.status);geography=await response.json();
     if(geography.meta?.schemaVersion!==1)throw Error('Formato cartográfico desconocido');
     try{const res=await fetch('data/infrastructure-basemap.geojson');if(!res.ok)throw Error();basemap=await res.json();}catch{baseError=true;}
     schedule();
   }catch(error){root.querySelector('#infraMapError').textContent='No se pudo cargar el mapa. El listado y las fichas siguen disponibles.';}
 }
 init();
})();
