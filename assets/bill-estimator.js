/* Monthly scenarios use full selected tariff rows, independent of chart filters. */
function billNumber(value){let s=String(value??'').trim();if(!s)return null;if(!/^\d+(?:[.,]\d+)?$/.test(s))return null;let n=Number(s.replace(',','.'));return Number.isFinite(n)?n:null}
function billMarketRange(value){let s=String(value??'').trim().replace(/^≈\s*/,'');let parts=s.split(/[–—]|\s+-\s+/);if(parts.length>2)return null;let n=parts.map(billNumber);return n.some(v=>v===null)?null:[Math.min(...n),Math.max(...n)]}
function billGasExcluded(rows){return rows.length>0&&rows.every(r=>r.SERVICIO==='Unbundling'||r.CATEGORIA==='SDB')}
function billCalculate(rows,consumption,reserved=null){
 if(consumption===null||!Number.isFinite(consumption)||consumption<0)return {error:'Ingresá un consumo mensual válido, mayor o igual a cero.'};
 if(!rows.length)return {error:'No hay datos oficiales para este período y selección.'};
 let scopes=new Set(rows.map(r=>['EMPRESA','TIPODESUMINISTRO','SUBZONACODIGO','SUBZONA','SERVICIO','CATEGORIA','TIPOTARIFA','CUADRO'].map(k=>r[k]).join('|')));
 if(scopes.size!==1)return {error:'Elegí una sola zona, servicio, categoría, tipo de tarifa y cuadro para estimar.'};
 let find=kind=>rows.filter(r=>r.CARGOTIPO===kind),fixed=find('Cargo Fijo ($)'),variable=find('Cargo Variable ($/m3)'),capacity=find('Capacidad ($ por m3/d)');
 if(fixed.length!==1||!Number.isFinite(fixed[0].CARGO)||!variable.length)return {error:'El cuadro no tiene un cargo fijo y variable únicos suficientes para estimar.'};
 let spans=variable.map(r=>({rate:r.CARGO,start:Number(r.CONSUMOM3INICIO||0),end:r.CONSUMOM3FIN===''||r.CONSUMOM3FIN==null?Infinity:Number(r.CONSUMOM3FIN)})).sort((a,b)=>a.start-b.start);
 let last=0,parts=[],cost=0;
 for(let i=0;i<spans.length;i++){let s=spans[i];if(!Number.isFinite(s.rate)||!Number.isFinite(s.start)||Number.isNaN(s.end)||s.end<=last||(i===0?s.start!==0:s.start!==last+1))return {error:'Tramos de consumo incompletos, superpuestos o duplicados. Revisá el original.'};let qty=Math.max(0,Math.min(consumption,s.end)-last);if(qty){parts.push({qty,rate:s.rate,from:last,to:s.end});cost+=qty*s.rate}last=s.end}
 if(consumption>last)return {error:'El consumo excede los tramos publicados; no se extrapola la tarifa.'};
 let category=rows[0].CATEGORIA,needsCapacity=/^(G|FD|FT|GNC FIRME)$/.test(category)||capacity.some(r=>r.CARGO!==0),reserveCost=0;
 if(needsCapacity){if(capacity.length!==1||!Number.isFinite(capacity[0].CARGO))return {error:'Falta el cargo oficial de reserva de capacidad para este servicio.'};if(reserved===null||!Number.isFinite(reserved)||reserved<=0)return {error:'Este servicio necesita la capacidad diaria contratada (m³/día). Ingresala para calcular.'};reserveCost=reserved*capacity[0].CARGO}
 return {fixed:fixed[0].CARGO,variable:cost,reserve:reserveCost,total:fixed[0].CARGO+cost+reserveCost,parts,excluded:billGasExcluded(rows),needsCapacity};
}
function billSelectedRows(rows){return rows.filter(r=>COMPARE_FILTERS.every(([id,key])=>$('#'+id).value==='all'||String(r[key])===$('#'+id).value))}
function billReferences(){return (D.marketPrices||[]).filter(r=>/^USD\/MMBtu(?: PIST)?$/.test(r.unit||'')&&billMarketRange(r.value))}
function billGasScenario(consumption,excluded){
 if(!excluded)return {min:0,max:0,note:'Gas incluido en el cargo variable: no se agrega una referencia de mercado.'};
 let selected=$('#billGasSource').value;
 if(!selected||selected==='none')return {min:0,max:0,omitted:true,note:'Gas excluido del cuadro y pendiente de agregar. Este subtotal no incluye su compra.'};
 if(selected==='custom'){let unit=billNumber($('#billGasCustom').value);return unit===null?{error:'Ingresá el precio de tu contrato en ARS/m³.'}:{min:consumption*unit,max:consumption*unit,note:'Precio de contrato ingresado: ARS '+fmt2(unit)+'/m³.'}}
 let ref=billReferences().find(r=>r.id===selected),range=ref&&billMarketRange(ref.value),fx=billNumber($('#billFX').value);
 if(!range)return {error:'La referencia seleccionada dejó de tener un precio numérico disponible. Elegí otra.'};
 if(fx===null||fx<=0)return {error:'Ingresá el tipo de cambio ARS/USD para convertir la referencia de Mercado.'};
 let factor=9300/252164.401,unit=range.map(v=>v*fx*factor);
 return {min:consumption*unit[0],max:consumption*unit[1],note:ref.label+' · '+ref.value+' '+ref.unit+' · '+(ref.reference||ref.observationDate||'fecha no informada')+' · TC '+fmt2(fx)+' ARS/USD · '+fmt2(unit[0])+(unit[0]!==unit[1]?'–'+fmt2(unit[1]):'')+' ARS/m³. '+(ref.note||''),url:safeNewsUrl(ref.sourceUrl),benchmark:true};
}
function renderBillEstimator(){
 let output=$('#billResult');if(!output)return;
 let rowsA=billSelectedRows(comparisonRowsA),rowsB=billSelectedRows(comparisonRowsB),excluded=billGasExcluded(rowsA)||billGasExcluded(rowsB),refs=$('#compareProduct').value==='GN'?billReferences():[],select=$('#billGasSource'),selected=select.value||'none';
 select.innerHTML='<option value="none">Sin agregar gas por separado</option><option value="custom">Mi contrato · ARS/m³</option>'+refs.map(r=>'<option value="'+esc(r.id)+'">'+esc(r.label+' · '+r.value+' '+r.unit+' · '+(r.reference||r.observationDate||'sin fecha'))+'</option>').join('');select.value=['none','custom',...refs.map(r=>r.id)].includes(selected)?selected:'none';
 $('#billGasControls').hidden=!excluded;$('#billCustomControl').hidden=select.value!=='custom';$('#billFXControl').hidden=['none','custom'].includes(select.value);
 $('#billGasInfo').textContent=excluded?'El gas se agrega únicamente al período cuyo cuadro lo excluye. Las referencias de Mercado se actualizan con su frecuencia habitual; son escenarios, no ofertas de suministro. Para GLP por red usá tu contrato en ARS/m³: USD/t necesita una conversión específica del producto.':'El gas ya está incluido en esta selección. El estimador usa el cargo variable total y evita sumar otra vez PIST, transporte, gas retenido o margen.';
 let consumption=billNumber($('#billConsumption').value),reserve=billNumber($('#billReserved').value),extra=billNumber($('#billExtras').value);
 let cards=[['A',$('#compareMonthA').value,rowsA],['B',$('#compareMonthB').value,rowsB]].map(([name,period,rows])=>{
 let bill=billCalculate(rows,consumption,reserve);if(bill.error)return '<article class="bill-card"><h4>Período '+name+' · '+esc(period)+'</h4><p class="bill-error">'+esc(bill.error)+'</p></article>';
 let gas=billGasScenario(consumption,bill.excluded);if(gas.error||extra===null)return '<article class="bill-card"><h4>Período '+name+' · '+esc(period)+'</h4><p class="bill-error">'+esc(gas.error||'Ingresá otros cargos válidos; usá cero si no querés agregarlos.')+'</p></article>';
 let low=bill.total+gas.min+extra,high=bill.total+gas.max+extra,row=(label,value)=>'<div class="bill-line"><span>'+label+'</span><b>ARS '+fmt2(value)+'</b></div>';
 return '<article class="bill-card"><h4>Período '+name+' · '+esc(period)+'</h4>'+row('Cargo fijo mensual',bill.fixed)+row('Consumo · '+fmt2(consumption)+' m³',bill.variable)+(bill.needsCapacity?row('Reserva · '+fmt2(reserve)+' m³/día',bill.reserve):'')+(bill.excluded?'<div class="bill-line"><span>Compra de gas · escenario</span><b>'+(gas.omitted?'Pendiente':'ARS '+fmt2(gas.min)+(gas.max!==gas.min?'–'+fmt2(gas.max):''))+'</b></div>':'')+row('Otros cargos ingresados',extra)+'<div class="bill-total"><span>Subtotal estimado sin impuestos</span><strong>ARS '+fmt2(low)+(low!==high?'–'+fmt2(high):'')+'</strong></div><p>'+esc(gas.note)+'</p>'+(gas.url?'<a href="'+esc(gas.url)+'" target="_blank" rel="noopener">Fuente de la referencia ↗</a>':'')+'<details><summary>Cómo se calculó el consumo</summary>'+bill.parts.map(p=>'<p>'+fmt2(p.qty)+' m³ × ARS '+fmt2(p.rate)+'/m³ = ARS '+fmt2(p.qty*p.rate)+'</p>').join('')+(bill.parts.length?'':'<p>Consumo cero: se conserva el cargo fijo.</p>')+'</details>'+(bill.excluded?'<p><b>Alcance:</b> faltan los cargos de transporte y gas retenido que correspondan a tu contrato, salvo que los incluyas en “Otros cargos”.</p>':'')+'</article>';
 });output.innerHTML=cards.join('');
}
['billConsumption','billReserved','billFX','billGasCustom','billExtras'].forEach(id=>$('#'+id).addEventListener('input',renderBillEstimator));$('#billGasSource').addEventListener('change',renderBillEstimator);
renderBillEstimator();
