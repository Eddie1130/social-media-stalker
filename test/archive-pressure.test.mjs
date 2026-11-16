import test from 'node:test';import assert from 'node:assert/strict';
import {PressureController} from '../src/archive-pressure.mjs';
test('pressure slows background work and recovers with hysteresis',()=>{
 const p=new PressureController();for(let i=0;i<3;i++)p.observe({checkpointP95Ms:600,eventLoopP95Ms:0,oldestInteractiveMs:0});assert.equal(p.limits().downloadConcurrency,1);assert.equal(p.limits().allowHistoricalDiscovery,false);
 for(let i=0;i<6;i++)p.observe({checkpointP95Ms:10,eventLoopP95Ms:10,oldestInteractiveMs:0});assert.equal(p.limits().downloadConcurrency,2);
 for(let i=0;i<6;i++)p.observe({checkpointP95Ms:10,eventLoopP95Ms:10,oldestInteractiveMs:0});assert.equal(p.limits().downloadConcurrency,3);
});

test('slow event-loop samples protect downloads between fifteen-second health updates', async () => {
 const { PressureSampler } = await import('../src/archive-pressure.mjs');
 const sampler=new PressureSampler(),controller=new PressureController();
 const local={series:[{name:'event_loop',count:1,last:300}]};
 for(const now of [1000,6000,11000])controller.observe(sampler.observe(local,[],now));
 assert.equal(controller.limits().downloadConcurrency,1);
 local.series[0]={name:'event_loop',count:2,last:20};
 for(let i=0;i<12;i++)controller.observe(sampler.observe(local,[],16000+i*5000));
 assert.equal(controller.limits().downloadConcurrency,3);
});

test('a single slow startup checkpoint cannot pin all downloaders to one worker', async () => {
 const { PressureSampler } = await import('../src/archive-pressure.mjs');
 const sample = new PressureSampler(), controller = new PressureController();
 const local = {series:[{name:'settings_commit',dimensions:{outcome:'ok'},count:1,last:900,recentP95:900}]};
 for(let i=0;i<20;i++)controller.observe(sample.observe(local, []));
 assert.equal(controller.limits().downloadConcurrency,3);
 for(let i=0;i<3;i++){
  local.series[0].count++;
  controller.observe(sample.observe(local, []));
 }
 assert.equal(controller.limits().downloadConcurrency,1,'sustained fresh slow commits still apply backpressure');
 for(let i=0;i<12;i++)controller.observe(sample.observe(local, []));
 assert.equal(controller.limits().downloadConcurrency,3,'idle checkpoints allow recovery');
});
