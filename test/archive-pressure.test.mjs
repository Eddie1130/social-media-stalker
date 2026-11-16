import test from 'node:test';import assert from 'node:assert/strict';
import {PressureController} from '../src/archive-pressure.mjs';
test('pressure slows background work and recovers with hysteresis',()=>{
 const p=new PressureController();for(let i=0;i<3;i++)p.observe({checkpointP95Ms:600,eventLoopP95Ms:0,oldestInteractiveMs:0});assert.equal(p.limits().downloadConcurrency,1);assert.equal(p.limits().allowHistoricalDiscovery,false);
 for(let i=0;i<6;i++)p.observe({checkpointP95Ms:10,eventLoopP95Ms:10,oldestInteractiveMs:0});assert.equal(p.limits().downloadConcurrency,2);
 for(let i=0;i<6;i++)p.observe({checkpointP95Ms:10,eventLoopP95Ms:10,oldestInteractiveMs:0});assert.equal(p.limits().downloadConcurrency,3);
});
