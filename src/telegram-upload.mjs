import fs from 'node:fs/promises';
import path from 'node:path';
export async function prepareUploads(input,{dir,requestId}){
 if(input.length>30)throw Error('TELEGRAM_BROKER_REQUEST_INVALID');
 const spool=path.join(dir,'.broker-upload',requestId),files=[];let created=false;
 try{
  for(const [index,file] of input.entries()){
   if(file.sourcePath){files.push({name:file.name,filename:file.filename,path:file.sourcePath,type:file.blob.type,source:true});continue;}
   if(file.blob.size>2*1024*1024)throw Error('TELEGRAM_BROKER_REQUEST_INVALID');
   await fs.mkdir(spool,{recursive:true,mode:0o700});created=true;
   const filename=path.join(spool,String(index)),handle=await fs.open(filename,'wx',0o600);
   try{for await(const chunk of file.blob.stream())await handle.writeFile(chunk);}finally{await handle.close();}
   files.push({name:file.name,filename:file.filename,path:filename,type:file.blob.type});
  }
  return {files,cleanup:async()=>{if(created)await fs.rm(spool,{recursive:true,force:true});}};
 }catch(error){if(created)await fs.rm(spool,{recursive:true,force:true});throw error;}
}
