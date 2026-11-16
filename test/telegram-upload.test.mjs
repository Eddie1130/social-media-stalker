import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {prepareUploads} from '../src/telegram-upload.mjs';
test('original media uses a validated source descriptor without copying bytes',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'upload-source-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const source=path.join(dir,'clip.mp4');fs.writeFileSync(source,'media');
 const upload=await prepareUploads([{name:'media0',filename:'clip.mp4',sourcePath:source,blob:{type:'video/mp4',stream(){throw Error('MUST_NOT_COPY')}}}],{dir,requestId:'job'});
 assert.equal(upload.files[0].path,source);assert.equal(upload.files[0].source,true);assert.equal(fs.existsSync(path.join(dir,'.broker-upload')),false);await upload.cleanup();assert.equal(fs.existsSync(source),true);
});
