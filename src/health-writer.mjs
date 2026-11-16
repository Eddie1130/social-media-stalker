import fs from 'node:fs';
import { atomic } from './error-monitor.mjs';

const withoutTimestamp = ({ at, ...value }) => value;

// Keep meaningful changes immediate while bounding redundant heartbeat writes.
export function createHealthWriter(file, { intervalMs = 15000, select = withoutTimestamp, writer = atomic, clock = Date.now } = {}) {
  let signature, lastAt = null;
  return (value, { force = false, now = clock() } = {}) => {
    const next = JSON.stringify(select(value));
    if (!force && lastAt !== null && now >= lastAt && now - lastAt < intervalMs && next === signature && fs.existsSync(file)) return false;
    writer(file, { ...value, at: now });
    signature = next;
    lastAt = now;
    return true;
  };
}
