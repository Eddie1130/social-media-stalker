import { xHistoryReports } from './x-history-status.mjs';
import { simpleXHistory } from './x-status.mjs';
import path from 'node:path';
import { platforms } from './platform-menu.mjs';
const amount = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
const phases = { idle: '未開播', offline: '未開播', waiting: '等待檢查', checking: '檢查中', live: '直播中', recording: '錄影中', downloading: '下載中', stopped: '已停止', error: '異常／重試中', failed: '異常／重試中', retry: '等待重試', ready: '正常', complete: '正常', ok: '正常', watching: '監看中', polling: '監看中' };
export function platformStatus(user, platform, stateDir, read, now = Date.now(), { settings = {}, id } = {}) {
  const config = platforms[platform], names = Object.keys(user?.[config.key] || {}).sort();
  const health = read(path.join(stateDir, platform === 'ig' ? 'health.json' : platform === 'x' ? 'x/health.json' : 'tiktok/catalog/health.json'), null);
  const live = platform === 'tt' ? read(path.join(stateDir, 'tiktok/health.json'), null) : null;
  const fresh = h => h && Number.isFinite(h.at) && Math.abs(now - h.at) <= 120000 && !['stopped', 'fatal'].includes(h.phase);
  const history = platform === 'x' ? xHistoryReports(user, settings, id, stateDir, read, health) : [];
  const accounts = {}, backfills = {}, accountPending = {}, progress = {}; let pending = 0;
  for (const name of names) {
    const before = pending;
    let searching = false, scanKnown = false, scanBlocked = false, processing = false, routineScan = false;
    const sub = user[config.key][name];
    const target = Array.isArray(health?.targets) ? health.targets.find(t => t?.username === name) : health?.targets?.[name];
    let state = !fresh(health) ? '狀態未更新' : !target ? '等待首次檢查' : target.failures ? '異常／重試中' : '正常';
    let icon = state === '正常' ? '🟢' : state.includes('異常') ? '🔴' : '🟡';
    if (health?.enabled === false) { state = '已停用'; icon = '🟡'; }
    if (platform === 'ig' && target?.target && /^\d+$/.test(target.target)) {
      const catalog = read(path.join(stateDir, `catalog-${target.target}.json`), null);
      const assets = Object.values(catalog?.assets || {}), remaining = assets.filter(a => !a?.archiveDone).length;
      pending += remaining;
      scanKnown = typeof catalog?.posts?.baseline === 'boolean' && typeof catalog?.highlights?.baseline === 'boolean';
      searching = scanKnown && (!catalog.posts.baseline || !catalog.highlights.baseline);
      routineScan = scanKnown && !searching && (!!catalog.posts.cursor || !!catalog.highlights.todo?.length);
      scanBlocked = !!(catalog?.posts?.failures || catalog?.highlights?.failures || catalog?.posts?.latestScan?.failures || catalog?.highlights?.todo?.some(item => item?.failures));
      if (typeof catalog?.posts?.baseline === 'boolean' && typeof catalog?.highlights?.baseline === 'boolean' &&
          (!catalog.posts.baseline || !catalog.highlights.baseline || remaining)) {
        const retrying = catalog.posts.failures > 0 || catalog.highlights.failures > 0 || (Array.isArray(catalog.highlights.todo) && catalog.highlights.todo.some(item => item?.failures > 0));
        const scan = retrying ? '等待重試' : [!catalog.posts.baseline ? '貼文搜尋中' : '', !catalog.highlights.baseline ? '精選搜尋中' : ''].filter(Boolean).join('、') || '掃描完成';
        // Counts cover discovered assets; search may still discover more, so never claim an overall percentage.
        backfills[name] = `回補：${scan}\n封存：${assets.length ? `${assets.length - remaining}/${assets.length} 個已發現媒體` : '等待搜尋結果'}${fresh(health) ? '' : ' · 狀態未更新'}`;
      }
    } else if (platform === 'x') pending += amount(target?.pending);
    if (platform === 'x') {
      scanKnown = Number.isFinite(target?.lastSuccess) && target.lastSuccess > 0;
      const incompleteHistory = (Array.isArray(health?.historyJobs) ? health.historyJobs : []).some(item => item?.username === name && item.status !== 'cancelled' && (['partial', 'failed', 'needs_start'].includes(item.status) || amount(item.progress?.partialWindows) > 0 || amount(item.progress?.failedWindows) > 0));
      scanBlocked = incompleteHistory;
      const jobs = history.filter(job => job.username === name), job = jobs[0];
      if (job) {
        scanKnown = true;
        processing = jobs.some(item => ['importing', 'archive', 'rendering'].includes(item.phase) || item.status === 'importing');
        searching = jobs.some(item => item.fetchDone !== true && !['archive', 'rendering', 'finished'].includes(item.phase));
        scanBlocked ||= jobs.some(item => ['retry', 'queued'].includes(item.status));
        backfills[name] = job.status === 'queued' ? '回補：排隊中' : simpleXHistory(fresh(health) ? job : { ...job, progressUpdatedAt: undefined }, now).split('\n').slice(1).join('\n').replace(/^進度：/, '回補：');
        if (!fresh(health) && !backfills[name].includes('狀態未更新')) backfills[name] += ' · 狀態未更新';
        if (jobs.length > 1) backfills[name] += `\n另有 ${jobs.length - 1} 項${jobs.slice(1).every(job => job.status === 'queued') ? '排隊回補' : '回補任務'}`;
      }
    }
    if (platform === 'tt') {
      const states = Object.values(target || {});
      scanKnown = states.length > 0 && states.every(item => typeof item?.baseline === 'boolean');
      searching = states.some(item => item?.baseline === false || /分頁|搜尋/.test(item?.phase || ''));
      scanBlocked = states.some(item => item?.unresolved || item?.failures || item?.consecutiveFailures || item?.reason);
      pending += states.reduce((sum, state) => sum + amount(state?.pending), 0);
      const failed = states.some(s => s && (s.reason || s.failures>=3 || /error|fail|異常/.test(s.phase || '')));
      const transient=states.some(s=>(s?.consecutiveFailures||0)>0);
      const ages={story:180000,post:420000,repost:420000,profile:2100000,like:720000};
      const stale=Object.entries(target||{}).some(([kind,s])=>sub.notifications?.[kind]?.enabled&&Number.isFinite(s.lastSuccess)&&s.lastSuccess>0&&now-s.lastSuccess>(ages[kind]||420000));
      if (fresh(health) && target) { state = failed ? '內容異常／重試中' : '內容正常'; icon = failed ? '🔴' : '🟢'; }
      if(fresh(health)&&target&&!failed&&(transient||stale)){state=transient?'內容暫時失敗／等待重試':'內容更新較慢';icon='🟡';}
      const livePhase = live?.targets?.[name]?.phase;
      state += ` · LIVE ${fresh(live) ? phases[livePhase] || (/^(未開播|錄影中|檢查直播中|監看中|已停止監控|等待重試（\d+\/3）|檢查／錄影異常，重試中)$/.test(livePhase || '') ? livePhase : '等待檢查') : '狀態未更新'}`;
      if (/異常/.test(livePhase || '')) icon = '🔴';
      else if ((!fresh(live) || /重試|停止/.test(livePhase || '')) && icon === '🟢') icon = '🟡';
    }
    accountPending[name] = pending - before;
    progress[name] = !fresh(health) || health?.enabled === false || !target || !scanKnown ? '進度待確認' :
      scanBlocked || target.failures ? (searching ? '仍在搜尋新貼文／媒體（等待重試或排程）' : '進度待確認（等待重試或補查）') :
      searching ? '仍在搜尋新貼文／媒體' : processing && accountPending[name] === 0 ? '搜尋完成，媒體處理中' : accountPending[name] > 0 ? '搜尋完成，下載媒體中' : routineScan ? '首次搜尋已完成，例行檢查新內容' : '已完成，持續監控新內容';
    const muted = user.mediaNotifications === false || (sub?.notifications && !Object.values(sub.notifications).some(p => p.enabled));
    accounts[name] = `${icon} @${name} · ${state}${muted ? ' · 🔕' : ''}`;
  }
  const text = [`${config.title}｜${names.length} 個帳號`, ...(names.length ? names.map(name => [accounts[name], progress[name], ...(accountPending[name] > 0 ? [`待下載：${accountPending[name]}`] : [])].join('\n')) : ['尚未新增帳號。']), ...(pending > 0 ? [`待下載總數：${pending}`] : [])].join('\n');
  return { accounts, backfills, accountPending, progress, pending, text, history };
}
