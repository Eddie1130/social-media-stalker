import { platformStatus } from './platform-status.mjs';
import { platforms } from './platform-menu.mjs';
import { load } from './error-monitor.mjs';

export function adminStatus(settings, stateDir, page = 0, now = Date.now()) {
  let readErrors = 0;
  const read = (file, fallback) => { try { return load(file, fallback); } catch { readErrors++; return fallback; } };
  const merged = {};
  for (const { key } of Object.values(platforms)) {
    merged[key] = Object.assign({}, ...settings.allowedIds.map(id => settings.users[id]?.[key] || {}));
  }
  const lines = [], totals = [];
  for (const [platform, config] of Object.entries(platforms)) {
    const status = platformStatus(merged, platform, stateDir, read, now, { settings, id: settings.ownerId });
    totals.push(`${config.title}：${Object.keys(status.accounts).length} 個帳號 · 待下載 ${status.pending}`);
    for (const [name, text] of Object.entries(status.accounts)) lines.push(`${config.title} ${text.replace(/ · 🔕$/, '')}\n待下載：${status.accountPending[name]}`);
  }
  const last = Math.max(0, Math.ceil(lines.length / 12) - 1);
  page = Math.min(Math.max(0, Number.isSafeInteger(page) ? page : 0), last);
  const button = (text, index) => ({ text, callback_data: `admin-status:${index}` });
  return {
    text: ['👑 所有監控帳號', ...totals, '', ...lines.slice(page * 12, page * 12 + 12),
      !lines.length ? '尚未新增帳號。' : `第 ${page + 1}/${last + 1} 頁`,
      '待下載為已發現的監控媒體數量，不含尚未掃描的內容及手動連結任務。',
      ...(readErrors ? ['⚠️ 部分狀態讀取失敗，數量可能不完整。'] : [])].join('\n'),
    reply_markup: { inline_keyboard: [
      ...(last ? [[...(page ? [button('上一頁', page - 1)] : []), ...(page < last ? [button('下一頁', page + 1)] : [])]] : []),
      [button('🔄 重新整理', page)], [{ text: '⬅️ 狀態', callback_data: 'status' }],
    ] },
  };
}
