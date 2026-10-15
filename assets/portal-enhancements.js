/* Relevant changes, project subscriptions, comparable facts and data freshness. */
(() => {
 'use strict';
 const $=s=>document.querySelector(s),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const safe=u=>/^https?:\/\//i.test(u||'')?esc(u):'#';
 const ALERT_STORE='gasdata-alerts-v1',COMPARE_STORE='gasdata-project-compare-v1';
 let records=portalRead(ALERT_STORE,{version:1,initialized:false,baseline:{},events:{}}),chosen=portalRead(COMPARE_STORE,[]),infra=null,data=null,kind='all',view='pending',limit=4,writeWarning='',processing=false;
 if(records.version!==1||!records.events||!records.baseline)records={version:1,initialized:false,baseline:{},events:{}};
 if(!Array.isArray(chosen))chosen=[];
 const fullTime=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(v)&&Number.isFinite(Date.parse(v))?Date.parse(v):null;
 const fmt=v=>{if(typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v))return v.split('-').reverse().join('/');const t=fullTime(v);return t===null?(v||'No disponible'):new Intl.DateTimeFormat('es-AR',{dateStyle:'short',...(String(v).includes('T')?{timeStyle:'short'}:{}),timeZone:'America/Argentina/Buenos_Aires'}).format(new Date(t));};
 const stamp=()=>new Date().toISOString();
 const hash=s=>{let n=2166136261;for(let i=0;i<s.length;i++){n^=s.charCodeAt(i);n=Math.imul(n,16777619);}return(n>>>0).toString(36);};
 const serialize=x=>JSON.stringify(x);
 const watched=id=>!!portalSaved['project|'+id];
 const project=id=>infra?.projects.find(p=>p.id===id);
 const projectUrl=id=>new URL('#infra/'+id,location.href).href;
 const baseText=p=>String(p||'').replace(/^[CE]:\s*/,'');
 function persist(){if(!portalWrite(ALERT_STORE,records))writeWarning='No se pudieron guardar las alertas en este navegador.';}
 function add(id,event){if(records.events[id])return false;records.events[id]={id,detectedAt:stamp(),readAt:null,...event};return true;}
 function followRecord(p){return portalRecord('project',{id:p.id,title:p.name,source:p.company,desc:p.verifiedStatus+' · '+p.provinces.join(' / '),url:projectUrl(p.id)});}
 function syncProjectButtons(){
   document.querySelectorAll('[data-project-follow]').forEach(b=>{const yes=watched(b.dataset.projectFollow);b.textContent=yes?'★ Siguiendo obra':'☆ Seguir obra';b.setAttribute('aria-pressed',String(yes));b.classList.toggle('following',yes);});
   document.querySelectorAll('[data-project-compare]').forEach(b=>b.checked=chosen.includes(b.dataset.projectCompare));
 }
 function refreshProjects(){
   if(!infra)return;let changed=false;records.projectNewsSeen=records.projectNewsSeen||{};
   infra.projects.forEach(p=>{const r=followRecord(p);portalRegistry.set(r.key,r);});
   for(const [id,n] of Object.entries(infra.news||{})){
     if(!watched(n.projectId)||n.titleType==='inventory_reference')continue;
     const watch=portalSaved['project|'+n.projectId],detected=fullTime(n.firstDetectedAt||n.detectedAt||n.firstSeenAt),published=fullTime(n.publishedAt),start=fullTime(watch.savedAt)||Date.now();
     if(!((detected!==null&&detected>=start)||(published!==null&&published>=start-72*3600000)))continue;
     const p=project(n.projectId);if(!p)continue;
     const r=portalRecord('projectNews',{id,projectId:p.id,title:n.title,source:n.source,desc:p.name+' · '+n.summary,publishedAt:n.publishedAt,url:n.url});portalRegistry.set(r.key,r);
     const seenKey=p.id+'|'+id;if(records.projectNewsSeen[seenKey]===watch.savedAt)continue;records.projectNewsSeen[seenKey]=watch.savedAt;
     if(!portalSaved[r.key]){let {original,...snapshot}=r;portalSaved[r.key]={...snapshot,status:'pending',note:'',savedAt:stamp()};changed=true;}
     add('project-news|'+p.id+'|'+id,{kind:'project',projectId:p.id,title:'Nueva noticia · '+p.name,description:n.title,source:n.source,url:n.url,sourceDate:n.publishedAt||null,followKey:r.key});
   }
   if(changed){portalWrite(PORTAL_STORE,portalSaved);renderFollowing();}
 }
 function signatureRecord(key,values,event){return {key,sig:serialize(values),summary:event.description,event};}
 function catalog(){
   if(!data)return [];
   let rows=[];
   (data.regulations||[]).forEach(r=>rows.push(signatureRecord('reg|'+(r.url||r.num),[r.num,r.title,r.disposition,r.publishedAt],{kind:'regulation',title:'Normativa · '+(r.num||r.title),description:r.disposition||r.title||'Nueva publicación incorporada.',source:r.issuer||r.source||'Normativa legal',url:r.url,sourceDate:r.publishedAt})));
   const tariffRows=[...new Map([...(data.tariffArchive||[]),...(data.tariffs||[])].map(r=>[(r.documentUrl||r.url||r.name+'|'+r.product),r])).values()];
   tariffRows.forEach(r=>rows.push(signatureRecord('tariff|'+(r.documentUrl||r.url||r.name+'|'+r.product),[r.name,r.product,r.res,r.validFrom,r.validTo,r.documentUrl],{kind:'tariff',title:'Cuadro tarifario · '+r.name+' · '+r.product,description:'Resolución '+(r.res||'no informada')+' · vigencia desde '+fmt(r.validFrom)+(r.validTo?' hasta '+fmt(r.validTo):'')+'. '+(r.scope||''),source:r.primarySource||'ENARGAS / ENReGE',url:r.documentUrl||r.url,sourceDate:r.validFrom})));
   (data.transportCapacity||[]).forEach(r=>rows.push(signatureRecord('contest|'+r.id,[r.title,r.status,r.deadlineAt,r.volume,r.period],{kind:'contest',title:'Concurso / capacidad · '+r.title,description:[r.company,r.status,r.volume,r.deadlineAt?'Cierre: '+fmt(r.deadlineAt):'Cierre no confirmado'].filter(Boolean).join(' · '),source:r.source,url:r.url,sourceDate:r.publishedAt})));
   if(infra)infra.projects.filter(p=>watched(p.id)).forEach(p=>rows.push(signatureRecord('project|'+p.id,[p.verifiedStatus,p.stage,p.progress,p.investment,p.dates,p.facts.filter(x=>['capacidad','diametro','longitud'].includes(x.key)).map(x=>x.value)],{kind:'project',projectId:p.id,title:'Estado verificado · '+p.name,description:p.verifiedStatus+' · '+p.stage,source:p.company,url:projectUrl(p.id),sourceDate:p.lastDocumentedAt})));
   return rows;
 }
 function process(){
   if(processing||!data)return;processing=true;
   try{
     refreshProjects();const now=Date.now();
     for(const row of catalog()){
       const previous=records.baseline[row.key],recent=fullTime(row.event.sourceDate);
       // Initial inventory is a baseline, not hundreds of notifications about old publications.
       if(previous&&previous.sig!==row.sig)add(row.key+'|'+hash(row.sig),{...row.event,title:'Cambio detectado · '+row.event.title,description:'Antes: '+previous.summary.slice(0,180)+' Ahora: '+row.event.description.slice(0,220)});
       else if(!previous&&((records.initialized&&row.event.kind!=='project')||(recent!==null&&recent>=now-72*3600000)))add(row.key+'|'+hash(row.sig),{...row.event,title:'Incorporado · '+row.event.title});
       records.baseline[row.key]={sig:row.sig,summary:row.summary};
     }
     const contests=new Map((data.transportCapacity||[]).map(r=>[r.id,r]));
     for(const e of Object.values(records.events)){
       if(e.deadlineAt){const current=contests.get(e.contestId);if((fullTime(e.deadlineAt)||0)<=now||(current&&(/CERRAD|DESIERT|CANCELAD|VENCID/i.test(current.status||'')||current.deadlineAt!==e.deadlineAt)))e.obsolete=true;}
       if(infra&&e.id.startsWith('candidate|')){const candidate=infra.candidates?.[e.id.slice('candidate|'.length)];if(!candidate||candidate.status!=='pending')e.obsolete=true;}
     }
     for(const r of data.transportCapacity||[]){
       const end=fullTime(r.deadlineAt),days=end===null?null:(end-now)/86400000;
       if(days===null||days<0||days>7||/CERRAD|DESIERT|CANCELAD|VENCID/i.test(r.status||''))continue;
       const bucket=days<=1?'24h':days<=3?'3d':'7d',id='deadline|'+r.id+'|'+r.deadlineAt+'|'+bucket;
       Object.values(records.events).filter(e=>e.contestId===r.id&&e.id!==id).forEach(e=>e.obsolete=true);
       add(id,{kind:'contest',contestId:r.id,priority:days<=1?'urgent':'notice',title:(days<=1?'Vence en menos de 24 horas · ':'Próximo vencimiento · ')+r.title,description:(r.deadlineLabel||'Cierre')+': '+fmt(r.deadlineAt)+'. '+(r.volume||''),source:r.source,url:r.url,sourceDate:r.publishedAt,deadlineAt:r.deadlineAt});
     }
     if(infra)for(const [id,c] of Object.entries(infra.candidates||{})){
       if(c.status!=='pending'||!watched(c.projectId))continue;const p=project(c.projectId);if(!p)continue;
       add('candidate|'+id,{kind:'project',projectId:p.id,title:'Posible actualización · '+p.name,description:(c.kind==='progress'?'Avance publicado a verificar: '+c.proposal+' %':c.proposal)+'. '+(c.scope||'Requiere validar alcance')+'. No modifica el estado verificado.',source:c.sourceType==='official'?'Fuente oficial / empresa':'Medio periodístico',url:c.sourceUrl,sourceDate:c.sourceDate});
     }
     records.initialized=true;persist();renderAlerts();renderFreshness();renderProjectComparison();syncProjectButtons();
   }finally{processing=false;}
 }
 function read(e){return !!e.readAt||(e.followKey&&portalSaved[e.followKey]?.status==='read');}
 function renderAlerts(){
   const node=$('#gasdataAlerts');if(!node)return;
   const all=Object.values(records.events).filter(e=>!e.obsolete),pending=all.filter(e=>!read(e)),filtered=all.filter(e=>(kind==='all'||e.kind===kind)&&(view==='all'||(view==='read'?read(e):!read(e)))).sort((a,b)=>(a.priority==='urgent'?0:1)-(b.priority==='urgent'?0:1)||b.detectedAt.localeCompare(a.detectedAt));
   const labels={regulation:'Normativa',tariff:'Tarifas',contest:'Concursos',project:'Obras seguidas'};
   const oldKind=$('#gdAlertKind')?.value,oldView=$('#gdAlertView')?.value;
   node.innerHTML=`<div class="gd-panel-heading"><div><span class="gd-kicker">LO QUE REQUIERE TU ATENCIÓN</span><h2>Alertas relevantes <span class="gd-counter">${pending.length}</span></h2><p>Normativa, cuadros tarifarios, vencimientos y novedades de las obras que seguís.</p></div><button type="button" id="gdAlertsReadAll" ${!pending.length?'disabled':''}>Marcar todas como vistas</button></div><div class="gd-alert-controls"><label>Contenido<select id="gdAlertKind"><option value="all">Todo</option>${Object.entries(labels).map(([k,v])=>`<option value="${k}" ${kind===k?'selected':''}>${v}</option>`).join('')}</select></label><label>Lectura<select id="gdAlertView"><option value="pending" ${view==='pending'?'selected':''}>Pendientes</option><option value="read" ${view==='read'?'selected':''}>Vistas</option><option value="all" ${view==='all'?'selected':''}>Todas</option></select></label><span>${filtered.length} alertas en esta vista · guardadas en este navegador</span></div><div class="gd-alert-grid">${filtered.slice(0,limit).map(e=>`<article class="gd-alert-card ${e.priority==='urgent'?'urgent':''}"><div class="gd-alert-meta"><span>${esc(labels[e.kind])}</span><time>Detectada: ${esc(fmt(e.detectedAt))}</time></div><h3>${esc(e.title)}</h3><p>${esc(e.description.length>440?e.description.slice(0,437)+'…':e.description)}</p><small>${esc(e.source||'Fuente original')} · ${e.kind==='tariff'?'Vigencia':'Publicación'}: ${esc(fmt(e.sourceDate))}</small><div class="gd-alert-actions">${e.projectId?`<button type="button" data-gd-open-project="${esc(e.projectId)}">Ver obra →</button>`:''}<a href="${safe(e.url)}" target="_blank" rel="noopener noreferrer">Abrir fuente ↗</a><button type="button" data-gd-alert-read="${esc(e.id)}">${read(e)?'Marcar pendiente':'Marcar vista'}</button></div></article>`).join('')||`<p class="gd-empty">${view==='pending'?'No hay alertas pendientes. Las nuevas detecciones aparecerán aquí automáticamente.':'No hay alertas para estos filtros.'}</p>`}</div>${filtered.length>limit?'<button type="button" id="gdAlertsMore">Mostrar más</button>':''}<p class="gd-storage-note" role="status">${esc(writeWarning||portalStorageWarning||'El seguimiento empieza en este navegador. Las obras se siguen desde su mapa, listado o ficha; las alertas no se envían por correo.')}</p>`;
 }
 function healthRows(){
   if(!data)return [];
   const updates=data.updates||[],update=n=>updates.find(x=>x.name===n)||{},max=xs=>xs.filter(Boolean).sort().at(-1)||null,rows=[];
   for(const s of data.newsSources||[])rows.push({group:'Noticias',name:s.name,attempt:s.checkedAt,success:s.status==='ok'?s.checkedAt:s.lastSuccessAt,period:max((data.news||[]).filter(n=>n.source===s.name&&n.dateType!=='unknown'&&n.dateType!=='detected').map(n=>n.publishedAt)),status:s.status==='error'?'error':'',next:update('Noticias').next,cadence:update('Noticias').cadence,url:s.url});
   const reg=update('Normativa'),scan=data.regulationScan||{};
   rows.push({group:'Normativa',name:'Normativa nacional',attempt:scan.lastRun||reg.last,success:scan.lastSuccessfulAt,period:max((data.regulations||[]).filter(r=>r.jurisdiction!=='PBA').map(r=>r.publishedAt)),status:scan.complete===false?'partial':reg.status,next:reg.next,cadence:reg.cadence,url:'https://www.boletinoficial.gob.ar/'});
   const pba=Object.values(data.bopbaScan||{}).filter(x=>x&&typeof x==='object'),pu=update('Boletín Oficial PBA');rows.push({group:'Normativa',name:'Boletín Oficial PBA',attempt:pu.last,success:pba.length&&pba.every(x=>x.complete)?max(pba.map(x=>x.checkedAt)):null,period:max((data.regulations||[]).filter(r=>r.jurisdiction==='PBA').map(r=>r.publishedAt)),status:pu.status,next:pu.next,cadence:pu.cadence,url:'https://boletinoficial.gba.gob.ar/'});
   const tc=data.tariffComparison||{},tu=update('Tarifas ENReGE'),ta=data.tariffAutomation||{};rows.push({group:'Tarifas',name:'Cuadros vigentes oficiales',attempt:max([ta.officialCheckedAt,tu.last]),success:ta.officialCheckedAt||null,period:max((data.tariffs||[]).map(x=>x.validFrom)),status:tu.status,next:tu.next,cadence:tu.cadence,url:ta.primarySourceUrl});rows.push({group:'Tarifas',name:'Comparador · Excel y anexos PDF',attempt:tc.checkedAt,success:tc.checkedAt&&!(tc.errors||[]).length&&tc.status!=='error'?tc.checkedAt:null,period:max((tc.datasets||[]).map(x=>x.period||x.month)),status:(tc.errors||[]).length?'partial':tc.status||tu.status,next:tu.next,cadence:tc.cadence||tu.cadence,url:'https://www.enargas.gob.ar/secciones/precios-y-tarifas/cuadros-tarifarios.php'});
   for(const [key,title,un] of [['basinMonthlyMeta','Producción por cuenca/provincia','Producción por cuenca/provincia'],['systemMonthlyMeta','Importaciones y exportaciones','Flujos mensuales']]){const m=data[key]||{},u=update(un);rows.push({group:'Mercado',name:title,attempt:max([m.checkedAt,u.last]),success:m.validatedAt||(['current','updated','unchanged'].includes(m.status)&&!m.error?m.checkedAt:null),period:m.latest,status:m.error?'error':u.status,next:u.next,cadence:u.cadence,url:m.sourceUrl||m.officialUrl});}
   for(const m of data.marketPrices||[])rows.push({group:'Mercado',name:m.label,attempt:m.checkedAt||m.validatedAt,success:m.validatedAt,period:m.reference,status:m.supplemental||m.updateStatus==='reference'?'historical':m.updateStatus,next:m.nextValidation,cadence:'Según la serie original',url:m.sourceUrl});
   const cu=update('Capacidad de transporte'),cm=data.transportCapacityMeta||{};rows.push({group:'Concursos',name:'Concursos y reventas de capacidad',attempt:cm.validatedAt||cu.last,success:null,period:max((data.transportCapacity||[]).map(x=>x.publishedAt)),status:cu.status,next:cu.next,cadence:cm.cadence||cu.cadence,url:'https://www.enargas.gob.ar/secciones/transporte-y-distribucion/concursos-reventas.php',note:'La base registra la consulta; no discrimina éxito por fuente. Los plazos vencidos no generan alertas.'});
   if(infra)rows.push({group:'Infraestructura',name:'Documentación de proyectos',attempt:infra.meta.generatedAt,success:infra.meta.officialLastSuccessAt,period:infra.meta.inventoryVerifiedAt,status:infra.meta.officialErrors?'partial':'ok',cadence:infra.meta.officialFrequency,url:null,note:'Última exitosa corresponde a alguna fuente oficial; no a cobertura completa. '+(infra.meta.officialErrors||0)+' fuentes con consulta fallida.'});
   return rows;
 }
 function healthStatus(r){
   if(r.status==='historical')return ['reference','Referencia histórica'];
   if(['error','partial','pending'].includes(r.status))return ['warn','Consulta parcial / dato conservado'];
   const due=fullTime(r.next);if(due!==null&&Date.now()>due+2*3600000)return ['warn','Consulta pendiente de renovación'];
   if(!r.success)return ['unknown','Éxito no confirmado'];
   return ['ok','Consulta registrada'];
 }
 function renderFreshness(){
   const rows=healthRows(),body=$('#gasdataFreshnessBody');if(!body)return;
   const issues=rows.filter(r=>healthStatus(r)[0]==='warn').length;
   $('#gasdataFreshness>summary').textContent='Vigencia de datos y consultas'+(issues?' · '+issues+' para revisar':'');
   body.innerHTML=`<p>Consultar hoy no significa que el dato corresponda a hoy. Se muestran por separado la consulta, el último éxito que la base permite confirmar y el período publicado. “No disponible” no se interpreta como cero ni como fuente actualizada.</p><div class="gd-health-scroll"><table><thead><tr><th>Dato / fuente</th><th>Última consulta</th><th>Última exitosa confirmada</th><th>Fecha / período del dato</th><th>Situación</th></tr></thead><tbody>${rows.map(r=>{const [cls,label]=healthStatus(r);return `<tr><td><b>${esc(r.name)}</b><small>${esc(r.group+' · '+(r.cadence||'Frecuencia no informada'))}</small>${r.url?`<a href="${safe(r.url)}" target="_blank" rel="noopener noreferrer">Fuente ↗</a>`:''}</td><td>${esc(fmt(r.attempt))}</td><td>${esc(fmt(r.success))}</td><td>${esc(fmt(r.period))}</td><td><span class="gd-health ${cls}">${label}</span>${r.note?`<small>${esc(r.note)}</small>`:''}</td></tr>`;}).join('')}</tbody></table></div>`;
   for(const [id,group,anchor] of [['tarifas','Tarifas','#tariffDocuments'],['normativa','Normativa','#normativa'],['mercado','Mercado','#mercado'],['infraestructura','Infraestructura','#infraestructura']]){
     let el=$('#gdHealth-'+id);if(!el){el=document.createElement('div');el.id='gdHealth-'+id;el.className='gd-inline-health';$(anchor)?.prepend(el);}
     const subset=rows.filter(r=>r.group===group),warnings=subset.filter(r=>healthStatus(r)[0]==='warn').length;
     el.innerHTML=`<span class="gd-health ${warnings?'warn':'unknown'}">${warnings?'Hay consultas para revisar':'Fecha de consulta ≠ período publicado'}</span> <button type="button" data-gd-health-open>Ver vigencia y fuentes →</button>`;
   }
 }
 function investment(p){const v=p.investment||{},nf=new Intl.NumberFormat('es-AR',{maximumFractionDigits:2});return v.minimum==null?'No disponible':v.currency+' '+nf.format(v.minimum)+(v.maximum!=null&&v.maximum!==v.minimum?'–'+nf.format(v.maximum):'')+' millones'+(v.condition?' · '+baseText(v.condition):'');}
 function renderProjectComparison(){
   if(!infra)return;chosen=chosen.filter(id=>project(id)).slice(0,3);const controls=$('#gdCompareControls'),table=$('#gdCompareTable');if(!controls)return;
   $('#gdCompareCount').textContent=chosen.length+' de 3';
   controls.innerHTML=`<p>Elegí dos o tres obras. También podés marcarlas en el listado. Las selecciones se conservan al cambiar filtros.</p><div class="gd-compare-selects">${[0,1,2].map(i=>`<label>Proyecto ${i+1}<select data-gd-compare-slot="${i}"><option value="">Seleccionar…</option>${infra.projects.map(p=>`<option value="${p.id}" ${chosen[i]===p.id?'selected':''}>${esc(p.id+' · '+p.name)}</option>`).join('')}</select></label>`).join('')}<button type="button" id="gdCompareClear">Limpiar</button></div><p class="gd-storage-note" id="gdCompareMessage">${esc(portalStorageWarning)}</p>`;
   const ps=chosen.map(project);if(ps.length<2){table.innerHTML='<p class="gd-empty">Seleccioná al menos dos proyectos para comparar.</p>';syncProjectButtons();return;}
   const fact=(p,key)=>{const f=p.facts.find(x=>x.key===key);return !f||f.value==='ND'?'No disponible':baseText(f.value)+(f.certainty==='estimated'?' · estimado / proyectado':'');};
   const fields=[['Estado verificado',p=>p.verifiedStatus],['Etapa',p=>p.stage],['Empresa / titular',p=>p.company],['Provincias',p=>p.provinces.join(' / ')],['Recorrido',p=>fact(p,'recorrido')],['Diámetro',p=>fact(p,'diametro')],['Longitud',p=>fact(p,'longitud')],['Capacidad',p=>fact(p,'capacidad')],['Inversión publicada',investment],['Alcance de la inversión',p=>baseText(p.investment.scope)||'No disponible'],['Inicio real',p=>fmt(baseText(p.dates.inicio_real))],['Finalización real',p=>fmt(baseText(p.dates.fin_real))],['Finalización estimada',p=>fmt(baseText(p.dates.fin_estimado))],['Avance físico publicado',p=>p.progress?(p.progress.approximate?'≈ ':'')+String(p.progress.value)+' % · '+fmt(baseText(p.progress.date))+' · '+baseText(p.progress.scope):'Sin porcentaje informado'],['Última verificación',p=>fmt(p.verifiedAt)]];
   const clean=v=>v==='ND'||!v?'No disponible':v;
   table.innerHTML=`<div class="gd-compare-table-scroll"><table><thead><tr><th>Concepto</th>${ps.map(p=>`<th><span>${esc(p.id)}</span><button type="button" data-gd-open-project="${p.id}">${esc(p.name)} →</button></th>`).join('')}</tr></thead><tbody>${fields.map(([name,fn])=>`<tr><th>${name}</th>${ps.map(p=>`<td>${esc(clean(fn(p)))}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="gd-compare-caution">Las inversiones pueden incluir alcances y horizontes distintos; no se suman ni se comparan como costos equivalentes. Las capacidades mantienen la unidad y el alcance publicados. No se calcula avance físico a partir de etapas.</p>`;syncProjectButtons();
 }
 function selectCompare(id,on){
   if(on&&!chosen.includes(id)){if(chosen.length>=3){const note=$('#gdCompareMessage');note.textContent='Podés comparar hasta tres proyectos. Quitá uno para agregar otro.';$('#gdProjectCompare').open=true;syncProjectButtons();return;}chosen.push(id);}else if(!on)chosen=chosen.filter(x=>x!==id);
   portalWrite(COMPARE_STORE,chosen);renderProjectComparison();
 }
 document.addEventListener('click',e=>{
   const follow=e.target.closest('[data-project-follow]');if(follow){const id=follow.dataset.projectFollow,p=project(id);if(!p)return;
     if(watched(id)){delete portalSaved['project|'+id];portalWrite(PORTAL_STORE,portalSaved);renderFollowing();}
     else {const r=followRecord(p);portalRegistry.set(r.key,r);portalSave(r.key);}
     process();return;
   }
   const open=e.target.closest('[data-gd-open-project]');if(open){page('infraestructura');window.GasDataInfrastructure?.open(open.dataset.gdOpenProject);return;}
   const ack=e.target.closest('[data-gd-alert-read]');if(ack){const event=records.events[ack.dataset.gdAlertRead];if(event){const was=read(event);event.readAt=was?null:stamp();if(event.followKey&&portalSaved[event.followKey]){portalSaved[event.followKey].status=was?'pending':'read';portalWrite(PORTAL_STORE,portalSaved);renderFollowing();}persist();renderAlerts();}return;}
   if(e.target.closest('#gdAlertsReadAll')){Object.values(records.events).forEach(e=>{e.readAt=stamp();if(e.followKey&&portalSaved[e.followKey])portalSaved[e.followKey].status='read';});portalWrite(PORTAL_STORE,portalSaved);persist();renderFollowing();renderAlerts();}
   if(e.target.closest('#gdAlertsMore')){limit+=12;renderAlerts();}
   if(e.target.closest('#gdCompareClear')){chosen=[];portalWrite(COMPARE_STORE,chosen);renderProjectComparison();}
   if(e.target.closest('[data-gd-health-open]')){page('inicio');$('#gasdataFreshness').open=true;$('#gasdataFreshness').scrollIntoView({block:'center',behavior:'smooth'});}
   queueMicrotask(syncProjectButtons);
 });
 document.addEventListener('change',e=>{
   if(e.target.id==='gdAlertKind'){kind=e.target.value;limit=4;renderAlerts();}
   if(e.target.id==='gdAlertView'){view=e.target.value;limit=4;renderAlerts();}
   if(e.target.dataset.projectCompare)selectCompare(e.target.dataset.projectCompare,e.target.checked);
   if(e.target.dataset.gdCompareSlot!==undefined){const i=Number(e.target.dataset.gdCompareSlot),id=e.target.value;if(id&&chosen.includes(id)&&chosen[i]!==id){e.target.value=chosen[i]||'';$('#gdCompareMessage').textContent='Elegí proyectos diferentes.';return;}const slots=[...chosen];slots[i]=id;chosen=slots.filter(Boolean);portalWrite(COMPARE_STORE,chosen);renderProjectComparison();}
 });
 window.addEventListener('gasdata:updated',e=>{data=e.detail;process();});
 window.addEventListener('gasdata:infrastructure',e=>{infra={...window.GasDataInfrastructure?.getData(),projects:e.detail.all};process();});
 window.addEventListener('gasdata:following',()=>{syncProjectButtons();if(!processing)renderAlerts();});
 setInterval(()=>{if(!document.hidden)process();},60000);
 if(typeof D!=='undefined'&&D.meta){data=D;process();}
 window.GasDataEnhancements={process,healthRows,healthStatus,fullTime,hash,getAlerts:()=>records,getChosen:()=>chosen,refreshProjects};
})();
