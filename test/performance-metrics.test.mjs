import test from 'node:test';
import assert from 'node:assert/strict';
import { PerformanceMetrics } from '../src/performance-metrics.mjs';
test('metrics clamp clock drift, bound series, and reject private dimensions',()=>{
 const m=new PerformanceMetrics({maxSeries:2});
 m.record('settings_commit',-4,{outcome:'ok'});m.record('settings_commit',100,{outcome:'ok'});
 assert.equal(m.snapshot().series[0].count,2);assert.equal(m.snapshot().series[0].max,100);
 assert.throws(()=>m.record('settings_commit',1,{url:'https://private/token'}));
 assert.throws(()=>m.record('unknown_metric',1));
 m.record('api_http',10,{outcome:'ok'});m.record('browser_query',20,{outcome:'ok'});
 assert.equal(m.snapshot().series.length,2);assert.equal(m.snapshot().dropped,1);
});
test('histogram quantiles use bounded buckets',()=>{
 const m=new PerformanceMetrics();for(let i=0;i<100;i++)m.record('api_http',i+1);
 assert.equal(m.snapshot().series[0].p95,100);assert.equal(m.snapshot().series[0].count,100);
});
