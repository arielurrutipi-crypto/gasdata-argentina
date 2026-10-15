/* Verified project facts and automatically detected signals remain separate. */
(() => {
 'use strict';
 const root=document.getElementById('infraestructura');if(!root)return;
 const stages=['Anunciado','Ingeniería','Licitación','Adjudicado','Construcción','Puesta en marcha','Operativo'];
 const state={data:null,selected:null,loading:false,payload:'',filters:{}};
 const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const strip=v=>String(v??'').replace(/^[CE]:\s*/,'');
 const text=v=>!v||v==='ND'?'No disponible':strip(v);
 const normalize=v=>String(v??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
 const url=v=>/^https?:\/\//i.test(v||'')?escape(v):'#';
 const nf=new Intl.NumberFormat('es-AR',{minimumFractionDigits:2,maximumFractionDigits:2});
 const date=v=>{
   if(!v)return 'Fecha no disponible';
   if(/^\d{4}$/.test(v))return v+' · sin mes/día';
   if(/^\d{4}-\d{2}$/.test(v))return v.slice(5)+'/'+v.slice(0,4)+' · sin día';
   if(/^\d{4}-\d{2}-\d{2}$/.test(v))return v.split('-').reverse().join('/');
   if(/^\d{4}-\d{2}-\d{2}T/.test(v)&&!isNaN(Date.parse(v)))return new Intl.DateTimeFormat('es-AR',{dateStyle:'short',timeZone:'America/Argentina/Buenos_Aires'}).format(new Date(v));
   return strip(v);
 };
 const sources=()=>new Map((state.data?.sources||[]).map(s=>[s.id,s]));
 const candidates=p=>Object.values(state.data?.candidates||{}).filter(c=>c.projectId===p.id&&c.status==='pending');
 const archived=p=>Object.values(state.data?.news||{}).filter(n=>n.projectId===p.id).sort((a,b)=>(b.publishedAt||'').localeCompare(a.publishedAt||''));
 const sourceLink=(s,label)=>s?`<a href="${url(s.url)}" target="_blank" rel="noopener noreferrer">${escape(label||s.title)} ↗</a>`:'';
 const investment=p=>{
   let m=p.investment||{};if(m.minimum==null)return 'Inversión no disponible';
   let relation=/superior|mayor/i.test(m.condition)?'> ':'';
   return `${relation}${escape(m.currency)} ${nf.format(m.minimum)}${m.maximum!=null&&m.maximum!==m.minimum?'–'+nf.format(m.maximum):''} millones`;
 };
 const evidenceLabel=q=>q==='estimated'?'Estimado / proyectado':q==='unknown'?'No disponible':'Confirmado documentalmente';
 function stageView(p,compact=false){
   const current=stages.indexOf(p.stage);
   return `<div class="infra-stage${compact?' compact':''}"><div class="infra-stage-label">Etapa: <b>${escape(p.stage)}</b></div><ol aria-label="Etapa actual del proyecto; no representa avance físico">${stages.map((s,i)=>`<li class="${i===current?'current':''}" title="${escape(s)}" ${i===current?'aria-current="step"':''}><span></span>${compact?'':escape(s)}</li>`).join('')}</ol><small>Indicador de etapas · no es un porcentaje físico</small></div>`;
 }
 function progressView(p){
   const v=p.progress;if(!v||!Number.isFinite(v.value))return '';
   return `<div class="infra-progress"><b>Avance informado: ${v.approximate?'≈ ':''}${nf.format(v.value)} %</b><span>Dato publicado: ${escape(date(v.date))}</span><small>${escape(strip(v.scope))} · no se extrapola a hoy</small><a href="${url(v.sourceUrl)}" target="_blank" rel="noopener noreferrer">Fuente del avance ↗</a></div>`;
 }
 const companyOptions=()=>{
   const known=['ENARSA','TGS','TGN','YPF','Pluspetrol','TotalEnergies','Harbour','PAE','Southern Energy','San Matías Pipeline','Litoralgas','ENERFE','Camuzzi','Oldelval','VMOS','Tecpetrol','GyP','Pampa','AXION','OTAMERICA','Oiltanking'];
   return known.filter(c=>state.data.projects.some(p=>normalize(p.company+' '+p.facts.filter(f=>['operador','empresas'].includes(f.key)).map(f=>f.value).join(' ')).includes(normalize(c))));
 };
 const filterSpecs=()=>[
   ['status','Estado',stages.concat('Por verificar','Suspendido','Cancelado')],
   ['type','Tipo de infraestructura',[...new Set(state.data.projects.map(p=>p.category))].sort()],
   ['company','Empresa',companyOptions()],
   ['province','Provincia',[...new Set(state.data.projects.flatMap(p=>p.provinces))].sort()],
   ['year','Año / horizonte',[...new Set(state.data.projects.flatMap(p=>p.years))].sort().reverse()],
   ['product','Energía',['Gas','Petróleo / líquidos','GNL']],
   ['phase','Situación',['Ejecutado','En ejecución','Proyectado']]
 ];
 function filters(){
   const node=root.querySelector('#infraFilters');
   node.innerHTML=`<label class="infra-search">Buscar<input id="infraSearch" type="search" placeholder="Proyecto, recorrido, empresa…" value="${escape(state.filters.search||'')}"></label>`+filterSpecs().map(([id,label,values])=>`<label>${label}<select data-infra-filter="${id}"><option value="">Todos</option>${values.map(v=>`<option value="${escape(v)}" ${state.filters[id]===v?'selected':''}>${escape(v)}</option>`).join('')}</select></label>`).join('')+`<button type="button" id="infraClear">Limpiar filtros</button>`;
 }
 function visible(p){
   const f=state.filters;
   if(f.search&&!normalize(p.name+' '+p.company+' '+p.facts.map(x=>x.value).join(' ')).includes(normalize(f.search)))return false;
   if(f.status&&p.stage!==f.status)return false;
   if(f.type&&p.category!==f.type)return false;
   if(f.company&&!normalize(p.company+' '+p.facts.filter(x=>['operador','empresas'].includes(x.key)).map(x=>x.value).join(' ')).includes(normalize(f.company)))return false;
   if(f.province&&!p.provinces.includes(f.province))return false;
   if(f.year&&!p.years.includes(f.year))return false;
   if(f.product&&!p.products.includes(f.product))return false;
   if(f.phase&&p.phase!==f.phase)return false;
   return true;
 }
 function notifyMaps(){queueMicrotask(()=>window.dispatchEvent(new CustomEvent("gasdata:infrastructure",{detail:{projects:state.data.projects.filter(visible),all:state.data.projects,selected:state.selected}})));}
 function list(){
   if(!state.data)return;
   const all=state.data.projects,rows=all.filter(visible);
   root.querySelector('#infraCount').textContent=`${rows.length} de ${all.length} proyectos / etapas`;
   root.querySelector('#infraOverview').innerHTML=rows.length?rows.map(p=>`<article class="infra-row"><div><span class="infra-id">${escape(p.id)} · ${escape(p.category)}</span><button type="button" class="infra-project-name" data-infra-open="${escape(p.id)}">${escape(p.name)}</button><p>${escape(p.provinces.join(' · '))}</p><span class="infra-pill">${escape(p.phase)}</span>${p.reviewContinuity?'<span class="infra-pill warn">Continuidad por verificar</span>':''}${candidates(p).length?`<span class="infra-pill warn">${candidates(p).length} posibles cambios</span>`:''}</div><div class="infra-verified"><span>Estado verificado</span><b>${escape(p.verifiedStatus)}</b><small>Comprobación documental: ${escape(date(p.verifiedAt))}</small></div><div class="infra-finance"><b>${investment(p)}</b><small>${escape(text(p.investment.scope))}</small><p>${escape(text(p.dates.fin_estimado!=='ND'?p.dates.fin_estimado:p.dates.fin_real))}</p><small>${escape(p.company)}</small></div><div>${stageView(p,true)}${progressView(p)}</div><button type="button" class="infra-open" data-infra-open="${escape(p.id)}" aria-label="Abrir ficha ${escape(p.name)}">Ver ficha →</button></article>`).join(''):'<div class="empty">No hay proyectos que coincidan con estos filtros.</div>';
   notifyMaps();
 }
 function detail(){
   const p=state.data?.projects.find(x=>x.id===state.selected);if(!p){state.selected=null;return;}
   const sm=sources(),pending=candidates(p),news=archived(p);
   const facts=group=>p.facts.filter(f=>group.includes(f.key)).map(f=>`<div class="infra-fact"><dt>${escape(f.label)} <span class="infra-quality ${f.certainty}">${evidenceLabel(f.certainty)}</span></dt><dd>${escape(text(f.value))}</dd></div>`).join('');
   const hist=[...(p.history||[])].sort((a,b)=>(a.date||'').localeCompare(b.date||''));
   root.querySelector('#infraDetail').innerHTML=`<button type="button" class="infra-back" id="infraBack">← Volver a proyectos</button><div class="infra-detail-heading"><span class="infra-id">${escape(p.id)} · ${escape(p.category)}</span><h2>${escape(p.name)}</h2><p>${escape(p.provinces.join(' · '))}</p></div><div class="infra-detail-main"><div class="infra-project-geography"><h3>Ubicación del proyecto</h3><div id="infraProjectMap" class="infra-project-map" aria-label="Mapa de ubicación de ${escape(p.name)}"></div><p class="infra-tile-status" role="status"></p><p class="infra-map-note">Referencias aproximadas · sin traza de ingeniería.</p><ol id="infraProjectPlaces" class="infra-project-places"></ol></div><div class="infra-state-card"><span>Estado verificado</span><h3>${escape(p.verifiedStatus)}</h3><p>Última verificación documental: ${escape(date(p.verifiedAt))}</p><p>Último hito / documento: ${escape(text(p.lastDocumentedAt))}</p><b>${investment(p)}</b><p>${escape(text(p.investment.condition))} · ${escape(text(p.investment.scope))}</p>${p.investment.sources&&p.investment.sources!=='ND'?`<p>Fuente del monto: ${p.investment.sources.split(/;\s*/).map(id=>sourceLink(sm.get(id),id)).join(' · ')}</p>`:''}${progressView(p)}</div></div>${stageView(p)}<section class="infra-detail-section"><div id="infraProjectMapSources"></div><details class="infra-concept"><summary>Esquema conceptual complementario</summary><figure><img src="${escape(p.image.url)}" alt="Esquema conceptual de ${escape(p.name)}" width="960" height="300"><figcaption>${escape(p.image.credit)}</figcaption></figure></details></section><section class="infra-detail-section"><h3>Posibles actualizaciones detectadas <span class="infra-pill warn">${pending.length}</span></h3><p class="infra-explanation">Se detectan automáticamente. Hasta validar su alcance, no modifican el estado verificado ni el avance del proyecto.</p>${pending.length?pending.sort((a,b)=>(b.detectedAt||'').localeCompare(a.detectedAt||'')).map(c=>`<article class="infra-signal"><b>${escape(c.kind==='progress'?'Posible avance publicado: '+nf.format(c.proposal)+' %':c.proposal)}</b><p>${escape(c.scope||'Revisar documento y alcance del cambio')}</p><small>${c.sourceType==='official'?'Fuente oficial / empresa':'Fuente periodística'} · publicación ${escape(date(c.sourceDate))} · detección ${escape(date(c.detectedAt))}</small><a href="${url(c.sourceUrl)}" target="_blank" rel="noopener noreferrer">Consultar evidencia ↗</a></article>`).join(''):'<p class="infra-muted">No hay cambios pendientes identificados para esta obra. Esto no certifica ausencia de novedades en fuentes que no pudieron consultarse.</p>'}</section><section class="infra-detail-section"><h3>Descripción y participantes</h3><dl class="infra-facts">${facts(['descripcion','recorrido','propietario','operador','empresas','contratistas','anteriores'])}</dl></section><section class="infra-detail-section"><h3>Alcance técnico e instalaciones</h3><dl class="infra-facts">${facts(['instalaciones','ductos','diametro','longitud','capacidad','compresoras','tratamiento','procesamiento','gnl','almacenamiento','terminales','otras'])}</dl></section><section class="infra-detail-section"><h3>Fechas y observaciones</h3><dl class="infra-facts">${facts(['anuncio','inicio_real','inicio_estimado','fin_real','fin_estimado','observaciones','relacion'])}</dl></section><section class="infra-detail-section"><h3>Cronología y documentos</h3><ol class="infra-timeline">${hist.map(h=>`<li><time>${escape(date(h.date))}</time><div>${escape(h.label)}<br><a href="${url(h.sourceUrl)}" target="_blank" rel="noopener noreferrer">Fuente ↗</a></div></li>`).join('')||'<li>Sin hitos fechados disponibles.</li>'}</ol></section><details class="infra-detail-section infra-news" open><summary>Noticias relacionadas <span class="infra-pill">${news.length}</span></summary><p class="infra-explanation">Archivo permanente · más recientes primero · las fechas incompletas y referencias del inventario se identifican expresamente.</p>${news.length?news.map(n=>`<article><div class="infra-news-meta">${escape(date(n.publishedAt))} · ${escape(n.source)}${n.titleType==='inventory_reference'?' · referencia del inventario':''}</div><h4><a href="${url(n.url)}" target="_blank" rel="noopener noreferrer">${escape(n.title)} ↗</a></h4><p>${escape(n.summary)}</p></article>`).join(''):'<p class="infra-muted">Todavía no hay noticias identificadas para este proyecto.</p>'}</details><section class="infra-detail-section"><h3>Fuentes del proyecto</h3><ul class="infra-sources">${[...p.sources,...p.pressSources].map(id=>{const s=sm.get(id);return s?`<li>${sourceLink(s)} <span>${s.type==='official'?'Oficial / corporativa':'Periodística'} · ${escape(date(s.date))}</span>${s.notes?`<p>${escape(s.notes)}</p>`:''}</li>`:''}).join('')}</ul></section>`;
 }
 function meta(){
   const m=state.data.meta||{},checks=Object.values(state.data.sourceChecks||{}),failed=checks.filter(x=>x.status==='error').length;
   root.querySelector('#infraHealth').textContent=`Noticias vinculadas: ${date(m.newsLinkedAt)} · última consulta oficial exitosa: ${date(m.officialLastSuccessAt)}${failed?' · '+failed+' fuentes con consulta fallida':''}`;
   root.querySelector('#infraHealth').classList.toggle('warn',failed>0);
   root.querySelector('#infraTotals').innerHTML=[['Proyectos / etapas',state.data.projects.length],['Operativos',state.data.projects.filter(x=>x.stage==='Operativo').length],['En ejecución',state.data.projects.filter(x=>x.phase==='En ejecución').length],['Posibles cambios',Object.values(state.data.candidates||{}).filter(x=>x.status==='pending').length]].map(([label,n])=>`<div><b>${n}</b><span>${label}</span></div>`).join('');
 }
 function render(){
   if(!state.data)return;
   if(state.selected&&!state.data.projects.some(p=>p.id===state.selected))state.selected=null;
   root.querySelector('#infraListView').hidden=!!state.selected;
   root.querySelector('#infraDetail').hidden=!state.selected;
   meta();filters();list();if(state.selected)detail();
 }
 async function load(){
   if(state.loading)return;state.loading=true;
   const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),20000);
   try{
     const res=await fetch('data/infrastructure.json?ts='+Date.now(),{cache:'no-store',signal:abort.signal});
     if(!res.ok)throw Error('HTTP '+res.status);
     const data=await res.json();
     if(data.meta?.schemaVersion!==1||!Array.isArray(data.projects)||!Array.isArray(data.sources))throw Error('Base incompleta');
     const payload=JSON.stringify(data);
     if(payload!==state.payload){state.data=data;state.payload=payload;render();}
     root.querySelector('#infraLoadError').textContent='';
   }catch(e){root.querySelector('#infraLoadError').textContent=state.data?'No se pudo comprobar una nueva versión. Se conserva el último inventario cargado.':'El inventario aún no se pudo cargar. Se reintentará automáticamente.';console.error('Infraestructura',e.message);}
   finally{clearTimeout(timer);state.loading=false;}
 }
 function open(id){
   if(!state.data?.projects.some(p=>p.id===id))return;
   state.selected=id;render();location.hash='infra/'+id;root.scrollIntoView({behavior:'auto',block:'start'});
 }
 root.addEventListener('click',e=>{
   const button=e.target.closest('[data-infra-open]');if(button){open(button.dataset.infraOpen);return;}
   if(e.target.closest('#infraBack')){state.selected=null;history.replaceState(null,'',location.pathname+location.search);render();}
   if(e.target.closest('#infraClear')){state.filters={};render();}
 });
 root.addEventListener('change',e=>{if(e.target.dataset.infraFilter){state.filters[e.target.dataset.infraFilter]=e.target.value;list();}});
 root.addEventListener('input',e=>{if(e.target.id==='infraSearch'){state.filters.search=e.target.value;list();}});
 const hash=()=>{const id=location.hash.match(/^#infra\/([GP]\d{2})$/)?.[1];if(id){state.selected=id;if(typeof page==='function')page('infraestructura');if(state.data)render();}else if(state.selected){state.selected=null;if(state.data)render();}};
 addEventListener('hashchange',hash);hash();
 setInterval(()=>{if(!document.hidden)load();},60000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
 addEventListener('focus',load);load();
 window.GasDataInfrastructure={load,open,date,visible,getData:()=>state.data};
})();
