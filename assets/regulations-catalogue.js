/* Read the complete saved catalogue; never reuse the thematic regulation filters. */
(() => {
 'use strict';
 const byId=id=>document.getElementById(id);
 if(!byId('legalCatalogueRows'))return;
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const normal=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
 const day=value=>/^\d{4}-\d{2}-\d{2}$/.test(value||'')?value.split('-').reverse().join('/'):'Sin fecha';
 const safeUrl=value=>{try{const u=new URL(value);return /^https?:$/.test(u.protocol)?u.href:null;}catch{return null;}};
 let data=null,pageIndex=0;
 function filtered(){
   const q=normal(byId('legalCatalogueSearch').value).trim(),issuer=byId('legalCatalogueIssuer').value,from=byId('legalCatalogueFrom').value,to=byId('legalCatalogueTo').value;
   if(from&&to&&from>to)return [];
   return (data?.resolutionExport?.rows||[]).filter(r=>(issuer==='all'||normal(r.issuer)===normal(issuer))&&(!from||r.date>=from)&&(!to||r.date<=to)&&(!q||normal([r.num,r.number,r.type,r.desc,r.issuer].join(' ')).includes(q)))
    .slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||''))||String(b.number||b.num).localeCompare(String(a.number||a.num),'es',{numeric:true})||String(a.num).localeCompare(String(b.num),'es'));
 }
 function render(){
   if(!data)return;
   const state=data.resolutionExport||{},rows=filtered(),size=byId('legalCatalogueSize').value==='all'?Math.max(1,rows.length):Number(byId('legalCatalogueSize').value)||50,pages=Math.max(1,Math.ceil(rows.length/size));
   pageIndex=Math.min(pageIndex,pages-1);
   const start=pageIndex*size,shown=rows.slice(start,start+size),invalid=byId('legalCatalogueFrom').value&&byId('legalCatalogueTo').value&&byId('legalCatalogueFrom').value>byId('legalCatalogueTo').value;
   const total=(state.rows||[]).filter(r=>byId('legalCatalogueIssuer').value==='all'||normal(r.issuer)===normal(byId('legalCatalogueIssuer').value)).length;
   byId('legalCatalogueCount').textContent=invalid?'El rango de fechas no es válido.':rows.length+' de '+total+' resoluciones del catálogo disponible · '+(shown.length?'mostrando '+(start+1)+'–'+(start+shown.length):'sin resultados')+' · más recientes primero';
   byId('legalCatalogueRows').innerHTML=shown.map(r=>{
     const url=safeUrl(r.url),catalogue=safeUrl(state.sourceUrl),original=url&&url!==catalogue&&!/\/resoluciones\.php(?:[?#]|$)/i.test(url);
     const access=original?'<a href="'+escape(url)+'" target="_blank" rel="noopener noreferrer" aria-label="'+escape('Abrir resolución original: '+r.num)+'">Original ↗</a>':(catalogue?'<span>Original no disponible</span><a href="'+escape(catalogue)+'" target="_blank" rel="noopener noreferrer">Catálogo ↗</a>':'<span>Original no disponible</span>');
     return '<tr><td><time datetime="'+escape(r.date)+'">'+escape(day(r.date))+'</time></td><th scope="row">'+escape(r.num)+'</th><td class="catalogue-description">'+escape(r.desc||'Sin descripción en el catálogo oficial.')+'</td><td class="catalogue-access">'+access+'</td></tr>';
   }).join('')||'<tr><td colspan="4" class="empty">'+(invalid?'Elegí una fecha Desde anterior o igual a Hasta.':'No hay resoluciones que coincidan con la búsqueda.')+'</td></tr>';
   byId('legalCataloguePage').textContent='Página '+(pageIndex+1)+' de '+pages;
   byId('legalCataloguePrevious').disabled=pageIndex===0;
   byId('legalCatalogueNext').disabled=pageIndex>=pages-1;
   const coverage=state.fromDate&&state.toDate?'Cobertura del catálogo: '+day(state.fromDate)+'–'+day(state.toDate)+'. ':'';
   const checked=state.checkedAt?new Intl.DateTimeFormat('es-AR',{dateStyle:'short',timeStyle:'short',timeZone:'America/Argentina/Buenos_Aires'}).format(new Date(state.checkedAt)):null;
   byId('legalCatalogueHealth').textContent=coverage+(state.complete?'Última consulta correcta: '+(checked||'no informada')+'.':'Consulta parcial'+(checked?' · último intento: '+checked:'')+'. Se conserva el catálogo anterior y se reintentará automáticamente.');
 }
 function show(view){
   for(const button of document.querySelectorAll('[data-legal-view]')){
     const selected=button.dataset.legalView===view;
     button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;
   }
   byId('legalTopicsPanel').hidden=view!=='topics';
   byId('legalCataloguePanel').hidden=view!=='catalogue';
 }
 const tabs=[...document.querySelectorAll('[data-legal-view]')];
 tabs.forEach((button,i)=>{
   button.addEventListener('click',()=>show(button.dataset.legalView));
   button.addEventListener('keydown',e=>{
     if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
     e.preventDefault();const target=tabs[e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length];show(target.dataset.legalView);target.focus();
   });
 });
 for(const id of ['legalCatalogueIssuer','legalCatalogueFrom','legalCatalogueTo','legalCatalogueSize'])byId(id).addEventListener('change',()=>{pageIndex=0;render();});
 byId('legalCatalogueSearch').addEventListener('input',()=>{pageIndex=0;render();});
 byId('legalCataloguePrevious').addEventListener('click',()=>{pageIndex=Math.max(0,pageIndex-1);render();});
 byId('legalCatalogueNext').addEventListener('click',()=>{pageIndex++;render();});
 byId('legalCatalogueClear').addEventListener('click',()=>{for(const id of ['legalCatalogueSearch','legalCatalogueFrom','legalCatalogueTo'])byId(id).value='';byId('legalCatalogueIssuer').value='ENReGE';pageIndex=0;render();});
 window.addEventListener('gasdata:updated',e=>{data=e.detail;render();});
 if(typeof D!=='undefined'&&D.meta){data=D;render();}
 window.GasDataResolutionCatalogue={filtered,render};
})();
