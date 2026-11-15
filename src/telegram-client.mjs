import { telegramApiBase } from './telegram-endpoint.mjs';
import path from 'node:path';
import { atomic, load } from './error-monitor.mjs';

export class TelegramClient {
  constructor({ token, dir, signal, fetchImpl = fetch, baseUrl = telegramApiBase(), sleep = ms => new Promise(resolve => setTimeout(resolve, ms)) }) {
    if (!/^\d+:[A-Za-z0-9_-]+$/.test(token || '')) throw Error('INVALID_TELEGRAM_CONFIG');
    Object.assign(this, { token, signal, fetchImpl, sleep, baseUrl });
    this.file = path.join(dir, 'api-rate.json');
    this.rate = load(this.file, { retryAt: 0 });
    if (!Number.isFinite(this.rate.retryAt) || this.rate.retryAt < 0) throw Error('INVALID_TELEGRAM_RATE_STATE');
    this.chats = new Map(); this.nextAt = 0;
    this.slots = []; this.scheduling = false; this.wakeSlots = null;
    this.signal?.addEventListener('abort', () => this.wakeSlots?.(), { once: true });
  }
  acquireSlot(chat, priority) {
    return new Promise((resolve, reject) => {
      this.slots.push({ chat, priority, resolve, reject });
      this.wakeSlots?.();
      if (!this.scheduling) void this.scheduleSlots();
    });
  }
  async scheduleSlots() {
    this.scheduling = true;
    let now = Date.now();
    try {
      while (this.slots.length) {
        if (this.signal?.aborted) throw Error('TELEGRAM_STOPPING');
        now = Math.max(now, Date.now());
        const readyAt = slot => Math.max(this.nextAt, this.chats.get(slot.chat) || 0);
        const ready = this.slots.filter(slot => readyAt(slot) <= now);
        const slot = ready.find(item => item.priority) || ready[0];
        if (!slot) {
          const at = Math.min(...this.slots.map(readyAt));
          // New interactive work can interrupt a wait for a media chat. Do not
          // reserve future slots: that lets many media lanes block every chat.
          const wake = new Promise(resolve => { this.wakeSlots = () => resolve(false); });
          try {
            const elapsed = await Promise.race([this.sleep(at - now).then(() => true), wake]);
            if (elapsed) now = Math.max(at, Date.now());
          } finally { this.wakeSlots = null; }
          continue;
        }
        this.slots.splice(this.slots.indexOf(slot), 1);
        this.nextAt = now + 40;
        if (slot.chat) this.chats.set(slot.chat, now + 1100);
        slot.resolve();
      }
    } catch (error) {
      for (const slot of this.slots.splice(0)) slot.reject(error);
    } finally { this.scheduling = false; }
  }
  async call(method, body, { polling = false, priority = false, files = [], timeoutMs, beforeRequest } = {}) {
    if (this.signal?.aborted) throw Error('TELEGRAM_STOPPING');
    if (Date.now() < this.rate.retryAt) throw Error('TELEGRAM_RETRY_WAIT');
    if (!polling) {
      const acknowledgement = method === 'answerCallbackQuery';
      await this.acquireSlot(acknowledgement ? '' : String(body.chat_id || ''), priority || acknowledgement);
      if (Date.now() < this.rate.retryAt) throw Error('TELEGRAM_RETRY_WAIT');
    }
    let payload = JSON.stringify(body), headers = { 'content-type': 'application/json' };
    if (files.length) {
      payload = new FormData(); headers = {};
      for (const [key, value] of Object.entries(body)) payload.append(key, typeof value === 'object' ? JSON.stringify(value) : String(value));
      for (const file of files) payload.append(file.name, file.blob, file.filename);
    }
    if (this.signal?.aborted) throw Error('TELEGRAM_STOPPING');
    beforeRequest?.();
    let response, data;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/bot${this.token}/${method}`, {
        method: 'POST', headers, body: payload,
        signal: AbortSignal.any([...(this.signal ? [this.signal] : []), AbortSignal.timeout(timeoutMs || (polling ? 25000 : (files.length || /file:\/\//.test(JSON.stringify(body))) && this.baseUrl !== 'https://api.telegram.org' ? 3600000 : 20000))]),
      });
      data = await response.json();
    } catch { throw Error('TELEGRAM_NETWORK_OR_RESPONSE_ERROR'); }
    if (!response.ok || data.ok !== true) {
      // Telegram returns 400 for a successful no-op edit. Treat only this exact case as acknowledged.
      if (method === 'editMessageText' && data.error_code === 400 && /^Bad Request: message is not modified/.test(data.description || '')) return true;
      const retry = Number(data.parameters?.retry_after);
      if (Number.isFinite(retry) && retry > 0) { this.rate.retryAt = Date.now() + retry * 1000; atomic(this.file, this.rate); }
      const error = Error(`TELEGRAM_ERROR_${Number.isInteger(data.error_code) ? data.error_code : response.status}`);
      if (data.error_code === 400 && /message to edit not found|message can't be edited/.test(data.description || '')) error.messageUnavailable = true;
      if (method === 'deleteMessage' && data.error_code === 400 && /message to delete not found/.test(data.description || '')) return true;
      throw error;
    }
    return data.result;
  }
}
