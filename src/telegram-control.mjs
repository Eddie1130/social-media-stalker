import { adminStatus } from './admin-status.mjs';
import {createPressurePublisher} from './archive-pressure.mjs';
import { writeSnapshot } from './atomic-state-store.mjs';
import { DeliveryBroker } from './telegram-delivery-broker.mjs';
import { snapshot as performanceSnapshot, record } from './performance-metrics.mjs';
import { monitorEventLoopDelay } from 'node:perf_hooks';
import { platformStatus } from './platform-status.mjs';
import { telegramApiBase } from './telegram-endpoint.mjs';
import { TikTokDelivery } from './tiktok-delivery.mjs';
import { ManualDelivery } from './manual-delivery.mjs';
import { flushReplies } from './telegram-replies.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { atomic, load, log } from './error-monitor.mjs';
import { settingsFile, initializeSettings, isSystemAlert, serviceUnavailableText } from './telegram-settings.mjs';
import { eventDirectory } from './telegram-events.mjs';
import { SettingsStore } from './telegram-state-store.mjs';
import { applyUpdate, authorizeUpdate } from './telegram-menu.mjs';
import { PersonalDelivery } from './telegram-delivery.mjs';
import { TelegramClient } from './telegram-client.mjs';
import { XDelivery } from './x-delivery.mjs';
import { simpleXHistory } from './x-status.mjs';
import { ingestExportReports, exportServiceReady, exportAccountNames } from './archive-export.mjs';

export function describeUser(settings, id, stateDir, watchdogDir = null) {
  let readErrors = 0;
  const read = (file, fallback) => { try { return load(file, fallback); } catch { readErrors++; return fallback; } };
  const user = settings.users[id], health = read(path.join(stateDir, 'health.json'), null);
  const targets = Array.isArray(health?.targets) ? health.targets : [];
  const names = Object.keys(user?.targets || {});
  const lines = ['📊 你的監看狀態'];
  const overviews = Object.fromEntries(['ig', 'x', 'tt'].map(platform => [platform, platformStatus(user, platform, stateDir, read, Date.now(), { settings, id })]));
  for (const overview of Object.values(overviews)) lines.push('', overview.text);
  const reports = overviews.x.history;
  if (reports.length) {
    lines.push('', '𝕏 歷史回補');
    for (const job of reports.filter(job => job.status !== 'queued')) lines.push(simpleXHistory(job));
    const queued = [...new Set(reports.filter(job => job.status === 'queued').map(job => '@' + job.username))];
    if (queued.length) lines.push('排隊：' + queued.join('、'));
  }
  const issues = { ...read(path.join(stateDir, 'monitor/issues.json'), {}), ...(watchdogDir ? read(path.join(watchdogDir, 'issues.json'), {}) : {}) };
  const targetIds = new Set(targets.filter(t => t && names.includes(t.username)).map(t => t.target));
  const relevant = Object.entries(issues).filter(([key, v]) => v?.active && (!key.startsWith('target:') || targetIds.has(v.target) || v.usernames?.some(name => names.includes(name)) || names.some(name => key.startsWith(`target:${name}:`))));
  const visibleIssues = relevant.slice(0, 6).map(([key, v]) => id !== settings.ownerId && isSystemAlert({ ...v, issueKey: key, username: /^target:([^:]+):/.exec(key)?.[1] }) ? serviceUnavailableText : `${key}：${v.reason}`);
  if (relevant.length) lines.push('', `⚠️ 目前異常：${relevant.length}`, ...new Set(visibleIssues));
  if (readErrors) lines.push(id === settings.ownerId ? `有 ${readErrors} 份執行狀態讀取失敗，請檢查監控日誌。` : serviceUnavailableText);
  if (health && (!Number.isFinite(health.at) || Date.now() - health.at > 120000)) lines.push('監看程序心跳已過期，顯示的是先前紀錄。');
  lines.push(`查詢時間：${new Intl.DateTimeFormat('zh-TW', { timeZone: 'Asia/Hong_Kong', dateStyle: 'short', timeStyle: 'medium', hour12: false }).format(new Date())}（香港）`);
  return lines.join('\n').slice(0, 3400);
}

// Refresh pre-upgrade status snapshots before retrying persisted messages.
export function refreshQueuedDescriptions(delivery, settings, describe) {
  for (const task of Object.values(delivery.state.pending)) {
    if (task.type === 'summary') task.body.text = `每日摘要（香港時間 20:00）\n${describe(task.userId)}`;
  }
  for (const reply of Object.values(settings.replies)) {
    if (['sendMessage', 'editMessageText'].includes(reply.method) && reply.body?.text?.startsWith('📊 你的監看狀態')) reply.body.text = describe(reply.userId);
  }
}

export function completedHistoryPanels(settings, describe) {
  const edits = [];
  for (const id of settings.allowedIds) {
    const overviews = {};
    for (const [messageId, panel] of Object.entries(settings.users[id]?.historyPanels || {})) {
      const overview = overviews[panel.platform] ??= describe.platform(id, panel.platform);
      if (!overview?.archived?.[panel.name]) continue;
      const text = `✅ @${panel.name} 的歷史內容已封存。`;
      const rows = panel.body.reply_markup.inline_keyboard.filter(row => !row.some(b => /^(?:(tt|x):)?history:/.test(b.callback_data)));
      edits.push({ id, messageId, panel, body: { chat_id: id, message_id: Number(messageId),
        text: panel.request ? text : panel.body.text + '\n' + text, reply_markup: { inline_keyboard: rows } } });
    }
  }
  return edits;
}

export async function run({ env = process.env, args = process.argv } = {}) {
  const dir = env.IG_CONTROL_DIR || '/app/control', stateDir = env.IG_STATE_DIR || '/app/state';
  if (env.IG_TELEGRAM_CONTROL === '0') {
    const health = () => atomic(path.join(dir, 'health.json'), { at: Date.now(), enabled: false, telegramOk: true, pollOk: true, lastPollAt: Date.now() });
    health();
    if (args.includes('--once')) return;
    await new Promise(resolve => {
      const tick = setInterval(health, 15000);
      const stop = () => { clearInterval(tick); for (const name of ['SIGTERM', 'SIGINT']) process.off(name, stop); resolve(); };
      for (const name of ['SIGTERM', 'SIGINT']) process.on(name, stop);
    });
    return;
  }
  let settings = initializeSettings(env);
  const signal = new AbortController();
  let stopping = false, telegramOk = true, xTelegramOk = true, pollOk = true, lastPollAt = Date.now();
  const stop = () => { stopping = true; signal.abort(); };
  for (const name of ['SIGTERM', 'SIGINT']) process.on(name, stop);
  const wait = ms => new Promise(resolve => { const t = setTimeout(done, ms); function done() { clearTimeout(t); signal.signal.removeEventListener('abort', done); resolve(); } signal.signal.addEventListener('abort', done, { once: true }); if (stopping) done(); });
  const client = new TelegramClient({ token: env.TELEGRAM_BOT_TOKEN, baseUrl: telegramApiBase(env), dir, signal: signal.signal, sleep: wait });
  const isolated=!args.includes('--once');
  const delivery = isolated ? {state:{pending:{}},persist(){}} : new PersonalDelivery({ dir, stateDir, settings: () => settings, log });
  const manual = isolated ? null : new ManualDelivery({ root: env.IG_ARCHIVE_DIR || '/downloads', dir, stateDir, settings: () => settings, log });
  const xDelivery = isolated || env.X_ENABLED === '0' ? null : new XDelivery({ root: env.IG_ARCHIVE_DIR || '/downloads', dir, stateDir, settings: () => settings, log });
  const ttDelivery = isolated ? null : new TikTokDelivery({ root: env.IG_ARCHIVE_DIR || "/downloads", dir, stateDir, settings: () => settings, log });
  const ttOk = { video: true, notice: true, content: true, story: true };
  const store=new SettingsStore({file:settingsFile(env),initial:settings});
  const earlyAcknowledged=new Map();
  let broker;
  const transact=async mutate=>{const started=performance.now(),previous=JSON.stringify(settings);settings=await store.transact(mutate);if(JSON.stringify(settings)!==previous)broker?.update(settings);record('settings_commit',performance.now()-started);};
  const persistSettings = async () => {const snapshot=structuredClone(settings);await transact(()=>snapshot);};
  const describe = id => describeUser(settings, id, stateDir, env.IG_WATCHDOG_DIR || '/app/watchdog-state');
  describe.admin = page => adminStatus(settings, stateDir, page);
  describe.platform = (id, platform) => platformStatus(settings.users[id], platform, stateDir, (file, fallback) => {
    try { return load(file, fallback); } catch { return fallback; }
  }, Date.now(), { settings, id });
  if(!isolated)refreshQueuedDescriptions(delivery, settings, describe);
  delivery.persist(); await persistSettings();
  const loopDelay=monitorEventLoopDelay({resolution:20});loopDelay.enable();
  let healthWriting=false;
  const health = async () => {if(healthWriting)return;healthWriting=true;try{record('event_loop',Math.max(0,loopDelay.percentile(95)/1e6));loopDelay.reset();await writeSnapshot(path.join(dir, 'health.json'), { performance:performanceSnapshot(),at: Date.now(), telegramOk: isolated ? broker?.health.telegramOk===true : telegramOk && xTelegramOk && ttOk.video && ttOk.notice && ttOk.content && ttOk.story, pollOk, lastPollAt, pending: isolated ? broker?.health.pending||0 : Object.keys(delivery.state.pending).length,deliveryReady:isolated?broker?.health.ready===true:true });}finally{healthWriting=false;}};
  const pressurePublisher=createPressurePublisher({stateDir,enabled:env.ARCHIVE_PRESSURE_ENABLED==='1',controlMetrics:performanceSnapshot,readServiceMetrics:()=>[broker?.health.performance],interactiveAge:()=>Math.max(0,...Object.values(settings.replies).filter(r=>Number.isFinite(r.at)&&Date.now()>=(r.retryAt||0)).map(r=>Date.now()-r.at))});
  const heartbeat = setInterval(()=>{void health().catch(()=>log('TELEGRAM_HEALTH_WRITE_FAILED',{reason:'CONTROL_STATE_OR_IO_ERROR'}));},15000);
  try {
    // Do not silently delete another deployment's webhook or pending updates.
    const webhook = await client.call('getWebhookInfo', {}, { polling: true });
    if (webhook?.url) throw Error('TELEGRAM_WEBHOOK_CONFIGURED');
    await client.call('setMyCommands', { commands: [{ command: 'menu', description: '開啟 Instagram／X／TikTok 選單' }, { command: 'status', description: '查看我的監看狀態' }, { command: 'add', description: '新增 IG 帳號，例如 /add alice' }, { command: 'ttadd', description: '新增 TikTok 帳號，例如 /ttadd alice' }, { command: 'xadd', description: '新增 X 帳號，例如 /xadd alice' }, { command: 'xhistory', description: '歷史回補，例如 /xhistory alice' }, { command: 'cancel', description: '取消目前操作' }] });
    await client.call('setChatMenuButton', { menu_button: { type: 'commands' } });
    if(isolated)broker=new DeliveryBroker({client,settings:()=>settings,env,log});
    await health(); log('TELEGRAM_CONTROL_STARTED');
    async function poll() {
      do {
        try {
          const updates = await client.call('getUpdates', { offset: settings.offset, timeout: args.includes('--once') ? 0 : 10, allowed_updates: ['message', 'callback_query'], limit: 50 }, { polling: true });
          if (!Array.isArray(updates)) throw Error('TELEGRAM_UPDATES_INVALID');
          for (const update of updates) {
            if(update.callback_query&&authorizeUpdate(settings,update)&&earlyAcknowledged.size<1000){
              earlyAcknowledged.set(`ack:${update.update_id}`,client.call('answerCallbackQuery',{callback_query_id:update.callback_query.id},{priority:true}).then(()=>true,()=>false));
            }
            await transact(candidate=>{applyUpdate(candidate, update, Date.now(), describe, env.ARCHIVE_EXPORT_ENABLED === '1' && exportServiceReady(env.EXPORT_DIR || '/exports'),
              platform => exportAccountNames(candidate, platform, { root: env.IG_ARCHIVE_DIR || '/downloads', stateDir }));});
          }
          const edits = completedHistoryPanels(settings, describe);
          if (edits.length) await transact(candidate => {
            for (const { id, messageId, panel, body } of edits) {
              const panels = candidate.users[id]?.historyPanels;
              if (JSON.stringify(panels?.[messageId]) !== JSON.stringify(panel)) continue;
              const sub = candidate.users[id][{ig:'targets', tt:'tiktokTargets', x:'xTargets'}[panel.platform]]?.[panel.name];
              if (sub) {
                sub.archivedHistory ||= {};
                sub.archivedHistory[panel.platform === 'tt' && sub.notifications?.like?.enabled ? 'likes' : 'default'] = true;
              }
              delete panels[messageId];
              candidate.replies[`archived:${id}:${messageId}`] = { method: 'editMessageText', userId: id, at: Date.now(), body };
            }
          });
          lastPollAt = Date.now(); pollOk = true;
        } catch (error) {
          if (stopping) return;
          if (!/^TELEGRAM_(?:ERROR_\d+|NETWORK_OR_RESPONSE_ERROR|RETRY_WAIT|UPDATES_INVALID)$/.test(error.message)) throw error;
          pollOk = false; log('TELEGRAM_CONTROL_POLL_FAILED', { reason: /^TELEGRAM_[A-Z0-9_]+$/.test(error.message) ? error.message : 'CONTROL_STATE_OR_IO_ERROR' });
          if (!args.includes('--once')) await wait(5000);
        }
      } while (!stopping && !args.includes('--once'));
    }
    async function replyDispatch() {
      do {
        if (env.ARCHIVE_EXPORT_ENABLED === '1') {
          try {await transact(candidate=>{ingestExportReports(candidate,env.EXPORT_DIR||'/exports');});}
          catch {log('ARCHIVE_EXPORT_REPORT_FAILED',{reason:'EXPORT_STATE_OR_IO_ERROR'});}
        }
        await flushReplies(() => settings, client, persistSettings, { stopping: () => stopping, log,transaction:transact,earlyAcknowledged });
        if (!args.includes('--once')) await wait(250);
      } while (!stopping && !args.includes('--once'));
    }
    async function dispatch() {
      do {
        const events = eventDirectory(env); fs.mkdirSync(events, { recursive: true });
        const names = fs.readdirSync(events).filter(n => /^[a-f0-9]{64}\.json$/.test(n)).slice(0, 100);
        const records = names.map(name => ({ file: path.join(events, name), event: load(path.join(events, name), null) })).sort((a,b) => a.event?.at - b.event?.at);
        for (const { file, event } of records) { delivery.ingest(event); fs.unlinkSync(file); }
        delivery.daily(Date.now(), describe);
        telegramOk = await delivery.drain(client, { stopping: () => stopping });
        if (!args.includes('--once')) await wait(1000);
      } while (!stopping && !args.includes('--once'));
    }
    async function manualDispatch() {
      do {
        await manual.drain(client, { stopping: () => stopping,
          externalDone: (key, userId) => key.startsWith('x:') ? xDelivery?.manualDone(key.slice(2), userId) : ttDelivery?.state.manualDone?.[key.slice(3)],
        });
        if (!args.includes('--once')) await wait(1000);
      } while (!stopping && !args.includes('--once'));
    }
    async function xDispatch() {
      if (!xDelivery) return;
      do {
        xTelegramOk = await xDelivery.drain(client, { stopping: () => stopping });
        if (!args.includes('--once')) await wait(1000);
      } while (!stopping && !args.includes('--once'));
    }
    async function tikTokDispatch(lane) {
      do {
        ttOk[lane] = await ttDelivery.drain(client, { stopping: () => stopping, lane });
        if (!args.includes("--once")) await wait(1000);
      } while (!stopping && !args.includes("--once"));
    }
    if (args.includes('--once')) await poll();
    await Promise.all(isolated?[poll(),replyDispatch()]:[replyDispatch(),dispatch(),manualDispatch(),xDispatch(),tikTokDispatch('notice'),tikTokDispatch('video'),tikTokDispatch('content'),tikTokDispatch('story')]);
    if (args.includes('--once')) await health();
    if (args.includes('--once')) process.exitCode = pollOk && telegramOk && xTelegramOk && ttOk.video && ttOk.notice && ttOk.content && ttOk.story ? 0 : 1;
  } finally {
    stopping = true; signal.abort(); clearInterval(heartbeat);loopDelay.disable();pressurePublisher.close();
    await broker?.stop();
    for (const name of ['SIGTERM', 'SIGINT']) process.off(name, stop);
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  run().catch(error => { log('TELEGRAM_CONTROL_FATAL', { reason: error.code || (/^[A-Z0-9_]+$/.test(error.message) ? error.message : 'UNEXPECTED_ERROR') }); process.exitCode = 1; });
}
