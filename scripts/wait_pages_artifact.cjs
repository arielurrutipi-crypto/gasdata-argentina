/* GitHub's artifact metadata may lag behind an otherwise successful upload. */
module.exports = async function waitForArtifact({github, context, core, name, expectedId,
 maxAttempts=10, intervalMs=3000, wait=ms=>new Promise(resolve=>setTimeout(resolve,ms))}) {
 if(!name || !expectedId)throw new Error('Falta el nombre o identificador del paquete recién cargado.');
 let consecutive=0,lastStatus='sin registro visible';
 for(let attempt=0;attempt<maxAttempts;attempt++){
   let artifacts;
   try {
     artifacts=await github.paginate(github.rest.actions.listWorkflowRunArtifacts,
       {...context.repo,run_id:context.runId,per_page:100});
   } catch(error) {
     consecutive=0;lastStatus='error HTTP '+(error.status||'no informado');
     core.warning('No se pudo consultar el paquete ('+lastStatus+'); se reintentará.');
   }
   if(artifacts){
     const matches=artifacts.filter(a=>a.name===name);
     if(matches.length>1)throw new Error('Hay varios paquetes con el nombre de este intento: '+name);
     const artifact=matches[0];
     if(artifact&&!artifact.expired&&String(artifact.id)===String(expectedId)){
       consecutive++;
       if(consecutive>=2){core.info('Paquete confirmado: '+name+' (ID '+expectedId+').');return artifact;}
       lastStatus='registro encontrado; confirmando visibilidad';
     }else{consecutive=0;lastStatus='el paquete recién cargado todavía no está visible';}
   }
   core.info('Esperando metadatos de '+name+' · consulta '+(attempt+1)+'/'+maxAttempts+'.');
   if(attempt+1<maxAttempts)await wait(intervalMs);
 }
 throw new Error('No se pudo confirmar el paquete '+name+': '+lastStatus+'. No se publican paquetes anteriores.');
};
