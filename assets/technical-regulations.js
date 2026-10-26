/* Technical decisions share the legal catalogue and its collection schedule. */
(() => {
 'use strict';
 const node=document.getElementById('techRegList');if(!node)return;
 let data=null,pageIndex=0;const size=10;
 const normal=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[–—-]/g,' ');
 function filtered(){
   const scope=document.getElementById('techRegScope').value,issuer=document.getElementById('techRegIssuer').value,q=normal(document.getElementById('techRegSearch').value).trim();
   return (data?.regulations||[]).filter(r=>(scope==='all'||r.technical===true)&&(issuer==='all'||regIssuer(r).name===issuer)&&(!q||normal([r.num,r.title,r.firstArticle,r.disposition,r.desc,...r.tags||[]].join(' ')).includes(q)))
    .sort((a,b)=>String(b.publishedAt||b.issuedAt||'').localeCompare(String(a.publishedAt||a.issuedAt||'')));
 }
 function render(){
   if(!data)return;const rows=filtered(),pages=Math.max(1,Math.ceil(rows.length/size));pageIndex=Math.min(pageIndex,pages-1);
   node.innerHTML=rows.slice(pageIndex*size,(pageIndex+1)*size).map(r=>ritem(r,false)).join('')||'<p class="empty">No hay resoluciones que coincidan con estos filtros.</p>';
   document.getElementById('techRegCount').textContent=rows.length+' resultados · más recientes primero';
   document.getElementById('techRegPage').textContent='Página '+(pageIndex+1)+' de '+pages;
   document.getElementById('techRegPrevious').disabled=pageIndex===0;document.getElementById('techRegNext').disabled=pageIndex>=pages-1;
   const c=data.resolutionExport||{},b=data.regulationScan||{};
   document.getElementById('techRegHealth').textContent='Consulta cada 3 horas. '+(b.complete===false?'Boletín Oficial: consulta parcial; se conservan los documentos y reintentos pendientes. ':'')+'Catálogo del regulador: '+(c.complete?'última consulta correcta '+fmt(c.checkedAt):'consulta parcial; se conserva el último catálogo')+'. Cuando no se confirmó la publicación, se indica la fecha de la resolución. Una consulta pública no equivale a una norma aprobada.';
   if(typeof portalRefreshButtons==='function')portalRefreshButtons();
 }
 for(const id of ['techRegScope','techRegIssuer'])document.getElementById(id).addEventListener('change',()=>{pageIndex=0;render();});
 document.getElementById('techRegSearch').addEventListener('input',()=>{pageIndex=0;render();});
 document.getElementById('techRegPrevious').addEventListener('click',()=>{pageIndex=Math.max(0,pageIndex-1);render();});
 document.getElementById('techRegNext').addEventListener('click',()=>{pageIndex++;render();});
 window.addEventListener('gasdata:updated',e=>{data=e.detail;render();});
 if(typeof D!=='undefined'&&D.meta){data=D;render();}
 window.GasDataTechnicalRegulations={filtered,render};
})();
