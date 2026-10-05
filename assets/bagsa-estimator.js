function billBagsaRows(rows){return rows.filter(r=>r.TIPODESUMINISTRO==='GN'&&r.CATEGORIA==='SDB'&&r.SERVICIO==='Servicio General'&&r.TIPOTARIFA==='Plenas'&&r.CUADRO==='SinSEF'&&r.EMPRESA===$('#billBagsaCompany').value&&r.SUBZONA===$('#billBagsaZone').value)}
function billBagsaCalculate({connection,rows,volume,capacity,gasPrice,userGasPrice,reference,includeRetained}){
 if(volume===null||!Number.isFinite(volume)||volume<0)return {error:'Ingresá el volumen mensual total del punto de entrega de BAGSA.'};
 let result={gas:gasPrice===null?0:volume*gasPrice,gasPending:gasPrice===null,network:0,networkPending:false,retained:0,retainedPending:false,retainedQty:0,notes:[]};
 if(connection==='direct'){
  if(!reference){result.networkPending=true;result.notes.push('Transporte pendiente: elegí la ruta contratada por BAGSA.');result.retainedPending=includeRetained}
  else{
   if(reference.service==='TF'&&(capacity===null||capacity<=0))return {error:'El transporte firme de BAGSA necesita su capacidad diaria contratada.'};
   result.network=reference.service==='TF'?reference.rate*capacity:reference.rate/1000*volume;
   result.notes.push(reference.company+' · '+reference.service+' · '+reference.origin+' → '+reference.destination+' · '+reference.period+' · Resolución '+reference.resolution+'. Misma referencia vigente en A y B.');result.source={url:reference.sourceUrl};
   if(includeRetained){let p=reference.retainedPercent;if(!Number.isFinite(p)||p<0||p>=100)return {error:'La retención de la ruta no es válida.'};result.retainedQty=volume/(1-p/100)-volume;result.retainedPending=gasPrice===null;result.retained=gasPrice===null?0:result.retainedQty*gasPrice;result.notes.push('Gas retenido de transporte: '+fmt2(p)+'% del volumen inyectado; '+fmt2(result.retainedQty)+' m³ adicionales.');}
  }
 }else{
  let tariff=billCalculate(rows,volume,capacity);
  if(tariff.error){result.networkPending=true;result.notes.push('Tarifa SDB pendiente: '+tariff.error)}else{result.network=tariff.total;result.notes.push('SDB: cargo fijo ARS '+fmt2(tariff.fixed)+' + consumo ARS '+fmt2(tariff.variable)+(tariff.reserve?' + reserva ARS '+fmt2(tariff.reserve):'')+'. Gas y retención no incluidos.');result.source=rows.find(r=>r._pdfSource)?._pdfSource;}
  let retained=rows.filter(r=>r.CARGOTIPO==='Gas Retenido sobre precio a usuarios (%)');
  if(retained.length!==1||userGasPrice===null){result.retainedPending=true;result.notes.push('Retención SDB pendiente: requiere el porcentaje oficial legible y el precio del gas a usuarios aplicable a la cartera. No se interpreta un importe ARS/m³ como porcentaje.');}
  else{result.retained=volume*retained[0].CARGO*userGasPrice;result.notes.push('Retención SDB: '+fmt2(retained[0].CARGO*100)+'% × ARS '+fmt2(userGasPrice)+'/m³ de gas a usuarios × '+fmt2(volume)+' m³. Base distinta de la retención por volumen TGS/TGN.');}
 }
 result.total=result.gas+result.network+result.retained;result.pending=result.gasPending||result.networkPending||result.retainedPending;return result;
}
function renderBagsaEstimator(){
 let output=$('#billBagsaResult');if(!output)return;
 let connection=$('#billBagsaConnection').value;$('#billBagsaDirectControls').hidden=connection!=='direct';$('#billBagsaDistributorControls').hidden=connection!=='distributor';
 let rows=[...billRowsA,...billRowsB].filter(r=>r.CATEGORIA==='SDB'&&r.TIPODESUMINISTRO==='GN'),company=$('#billBagsaCompany').value,zone=$('#billBagsaZone').value;
 fillPortalSelect('billBagsaCompany',[...new Set(rows.map(r=>r.EMPRESA))].sort(),company||$('#billCompany').value);
 fillPortalSelect('billBagsaZone',[...new Set(rows.filter(r=>r.EMPRESA===$('#billBagsaCompany').value).map(r=>r.SUBZONA))].sort(),zone||$('#billZone').value);
 let refs=billTransportReferences().filter(r=>r.company===$('#billBagsaTransportCompany').value&&r.service===$('#billBagsaTransportService').value),route=$('#billBagsaTransportRoute').value;
 fillPortalSelect('billBagsaTransportRoute',refs.map(r=>r.id),route,'Elegí la ruta contratada por BAGSA');for(let option of $('#billBagsaTransportRoute').options){let ref=refs.find(r=>r.id===option.value);if(ref)option.textContent=ref.origin+' → '+ref.destination}
 if(connection==='none'){output.innerHTML='<p>Elegí el tipo de conexión para ver los pagos de BAGSA.</p>';return}
 if($('#billProduct').value!=='GN'){output.innerHTML='<p class="bill-error">Este escenario de BAGSA corresponde a gas natural. Para GLP se necesitan otros contratos y unidades.</p>';return}
 let volume=billNumber($('#billBagsaConsumption').value),capacity=billNumber($('#billBagsaReserved').value),gasPrice=billNumber($('#billBagsaGasPrice').value),userGasPrice=billNumber($('#billBagsaUserGasPrice').value),reference=refs.find(r=>r.id===$('#billBagsaTransportRoute').value);
 output.innerHTML=[['A',$('#billMonthA').value,billRowsA],['B',$('#billMonthB').value,billRowsB]].map(([period,date,data])=>{
  let result=billBagsaCalculate({connection,rows:billBagsaRows(data),volume,capacity,gasPrice,userGasPrice,reference,includeRetained:$('#billBagsaIncludeRetained').checked});
  if(result.error)return '<article class="bill-card"><h4>BAGSA · '+period+' · '+esc(date)+'</h4><p class="bill-error">'+esc(result.error)+'</p></article>';
  let groups=new Map(),add=(provider,label,cost,pending)=>{let g=groups.get(provider)||{provider,labels:[],cost:0,pending:false};g.labels.push(label);g.cost+=cost;g.pending=g.pending||pending;groups.set(provider,g)},gasProvider=$('#billBagsaGasPayee').value,networkProvider=connection==='distributor'?'distributor':$('#billBagsaTransportPayee').value;
  add(gasProvider,'Compra de gas',result.gas,result.gasPending);add(networkProvider,connection==='direct'?'Transporte contratado':'Servicio SDB · red y transporte del cuadro',result.network,result.networkPending);
  if(result.retained!==0||result.retainedPending)add(connection==='direct'?gasProvider:'distributor','Gas retenido',result.retained,result.retainedPending);
  let labels={commercial:'Comercializadora / productor',transporter:reference?.company||'Transportista',distributor:connection==='distributor'?$('#billBagsaCompany').value:'Distribuidora según contrato'};
  return '<article class="bill-card"><h4>BAGSA · período '+period+' · '+esc(date)+'</h4><p>Volumen del punto de entrega: '+fmt2(volume)+' m³.</p>'+[...groups.values()].map(g=>'<div class="bill-invoice"><b>BAGSA paga a '+esc(labels[g.provider])+'</b><p>'+esc(g.labels.join(' + '))+'</p><strong>'+(g.pending?'Parcial · ':'')+'ARS '+fmt2(g.cost)+'</strong>'+(g.pending?'<p>Hay conceptos pendientes de completar.</p>':'')+'</div>').join('')+'<div class="bill-total"><span>'+(result.pending?'Subtotal parcial de BAGSA':'Subtotal estimado de BAGSA')+' · sin impuestos</span><strong>ARS '+fmt2(result.total)+'</strong></div>'+result.notes.map(note=>'<p>'+esc(note)+'</p>').join('')+(result.source?'<a href="'+esc(result.source.url)+(result.source.page?'#page='+result.source.page:'')+'" target="_blank" rel="noopener">Fuente oficial'+(result.source.page?' · página '+result.source.page:'')+' ↗</a>':'')+'</article>';
 }).join('');
}
['billBagsaConnection','billBagsaGasPayee','billBagsaTransportPayee','billBagsaCompany','billBagsaZone','billBagsaTransportCompany','billBagsaTransportService','billBagsaTransportRoute','billBagsaIncludeRetained'].forEach(id=>$('#'+id).addEventListener('change',renderBagsaEstimator));
['billBagsaConsumption','billBagsaReserved','billBagsaGasPrice','billBagsaUserGasPrice'].forEach(id=>$('#'+id).addEventListener('input',renderBagsaEstimator));
renderBagsaEstimator();
