import { record } from './performance-metrics.mjs';
import { validExportReply } from './archive-export.mjs';

export async function flushReplies(settingsSource,client,persist,{stopping=()=>false,log=()=>{},transaction,earlyAcknowledged=new Map()}={}) {
  const current=typeof settingsSource==='function'?settingsSource:()=>settingsSource;
  const acknowledgements=new Set();let ok=true;
  const commit=async mutator=>{
    const apply=s=>{for(const key of acknowledgements)delete s.replies[key];mutator?.(s);};
    if(transaction)await transaction(apply);
    else {apply(current());await persist();}
    acknowledgements.clear();
  };
  const superseded=(s,key,reply)=>{
    const target=reply.body.message_id||reply.replacesMessageId;
    const entries=Object.entries(s.replies),index=entries.findIndex(([k])=>k===key);
    return target&&entries.slice(index+1).some(([,other])=>other.userId===reply.userId&&(other.body.message_id||other.replacesMessageId)===target&&['editMessageText','sendMessage'].includes(other.method));
  };
  try {
    const keys=Object.keys(current().replies).sort((a,b)=>Number(current().replies[b]?.method==='answerCallbackQuery')-Number(current().replies[a]?.method==='answerCallbackQuery'));
    for(const key of keys) {
      if(stopping())break;
      const reply=current().replies[key];if(!reply)continue;
      if(!current().allowedIds.includes(reply.userId)||!validExportReply(current(),reply)||superseded(current(),key,reply)){await commit(s=>{delete s.replies[key];});continue;}
      if(!['sendMessage','editMessageText','answerCallbackQuery'].includes(reply.method)||(reply.method!=='answerCallbackQuery'&&String(reply.body?.chat_id)!==reply.userId))throw Error('TELEGRAM_REPLY_INVALID');
      if(reply.method==='editMessageText'&&(!Number.isSafeInteger(reply.body.message_id)||reply.body.message_id<1))throw Error('TELEGRAM_REPLY_INVALID');
      if(Date.now()<(reply.retryAt||0)){ok=false;continue;}
      const started=Date.now();let result;
      try {
        const early=earlyAcknowledged.get(key);earlyAcknowledged.delete(key);
        if(!(early&&await early))result=await client.call(reply.method,reply.body,{priority:true,beforeRequest:()=>{
          const s=current();if(!s.replies[key]||!s.allowedIds.includes(reply.userId)||!validExportReply(s,reply)||superseded(s,key,reply))throw Error('TELEGRAM_REPLY_SUPERSEDED');
        }});
      } catch(error) {
        if(error.message==='TELEGRAM_REPLY_SUPERSEDED'){await commit(s=>{delete s.replies[key];});continue;}
        if(reply.method==='editMessageText'&&error.messageUnavailable){await commit(s=>{const r=s.replies[key];if(r){r.replacesMessageId=r.body.message_id;r.method='sendMessage';delete r.body.message_id;}});ok=false;continue;}
        if(!/^TELEGRAM_(?:ERROR_\d+|NETWORK_OR_RESPONSE_ERROR|RETRY_WAIT|STOPPING)$/.test(error.message))throw error;
        if(!(reply.method==='answerCallbackQuery'&&error.message==='TELEGRAM_ERROR_400')){
          await commit(s=>{const r=s.replies[key];if(r){r.failures=(r.failures||0)+1;r.retryAt=Date.now()+Math.min(300,15*2**Math.min(r.failures,5))*1000;r.error=error.message;}});
          ok=false;log('TELEGRAM_REPLY_RETRY',{reason:error.message});continue;
        }
      }
      if(reply.method==='answerCallbackQuery')acknowledgements.add(key);
      else await commit(s=>{
        if (reply.historyPanel && reply.method === 'sendMessage' && Number.isSafeInteger(result?.message_id)) {
          const panels = s.users[reply.userId].historyPanels ||= {};
          if (reply.replacesMessageId) delete panels[reply.replacesMessageId];
          panels[result.message_id] = reply.historyPanel;
        }
        if(reply.inputPrompt&&reply.method==='sendMessage'&&s.users?.[reply.userId]?.waiting===reply.inputPrompt&&Number.isSafeInteger(result?.message_id)&&result.message_id>0){const u=s.users[reply.userId];if(!u.waitingMessageId||u.waitingMessageId===reply.replacesMessageId)u.waitingMessageId=result.message_id;}
        delete s.replies[key];
      });
      record('reply_queue',Math.max(0,started-(reply.at||started)),{lane:'interactive'});
      record('reply_total',Math.max(0,Date.now()-(reply.at||started)),{lane:'interactive'});
      log('TELEGRAM_REPLY_SENT',{method:reply.method,queueMs:Math.max(0,started-(reply.at||started)),elapsedMs:Date.now()-started});
    }
  } finally {if(acknowledgements.size)await commit();}
  return ok;
}
