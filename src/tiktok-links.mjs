export const tikTokLinkPattern = /(?:https?:\/\/)?(?:(?:www|vm|vt)\.)?tiktok\.com\/[^\s<>"']+/gi;
export function parseTikTokLink(raw) {
  const u = new URL(/^https?:\/\//i.test(raw) ? raw : 'https://' + raw);
  if (u.protocol !== 'https:' || u.username || u.password || u.port || !['tiktok.com','www.tiktok.com','vm.tiktok.com','vt.tiktok.com'].includes(u.hostname)) throw Error('TIKTOK_INVALID_LINK');
  if (/^\/@[A-Za-z0-9_][A-Za-z0-9_.]{0,23}\/live\/?$/.test(u.pathname)) {
    const room = u.searchParams.get('room_id');
    return u.origin + u.pathname + (room && /^\d{1,30}$/.test(room) ? '?room_id=' + room : '');
  }
  if (/^\/share\/live\/\d{1,30}\/?$/.test(u.pathname)) return u.origin + u.pathname;
  if (!/^\/@[a-zA-Z0-9_][a-zA-Z0-9_.]{0,23}\/(?:video|photo)\/\d{1,30}\/?$/.test(u.pathname) && !(['vm.tiktok.com','vt.tiktok.com'].includes(u.hostname) && /^\/[A-Za-z0-9_-]{1,128}\/?$/.test(u.pathname)) && !/^\/t\/[A-Za-z0-9_-]{1,128}\/?$/.test(u.pathname)) throw Error('TIKTOK_INVALID_LINK');
  return u.origin + u.pathname;
}
