"""Independent durable catalog scheduler; never shares LIVE recording threads."""

from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
import copy
import hashlib
import json
import logging
import os
import re
import random
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import traceback

from catalog_errors import classify_failure, safe_diagnostic, sqlite_busy
from catalog_metrics import record, snapshot as metrics_snapshot
from catalog_provider import identifier, media_url
from catalog_media import delivery_parts
from catalog_layout import migrate_media_layout, account_media
from archive_links import ensure_archive_link
from worker import atomic, cookies, subscriptions, needs_attention

KINDS = ("story", "post", "repost", "profile", "like")
PERIOD = {"post": 300, "repost": 300, "story": 120, "profile": 1800, "like": 600}
STOP = threading.Event()


def now_ms():
    return int(time.time() * 1000)


def invoke_provider(request, timeout):
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("catalog_provider.py"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = proc.communicate(json.dumps(request), timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return {"error": "TIKTOK_PROVIDER_TIMEOUT"}
    try:
        value = json.loads(output)
    except ValueError:
        return {"error": "TIKTOK_PROVIDER_RESPONSE_INVALID"}
    if not isinstance(value, dict) or proc.returncode and not value.get("error"):
        return {"error": "TIKTOK_PROVIDER_FAILED"}
    return value


def provider(name, kind, cursor="0", item_id=None):
    request = {"username": name, "kind": kind, "cursor": cursor, "cookies": cookies()}
    if item_id:
        request["itemId"] = item_id
    browser_enabled = os.getenv("TIKTOK_CATALOG_BROWSER", "1") == "1"
    saved_profile = (
        Path(os.getenv("TIKTOK_CATALOG_PROFILE", "/data/catalog-profile"))
        / ".cookie-version"
    )
    prefer_browser = browser_enabled and saved_profile.exists()
    request["browser"] = prefer_browser
    value = invoke_provider(request, 120 if prefer_browser else 90)
    if value.get("error") and browser_enabled:
        request["browser"] = not prefer_browser
        value = invoke_provider(request, 90 if prefer_browser else 120)
    if value.get("error"):
        reason = value["error"]
        raise RuntimeError(
            reason
            if isinstance(reason, str)
            and reason.startswith("TIKTOK_")
            and reason.replace("_", "").isalnum()
            else "TIKTOK_PROVIDER_FAILED"
        )
    return value


class SessionProvider:
    """Reuse one browser across types/targets rather than creating a new identity per page."""

    def __init__(self):
        self.browser = None
        self.name = None
        self.manual_required = False
        self.opened_at = None
        self.max_age = int(os.getenv("TIKTOK_CATALOG_BROWSER_MAX_AGE_SECONDS", "3600"))
        if self.max_age != 0 and not 300 <= self.max_age <= 86400:
            raise ValueError("TIKTOK_INVALID_BROWSER_MAX_AGE")

    def __call__(self, name, kind, cursor="0", item_id=None):
        started = time.perf_counter()
        try:
            for attempt in range(2):
                try:
                    return self._query(name, kind, cursor, item_id)
                except Exception as error:
                    failure = classify_failure(error)
                    if failure.category == "transport":
                        self.recover(failure)
                        raise
                    if attempt or not failure.retryable or STOP.is_set():
                        raise
                    if failure.category == "empty_response":
                        time.sleep(random.uniform(1, 3))
        finally:
            record("browser_query", (time.perf_counter()-started)*1000, {"platform":"tt","kind":kind})

    def recover(self, failure=None):
        try:
            self.close()
        except Exception:
            # The browser subprocess owner will reap the entire process group.
            pass
        finally:
            self.browser = self.name = self.opened_at = None
        record("browser_restart", 1, {"platform":"tt"})

    def _query(self, name, kind, cursor="0", item_id=None):
        if os.getenv("TIKTOK_CATALOG_BROWSER", "1") != "1":
            return provider(name, kind, cursor, item_id)
        if self.manual_required:
            raise RuntimeError("TIKTOK_CAPTCHA_REQUIRED")
        from catalog_regular_browser import RegularBrowserTransport
        from catalog_provider import fetch_page

        try:
            if self.browser and self.max_age and time.monotonic() - self.opened_at >= self.max_age:
                self.close()
            if self.browser is None:
                self.browser = RegularBrowserTransport(name, cookies())
                self.name = name
                self.opened_at = time.monotonic()
            else:
                self.browser.resume()
                if self.name != name or kind == "profile":
                    self.name = None
                    self.browser.navigate(name)
                    self.name = name
            request = {
                "username": name,
                "kind": kind,
                "cursor": cursor,
                "cookies": cookies(),
            }
            if item_id:
                request["itemId"] = item_id
            return fetch_page(request, self.browser)
        except Exception as error:
            if str(error) == "TIKTOK_CAPTCHA_REQUIRED":
                self.manual_required = True
            elif self.browser:
                broken = type(error).__name__ == "TargetClosedError" or any(
                    text in str(error).lower()
                    for text in (
                        "connection closed",
                        "target crashed",
                        "page crashed",
                        "browser has been closed",
                    )
                )
                try:
                    broken = broken or self.browser.page.is_closed()
                except Exception:
                    broken = True
                if broken:
                    try:
                        self.close()
                    finally:
                        self.browser = self.name = None
                    raise RuntimeError("TIKTOK_BROWSER_TRANSPORT_FAILED") from None
            raise
        finally:
            if self.browser:
                if self.manual_required:
                    self.close()
                else:
                    try:
                        self.browser.pause()
                    except Exception:
                        self.close()
                        raise RuntimeError("TIKTOK_BROWSER_TRANSPORT_FAILED") from None

    def idle(self):
        if self.browser and self.name is not None:
            self.name = None
            try:
                self.browser.park()
            except Exception:
                self.recover()

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        finally:
            self.browser = None
            self.name = self.opened_at = None


def safe_file(root, relative):
    file = (root / relative).resolve()
    if not file.is_relative_to(root.resolve()) or file.is_symlink():
        raise RuntimeError("TIKTOK_ARCHIVE_PATH_INVALID")
    return file


def download(url, file, kind, session=None, headers=None):
    if session is None:
        import requests

        session = requests.Session()
    client = session
    url = media_url(url)
    # Every redirect is validated before making the next request. Never attach TikTok cookies.
    for _ in range(6):
        response = client.get(
            url,
            stream=True,
            timeout=(15, 30),
            allow_redirects=False,
            headers={
                "Referer": "https://www.tiktok.com/",
                "User-Agent": "Mozilla/5.0",
                **{
                    k: v
                    for k, v in (headers or {}).items()
                    if k in ("User-Agent", "Referer")
                },
            },
        )
        if response.status_code in (301, 302, 303, 307, 308):
            from urllib.parse import urljoin

            following = response.headers.get("Location", "")
            response.close()
            url = media_url(urljoin(url, following))
            continue
        break
    else:
        raise RuntimeError("TIKTOK_MEDIA_REDIRECT_LIMIT")
    try:
        response.raise_for_status()
    except Exception:
        response.close()
        raise
    file.parent.mkdir(parents=True, exist_ok=True)
    part = file.with_suffix(".part")
    count = 0
    started = time.monotonic()
    try:
        with part.open("wb") as out:
            for chunk in response.iter_content(256 * 1024):
                if STOP.is_set() or time.monotonic() - started > 180:
                    raise RuntimeError("TIKTOK_DOWNLOAD_INTERRUPTED")
                count += len(chunk)
                if count > 20_000_000_000:
                    raise RuntimeError("TIKTOK_MEDIA_TOO_LARGE")
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        with part.open("rb") as inp:
            magic = inp.read(32)
        if count < 12:
            raise RuntimeError("TIKTOK_MEDIA_INCOMPLETE")
        if kind == "video":
            ext = "mp4" if b"ftyp" in magic[:20] else None
        else:
            ext = (
                "jpg"
                if magic.startswith(b"\xff\xd8\xff")
                else (
                    "png"
                    if magic.startswith(b"\x89PNG\r\n\x1a\n")
                    else (
                        "webp"
                        if magic.startswith(b"RIFF") and magic[8:12] == b"WEBP"
                        else None
                    )
                )
            )
        if not ext:
            raise RuntimeError("TIKTOK_MEDIA_SIGNATURE_INVALID")
        destination = file.with_suffix("." + ext)
        part.replace(destination)
        record("media_download",(time.monotonic()-started)*1000,{"platform":"tt","outcome":"ok"})
        record("media_bytes",count,{"platform":"tt"})
        return destination
    finally:
        response.close()
        part.unlink(missing_ok=True)


class Catalog:
    def __init__(
        self,
        root,
        state_dir,
        control,
        fetcher=provider,
        downloader=download,
        clock=now_ms,
    ):
        self.root, self.state_dir, self.control = (
            Path(root).resolve(),
            Path(state_dir),
            Path(control),
        )
        self.fetcher, self.downloader, self.clock = fetcher, downloader, clock
        self.active_names = None
        self.health_snapshot = {"targets": {}, "pending": 0, "phase": "running"}
        self.folder = self.state_dir / "tiktok/catalog"
        self.folder.mkdir(parents=True, exist_ok=True)
        os.chmod(self.folder, 0o700)
        file = self.folder / "catalog.sqlite"
        marker = file.with_suffix(".required")
        if marker.exists() and not file.exists():
            raise RuntimeError("TIKTOK_CATALOG_HISTORY_MISSING")
        self.db = sqlite3.connect(file)
        os.chmod(file, 0o600)
        self.db.executescript(
            """
          CREATE TABLE IF NOT EXISTS targets(id TEXT PRIMARY KEY, folder TEXT UNIQUE NOT NULL);
          CREATE TABLE IF NOT EXISTS streams(name TEXT, kind TEXT, data TEXT NOT NULL, PRIMARY KEY(name,kind));
          CREATE TABLE IF NOT EXISTS items(target TEXT, kind TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(target,kind,id));
          CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS items_work ON items(
            json_extract(data,'$.status'), coalesce(json_extract(data,'$.retryAt'),0));
          CREATE INDEX IF NOT EXISTS items_counts ON items(
            json_extract(data,'$.status'), json_extract(data,'$.username'), kind);
        """
        )
        atomic(marker, {"required": True})
        migrate_media_layout(self.root, self.db, self.folder)

    def read_settings(self):
        file=self.control / "settings.json"
        stat=file.stat();key=(stat.st_ino,stat.st_mtime_ns,stat.st_size)
        if getattr(self,"_settings_key",None)==key:return self._settings_cache
        value = json.loads(file.read_text())
        if value.get("version") != 1:
            raise RuntimeError("TIKTOK_SETTINGS_INVALID")
        self._settings_key=key;self._settings_cache=value
        return value

    def target_recipients(self, settings, name, kind=None):
        result = []
        for uid in settings["allowedIds"]:
            sub = settings["users"].get(uid, {}).get("tiktokTargets", {}).get(name)
            if not sub:
                continue
            pref = sub.get("notifications", {}).get(kind, {})
            if kind == "like" and not pref.get("enabled", False):
                continue
            result.append(
                {
                    "userId": uid,
                    "generation": sub["generation"],
                    "joinedAt": sub["joinedAt"],
                    "monitorOnly": sub.get("monitorOnly", False),
                    "historyAt": sub.get("historyAt", 0),
                    "enabled": pref.get("enabled", True),
                    "since": pref.get("since", sub["joinedAt"]),
                }
            )
        return result

    def stream(self, name, kind):
        row = self.db.execute(
            "SELECT data FROM streams WHERE name=? AND kind=?", (name, kind)
        ).fetchone()
        return (
            json.loads(row[0])
            if row
            else {
                "baseline": False,
                "cursor": "0",
                "failures": 0,
                "nextAt": 0,
                "generations": {},
            }
        )

    def save_stream(self, name, kind, value):
        self.db.execute(
            "INSERT OR REPLACE INTO streams VALUES(?,?,?)",
            (name, kind, json.dumps(value)),
        )

    def folder_for(self, uid, name):
        row = self.db.execute(
            "SELECT folder FROM targets WHERE id=?", (uid,)
        ).fetchone()
        if row:
            return row[0]
        folder = name
        if self.db.execute(
            "SELECT 1 FROM targets WHERE folder=?", (folder,)
        ).fetchone():
            folder += "_" + uid
        self.db.execute("INSERT INTO targets VALUES(?,?)", (uid, folder))
        return folder

    def notice(self, name, text, recipients, identity, notice_key=None, notice_kind=None):
        event = {
            "username": name,
            "kind": "notice",
            "at": self.clock(),
            "text": text,
            "files": [],
            "recipients": [
                {"userId": r["userId"], "generation": r["generation"]}
                for r in recipients
            ],
        }
        if notice_key:
            event.update(noticeKey=notice_key, noticeKind=notice_kind)
        key = hashlib.sha256(identity.encode()).hexdigest()
        self.db.execute(
            "INSERT OR IGNORE INTO outbox VALUES(?,?)", (key, json.dumps(event))
        )

    def poll(self, name, kind, settings):
        state, now = self.stream(name, kind), self.clock()
        recipients = self.target_recipients(settings, name, kind)
        requested = max((r["historyAt"] for r in recipients), default=0)
        if requested > state.get("historyAt", 0):
            state.update(historyAt=requested, backfill=True, cursor="0", nextAt=0)
        if now < state["nextAt"] or not recipients:
            return
        original_state = copy.deepcopy(state)
        try:
            result = self.fetcher(name, kind, state.get("cursor", "0"))
            uid = identifier(result["userId"])
            if state.get("userId") and state["userId"] != uid:
                raise RuntimeError("TIKTOK_ACCOUNT_ID_CHANGED")
            if (
                result.get("kind") != kind
                or result.get("username") != name
                or result.get("version") != 1
            ):
                raise RuntimeError("TIKTOK_PROVIDER_IDENTITY_INVALID")
            folder = self.folder_for(uid, name)
            if kind == "profile":
                profile = result["profile"]
                item = {
                    "id": hashlib.sha256(
                        json.dumps(profile, sort_keys=True).encode()
                    ).hexdigest(),
                    "authorId": uid,
                    "author": name,
                    "caption": f"暱稱：{profile['nickname']}\n簡介：{profile['bio']}",
                    "publishedAt": 0,
                    "assets": [{"url": media_url(result["avatar"]), "type": "photo"}],
                    "profile": profile,
                }
                digest = item["id"]
                if digest == state.get("profileHash"):
                    rows = []
                else:
                    item["id"] = digest + "_" + str(now)
                    rows = [item]
                state["profileHash"] = digest
                more = False
            else:
                rows, more = result["items"], result["hasMore"]
                if (
                    not isinstance(rows, list)
                    or not isinstance(more, bool)
                    or more
                    and not rows
                ):
                    raise RuntimeError("TIKTOK_PROVIDER_PAGE_INVALID")
                if more and str(result["cursor"]) == state.get("cursor", "0"):
                    raise RuntimeError("TIKTOK_PAGINATION_STALLED")
            monitor = all(r["monitorOnly"] for r in recipients) and kind in ("post", "repost", "like", "story")
            initial = monitor and not state["baseline"] and not state.get("backfill")
            frontier = set(state.get("head", []))
            overlap = any(item["id"] in frontier for item in rows)
            if state.get("cursor", "0") == "0":
                state["pendingHead"] = [item["id"] for item in rows]
            cutoff = min(r["joinedAt"] for r in recipients)
            reached_old = False
            all_known = bool(rows)
            for item in rows:
                iid = item["id"]
                if kind != "profile":
                    identifier(iid)
                if monitor and not state.get("backfill"):
                    old = kind in ("post", "story") and item.get("publishedAt", 0) < cutoff
                    if old or initial and kind in ("repost", "like"):
                        reached_old = iid == rows[-1]["id"]
                        continue
                    if iid in frontier and kind in ("repost", "like"):
                        break
                previous = self.db.execute(
                    "SELECT data FROM items WHERE target=? AND kind=? AND id=?",
                    (uid, kind, iid),
                ).fetchone()
                if previous:
                    record = json.loads(previous[0])
                    if item.get("unresolvedReason"):
                        if record["status"] == "unresolved":
                            record["item"] = item
                            record["reason"] = item["unresolvedReason"]
                    else:
                        if record["status"] == "unresolved":
                            record.update(
                                item=item,
                                status="pending",
                                reason=None,
                                failures=0,
                                retryAt=0,
                            )
                        # Refresh expiring URLs without changing original observation or recipients.
                        record["item"]["assets"] = item["assets"]
                        caption_changed = record["item"].get("caption") != item.get(
                            "caption"
                        )
                        record["item"]["caption"] = item.get("caption", "")
                        if caption_changed and record["status"] == "ready":
                            category = {
                                "post": "posts",
                                "repost": "reposts",
                                "story": "stories",
                                "profile": "profile",
                                "like": "likes",
                            }[kind]
                            destination = safe_file(
                                self.root,
                                Path("tiktok") / record["folder"] / category / iid,
                            )
                            (destination / "caption.txt").write_text(
                                record["item"]["caption"], encoding="utf-8"
                            )
                            metadata_file = destination / "metadata.json"
                            metadata = json.loads(metadata_file.read_text())
                            metadata["caption"] = record["item"]["caption"]
                            atomic(metadata_file, metadata)
                    if kind == "story":
                        new = [
                            r
                            for r in recipients
                            if r["enabled"]
                            and record.get("observedGenerations", {}).get(r["userId"])
                            != r["generation"]
                        ]
                        if new:
                            copy_record = {
                                **record,
                                "recipients": [
                                    {
                                        "userId": r["userId"],
                                        "generation": r["generation"],
                                    }
                                    for r in new
                                ],
                                "at": now,
                            }
                            if record["status"] == "ready":
                                self.queue_event(copy_record, record["files"])
                            else:
                                record.setdefault("extraRecipients", []).append(
                                    {"at": now, "recipients": copy_record["recipients"]}
                                )
                    record["observedGenerations"] = {
                        r["userId"]: r["generation"] for r in recipients
                    }
                    self.db.execute(
                        "UPDATE items SET data=? WHERE target=? AND kind=? AND id=?",
                        (json.dumps(record), uid, kind, iid),
                    )
                    continue
                all_known = False
                eligible = [
                    r
                    for r in recipients
                    if r["enabled"]
                    and (
                        kind == "story"
                        or initial
                        or state["baseline"]
                        and state["generations"].get(r["userId"]) == r["generation"]
                    )
                    and not state.get("backfill")
                    and now >= r["joinedAt"]
                    and now >= r["since"]
                ]
                record = {
                    "username": name,
                    "folder": folder,
                    "target": uid,
                    "kind": kind,
                    "item": item,
                    "at": now,
                    "recipients": [
                        {"userId": r["userId"], "generation": r["generation"]}
                        for r in eligible
                    ],
                    "observedGenerations": {
                        r["userId"]: r["generation"] for r in recipients
                    },
                    "files": [],
                    "status": (
                        "unresolved" if item.get("unresolvedReason") else "pending"
                    ),
                    "reason": item.get("unresolvedReason"),
                    "failures": 0,
                    "retryAt": 0,
                }
                self.db.execute(
                    "INSERT INTO items VALUES(?,?,?,?)",
                    (uid, kind, iid, json.dumps(record)),
                )
            if (
                rows
                and all_known
                and not state.get("backfill")
                and not state["baseline"]
                and state.get("cursor", "0") != "0"
            ):
                raise RuntimeError("TIKTOK_PAGINATION_DUPLICATE")
            if state.get("alerted", state["failures"] >= 3):
                self.notice(
                    name,
                    f"TikTok @{name} {kind} 監控已恢復。",
                    recipients,
                    f"recovery:{name}:{kind}:{state['nextAt']}",
                    notice_key=f"catalog:{name}:{kind}", notice_kind="recovery",
                )
            # Explicit backfills traverse every page, including previously seen pages.
            finished = not more or not state.get("backfill") and (
                state["baseline"] and all_known or monitor and (overlap or reached_old)
            )
            if finished:
                state["head"] = state.pop("pendingHead", [])
                state["backfill"] = False
            state.update(
                userId=uid,
                cursor="0" if finished else str(result["cursor"]),
                baseline=state["baseline"] or finished,
                failures=0,
                alerted=False,
                reason=None,
                errorType=None,
                lastSuccess=now,
                nextAt=now + (PERIOD[kind] * 1000 if finished else 30000),
                generations=(
                    {r["userId"]: r["generation"] for r in recipients}
                    if finished
                    else state["generations"]
                ),
                phase="監看中" if finished else "分頁封存中",
            )
            self.save_stream(name, kind, state)
            self.db.commit()
        except Exception as error:
            self.db.rollback()
            if isinstance(error, sqlite3.Error):
                raise
            if STOP.is_set():return
            # Neither a failed commit nor a later error may publish a cursor,
            # baseline or profile hash whose page was rolled back.
            state = original_state
            network_error = re.search(r"\bnet::(ERR_[A-Z_]+)\b", str(error))
            # Trace locations identify integration failures without logging private
            # exception messages, request URLs, cookies, or response bodies.
            print(json.dumps({
                "event": "TIKTOK_CATALOG_POLL_FAILED",
                "username": name,
                "kind": kind,
                "exception": type(error).__name__,
                "failureCode": classify_failure(error).safe_code,
                "failureCategory": classify_failure(error).category,
                "browserDiagnostic": getattr(error, "browser_diagnostic", None),
                "networkError": network_error.group(1) if network_error else None,
                "frames": [
                    {"file": Path(frame.filename).name, "line": frame.lineno,
                     "function": frame.name}
                    for frame in traceback.extract_tb(error.__traceback__)[-8:]
                ],
            }), flush=True)
            state["failures"] += 1
            previous_reason = state.get("reason")
            state["reason"] = (
                str(error)
                if isinstance(error, RuntimeError) and str(error).startswith("TIKTOK_")
                else "TIKTOK_CATALOG_FETCH_FAILED"
            )
            state["errorType"] = type(error).__name__
            abnormal = state.get("alerted") or state["failures"] >= 3 or needs_attention(error)
            state["phase"] = "異常／重試中" if abnormal else f"等待重試（{state['failures']}/3）"
            state["nextAt"] = now + min(3600000, 30000 * 2 ** min(state["failures"], 6))
            retry_after=getattr(error,"retry_after",0)
            if isinstance(retry_after,(int,float)) and 0<retry_after<=604800:state["nextAt"]=max(state["nextAt"],now+retry_after*1000)
            self.save_stream(name, kind, state)
            if abnormal and (not state.get("alerted") or needs_attention(error) and state["reason"] != previous_reason):
                self.notice(
                    name,
                    f"TikTok @{name} {kind} 監控失敗：{state['reason']}，將持續重試。",
                    recipients,
                    f"error:{name}:{kind}:{now}",
                    notice_key=f"catalog:{name}:{kind}", notice_kind="error",
                )
                state["alerted"] = True
                self.save_stream(name, kind, state)
            self.db.commit()

    def ready_items(self, status, names, limit, stories_first=False):
        """Filter and bound work in SQLite, without loading archived payloads."""
        names = list(names)
        if not names or limit <= 0:
            return []
        placeholders = ",".join("?" for _ in names)
        order = "ORDER BY CASE kind WHEN 'story' THEN 0 ELSE 1 END" if stories_first else ""
        return self.db.execute(
            f"""SELECT target,kind,id,data FROM items
              WHERE json_extract(data,'$.status')=?
                AND coalesce(json_extract(data,'$.retryAt'),0)<=?
                AND json_extract(data,'$.username') IN ({placeholders})
              {order} LIMIT ?""",
            [status, self.clock(), *names, limit],
        ).fetchall()

    def repair(self, settings, limit=1):
        """Rehydrate quarantined IDs independently of discovery pagination."""
        active = subscriptions(settings)
        attempted = 0
        for target, kind, iid, data in self.ready_items("unresolved", active, limit):
            record = json.loads(data)
            if (
                record["status"] != "unresolved"
                or record["username"] not in active
                or record.get("retryAt", 0) > self.clock()
            ):
                continue
            if STOP.is_set() or attempted >= limit:
                break
            attempted += 1
            try:
                result = self.fetcher(record["username"], kind, "0", iid)
                item = result["items"][0]
                if (
                    item.get("id") != iid
                    or item.get("unresolvedReason")
                    or not item.get("assets")
                ):
                    raise RuntimeError("TIKTOK_ITEM_IDENTITY_OR_MEDIA_INVALID")
                record.update(
                    item=item, status="pending", reason=None, failures=0, retryAt=0
                )
                if record.pop("repairAlerted", False):
                    self.notice(
                        record["username"],
                        f"TikTok @{record['username']} 有一筆待補查內容已恢復，將繼續下載。",
                        self.target_recipients(settings, record["username"]),
                        f"repaired:{target}:{kind}:{iid}:{record['at']}",
                        notice_key=f"repair:{target}:{kind}:{iid}", notice_kind="recovery",
                    )
            except Exception as error:
                if isinstance(error, sqlite3.Error):
                    raise
                if STOP.is_set():
                    self.db.rollback()
                    return
                record["failures"] += 1
                reason = str(error)
                record["reason"] = (
                    reason
                    if reason.startswith("TIKTOK_")
                    and reason.replace("_", "").isalnum()
                    else "TIKTOK_ITEM_REPAIR_FAILED"
                )
                record["retryAt"] = self.clock() + min(
                    3600000, 30000 * 2 ** min(record["failures"], 6)
                )
                if not record.get("repairAlerted") and (record["failures"] >= 3 or needs_attention(error)):
                    self.notice(
                        record["username"],
                        f"TikTok @{record['username']} 有一筆內容連續補查失敗，其餘內容會繼續封存。",
                        self.target_recipients(settings, record["username"]),
                        f"repair-error:{target}:{kind}:{iid}:{record['at']}",
                        notice_key=f"repair:{target}:{kind}:{iid}", notice_kind="error",
                    )
                    record["repairAlerted"] = True
            self.db.execute(
                "UPDATE items SET data=? WHERE target=? AND kind=? AND id=?",
                (json.dumps(record), target, kind, iid),
            )
            self.db.commit()

    def download_asset(self, asset, destination):
        for url in asset.get("urls", [asset["url"]]):
            try:
                kwargs = {"headers": asset["headers"]} if asset.get("headers") else {}
                return self.downloader(url, destination, asset["type"], **kwargs)
            except Exception as error:
                if STOP.is_set() or needs_attention(error):
                    raise
        raise RuntimeError("TIKTOK_MEDIA_DOWNLOAD_FAILED")

    def archive(self, record, reusable=None):
        item, folder, kind = record["item"], record["folder"], record["kind"]
        if record.get("manual"):
            folder = str(Path("manual") / folder)
        category = {
            "post": "posts",
            "repost": "reposts",
            "story": "stories",
            "profile": "profile",
            "like": "likes",
        }[kind]
        relative = Path("tiktok") / folder / category / item["id"]
        destination = safe_file(self.root, relative)
        destination.mkdir(parents=True, exist_ok=True)
        files = []
        for index, asset in enumerate(item["assets"], 1):
            # Origin IDs share media across targets and activities. Profile snapshots use their hash.
            shared = safe_file(
                self.root,
                Path("tiktok") / folder / "media" / f'{item["id"]}_{index:02d}',
            )
            existing = [
                p
                for p in shared.parent.glob(shared.name + ".*")
                if p.suffix in (".jpg", ".png", ".webp", ".mp4")
            ]
            saved = (
                existing[0]
                if len(existing) == 1
                else (reusable[index - 1] if reusable is not None else account_media(
                    self.root, self.db, folder, item["id"], index
                )) or self.download_asset(asset, shared)
            )
            local = destination / f"{index:02d}{saved.suffix}"
            link_status = ensure_archive_link(self.root, saved, local)
            if link_status in ("different", "cross_device"):
                print(json.dumps({"event": "archive_link_conflict", "reason": link_status,
                                  "path": str(local.relative_to(self.root))}), file=sys.stderr, flush=True)
            files.extend(
                str(part.relative_to(self.root)) for part in delivery_parts(local,stop=STOP)
            )
        metadata = {k: v for k, v in item.items() if k != "assets"}
        metadata.update(
            kind=kind, target=record["target"], observedAt=record["at"], files=files
        )
        atomic(destination / "metadata.json", metadata)
        caption = destination / "caption.txt"
        caption.write_text(item.get("caption", ""), encoding="utf-8")
        return files

    def queue_event(self, record, files):
        item, kind, iid = record["item"], record["kind"], record["item"]["id"]
        text = (
            f"TikTok [{kind}] @{record['username']}\n原作者：@{item.get('author', '')}\n"
            + item.get("caption", "")
        )
        if kind in ("post", "repost", "story", "like"):
            text += f"\nhttps://www.tiktok.com/@{item.get('author') or '_'}/video/{iid}"
        event = {
            "username": record["username"],
            "archiveFolder": record["folder"],
            "kind": kind,
            "at": record["at"],
            "text": text,
            "mediaCaption": text[:900],
            "files": files,
            "recipients": record["recipients"],
        }
        key = hashlib.sha256(
            f'{record["target"]}:{record["kind"]}:{record["item"]["id"]}:{record["at"]}'.encode()
        ).hexdigest()
        self.db.execute(
            "INSERT OR IGNORE INTO outbox VALUES(?,?)", (key, json.dumps(event))
        )

    def drain(self, settings, limit=50, budget_seconds=15):
        """Parallelize media IO only; browser and SQLite stay on this thread."""
        names = subscriptions(settings)
        candidates = list(self.ready_items("pending", names, limit, stories_first=True))
        deadline = time.monotonic() + budget_seconds
        inflight, busy = {}, set()
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="tiktok-media") as pool:
            while candidates or inflight:
                while candidates and len(inflight) < 3 and not STOP.is_set() and time.monotonic() < deadline:
                    # Aliases and different accounts reuse origin media. Serialize
                    # each origin ID so later jobs can reuse the completed file.
                    selected = None
                    for index, row in enumerate(candidates):
                        record = json.loads(row[3])
                        key = record["item"]["id"]
                        if key not in busy:
                            selected = index, row, record, key
                            break
                    if selected is None:
                        break
                    index, (target, kind, iid, _), record, key = selected
                    candidates.pop(index)
                    if record["status"] != "pending" or record["username"] not in names or record.get("retryAt", 0) > self.clock():
                        continue
                    try:
                        if record["failures"] and kind != "profile":
                            refreshed = self.fetcher(record["username"], kind, "0", iid)["items"][0]
                            if refreshed["id"] != iid:
                                raise RuntimeError("TIKTOK_ITEM_IDENTITY_INVALID")
                            record["item"]["assets"] = refreshed["assets"]
                            self.db.execute("UPDATE items SET data=? WHERE target=? AND kind=? AND id=?",(json.dumps(record),target,kind,iid));self.db.commit()
                        folder = str(Path("manual") / record["folder"]) if record.get("manual") else record["folder"]
                        reusable = [
                            account_media(self.root, self.db, folder, record["item"]["id"], i)
                            for i in range(1, len(record["item"]["assets"]) + 1)
                        ]
                        if STOP.is_set() or time.monotonic() >= deadline:
                            break
                        future = pool.submit(self.archive, record, reusable)
                    except Exception as error:
                        if isinstance(error, sqlite3.Error):
                            raise
                        future = Future()
                        future.set_exception(error)
                    inflight[future] = ((target, kind, iid, record), key)
                    busy.add(key)
                if not inflight:
                    break
                done, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for future in done:
                    job, key = inflight.pop(future)
                    busy.remove(key)
                    self.finish_archive(job, future, settings)
                # A deadline/stop only prevents new dispatch. All started jobs
                # must finish and be checkpointed before returning to the scheduler.
                if STOP.is_set() or time.monotonic() >= deadline:
                    candidates.clear()

    def finish_archive(self, job, future, settings):
        target, kind, iid, started_record = job
        row=self.db.execute("SELECT data FROM items WHERE target=? AND kind=? AND id=?",(target,kind,iid)).fetchone()
        if not row:return
        record=json.loads(row[0])
        if record.get("status")!="pending":return
        try:
            files = future.result()
            if len(record["item"]["assets"])!=len(started_record["item"]["assets"]):
                return  # Original durable pending job will reconcile additional media.
            if record["item"].get("caption")!=started_record["item"].get("caption"):
                folder=("manual/" if record.get("manual") else "")+record["folder"]
                category={"post":"posts","repost":"reposts","story":"stories","profile":"profile","like":"likes"}[kind]
                destination=safe_file(self.root,Path("tiktok")/folder/category/iid)
                metadata={k:v for k,v in record["item"].items() if k!="assets"}
                metadata.update(kind=kind,target=target,observedAt=record["at"],files=files)
                atomic(destination/"metadata.json",metadata)
                temp=destination/"caption.txt.tmp"
                with temp.open("w") as out:
                    out.write(record["item"].get("caption", ""));out.flush();os.fsync(out.fileno())
                temp.replace(destination/"caption.txt")
            self.queue_event(record, files)
            for extra in record.get("extraRecipients", []):
                self.queue_event({**record, **extra}, files)
            record.pop("extraRecipients", None)
            if record.get("archiveAlerted"):
                self.notice(
                    record["username"], "", self.target_recipients(settings, record["username"]),
                    f"archive-recovered:{target}:{kind}:{iid}",
                    notice_key=f"archive:{target}:{kind}:{iid}", notice_kind="recovery",
                )
            record.update(status="ready", files=files, reason=None, failures=0, archiveAlerted=False)
        except Exception as error:
            if isinstance(error, sqlite3.Error):
                raise
            if STOP.is_set():
                self.db.rollback()
                return
            record.pop("downloadRefreshed", None)
            record["failures"] += 1
            record["reason"] = "TIKTOK_ARCHIVE_FAILED"
            record["retryAt"] = self.clock() + min(
                3600000, 30000 * 2 ** min(record["failures"], 6)
            )
            if not record.get("archiveAlerted") and (record["failures"] >= 3 or needs_attention(error)):
                self.notice(
                    record["username"],
                    f"TikTok @{record['username']} 內容下載失敗，原進度已保留，將持續重試。",
                    self.target_recipients(settings, record["username"]),
                    f'archive:{target}:{kind}:{iid}:{record["failures"]}',
                    notice_key=f"archive:{target}:{kind}:{iid}", notice_kind="error",
                )
                record["archiveAlerted"] = True
        self.db.execute(
            "UPDATE items SET data=? WHERE target=? AND kind=? AND id=?",
            (json.dumps(record), target, kind, iid),
        )
        self.db.commit()

    def flush(self):
        events = self.state_dir / "tiktok/events"
        for key, data in self.db.execute("SELECT id,data FROM outbox").fetchall():
            file = events / (key + ".json")
            atomic(file, json.loads(data))
            self.db.execute("DELETE FROM outbox WHERE id=?", (key,))
            self.db.commit()

    def health(self):
        if getattr(self,"coordinator",None):
            current=time.monotonic()
            if current-getattr(self,"_last_health_scan",0)<15:return
            self._last_health_scan=current
        targets = {}
        for name, kind, data in self.db.execute("SELECT name,kind,data FROM streams"):
            if self.active_names is not None and name not in self.active_names:
                continue
            stream = json.loads(data)
            targets.setdefault(name, {})[kind] = {
                k: stream.get(k)
                for k in ("phase", "failures", "reason", "baseline", "lastSuccess")
            }
            report = targets[name][kind]
            report["consecutiveFailures"] = stream["failures"]
            report["queryAgeMs"] = max(0,self.clock()-stream["lastSuccess"]) if stream.get("lastSuccess") else None
            report["dueLagMs"] = max(0,self.clock()-stream.get("nextAt",0))
            report["backoffUntil"] = stream.get("nextAt") if stream["failures"] else None
            if not stream.get("alerted") and stream["failures"] < 3:
                report["failures"] = 0
                report["reason"] = None
        pending = unresolved = 0
        for name, kind, status, count in self.db.execute(
            """SELECT json_extract(data,'$.username'),kind,json_extract(data,'$.status'),count(*)
               FROM items WHERE json_extract(data,'$.status') IN ('pending','unresolved')
               GROUP BY json_extract(data,'$.status'),json_extract(data,'$.username'),kind"""
        ):
            if (
                self.active_names is not None
                and name not in self.active_names
            ):
                continue
            if status == "pending":
                pending += count
                value = targets.setdefault(name, {}).setdefault(kind, {})
                value["pending"] = count
            if status == "unresolved":
                unresolved += count
                value = targets.get(name, {}).get(kind)
                if value is not None:
                    value["unresolved"] = value.get("unresolved", 0) + count
        for kinds in targets.values():
            for value in kinds.values():
                if value.get("unresolved"):
                    value["phase"] += f"（{value['unresolved']} 筆待補查）"
        self.health_snapshot = {
            "targets": targets,
            "pending": pending,
            "unresolved": unresolved,
            "manualRequired": getattr(self.fetcher, "manual_required", False) is True,
            "phase": "running",
        }
        if not getattr(self,"coordinator",None):self.heartbeat()

    def heartbeat(self):
        atomic(
            self.folder / "health.json", {**self.health_snapshot, "at": self.clock(), "storageBlocked": getattr(self, "storage_blocked", False), "performance": metrics_snapshot()}
        )

    def manual_requests(self, settings):
        import re
        from urllib.parse import urlparse, urljoin, parse_qs
        import requests

        self.db.execute("CREATE TABLE IF NOT EXISTS manual_jobs(id TEXT PRIMARY KEY, attempts INTEGER, done INTEGER)")
        for rid, request in settings.get("tiktokRequests", {}).items():
            uid = request.get("userId")
            if uid not in settings["allowedIds"] or not re.fullmatch(r"[1-9]\d{0,19}-\d+-\d+", rid) or not rid.startswith(uid + "-"):
                continue
            row = self.db.execute("SELECT attempts,done FROM manual_jobs WHERE id=?", (rid,)).fetchone()
            attempts, done = row or (0, 0)
            if done:
                continue
            event = {"username": "manual", "kind": "notice", "at": request["at"], "text": "TikTok 連結下載失敗，請稍後重新傳送。", "files": [], "recipients": [{"userId": uid, "generation": rid}], "requestId": rid, "requestUrl": request["url"]}
            try:
                url = request["url"]
                for _ in range(6):
                    parsed = urlparse(url)
                    if parsed.scheme != "https" or parsed.hostname not in ("tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com") or parsed.username or parsed.password or parsed.port:
                        raise ValueError("TIKTOK_INVALID_LINK")
                    live = re.fullmatch(r"/@([A-Za-z0-9_][A-Za-z0-9_.]{0,23})/live/?", parsed.path)
                    shared = re.fullmatch(r"/share/live/(\d{1,30})/?", parsed.path)
                    if live or shared:
                        room = shared[1] if shared else parse_qs(parsed.query).get("room_id", [None])[0]
                        if room is not None and not re.fullmatch(r"\d{1,30}", room):
                            raise ValueError("TIKTOK_ROOM_INVALID")
                        pending = self.state_dir / "tiktok/live-requests" / (rid + ".json")
                        atomic(pending, {**request, "name": live[1].lower() if live else None, "room": room})
                        self.db.execute("INSERT OR REPLACE INTO manual_jobs VALUES(?,?,1)", (rid, attempts))
                        self.db.commit()
                        return
                    match = re.fullmatch(r"/@([A-Za-z0-9_][A-Za-z0-9_.]{0,23})/(?:video|photo)/(\d{1,30})/?", parsed.path)
                    if match:
                        break
                    if not re.fullmatch(r"/(?:t/)?[A-Za-z0-9_-]{1,128}/?", parsed.path):
                        raise ValueError("TIKTOK_INVALID_LINK")
                    response = requests.get(url, allow_redirects=False, timeout=20, stream=True)
                    try:
                        if response.status_code not in (301, 302, 303, 307, 308):
                            raise ValueError("TIKTOK_SHORT_LINK_FAILED")
                        url = urljoin(url, response.headers["Location"])
                    finally:
                        response.close()
                else:
                    raise ValueError("TIKTOK_REDIRECT_LIMIT")
                name, iid = match.groups()
                name = name.lower()
                item = self.fetcher(name, "post", item_id=iid)["items"][0]
                if item["id"] != iid:
                    raise ValueError("TIKTOK_ITEM_IDENTITY_INVALID")
                record = {"item": item, "folder": name, "kind": "post", "target": item["authorId"], "at": request["at"], "manual": True}
                event.update(username=name, kind="post", manual=True, files=(self.coordinator.archive_manual(record,self.read_settings()) if getattr(self,"coordinator",None) else self.archive(record)), text=f"TikTok @{name}\n{item.get('caption', '')}\n{url}", mediaCaption=f"@{name}\n{url}\n{item.get('caption', '')}"[:900])
                done = 1
            except Exception as error:
                if isinstance(error, sqlite3.Error):
                    raise
                if STOP.is_set():
                    self.db.rollback()
                    return
                attempts += 1
                done = int(attempts >= 3)
            if done:
                key = hashlib.sha256(("manual:" + rid).encode()).hexdigest()
                self.db.execute("INSERT OR IGNORE INTO outbox VALUES(?,?)", (key, json.dumps(event)))
            self.db.execute("INSERT OR REPLACE INTO manual_jobs VALUES(?,?,?)", (rid, attempts, done))
            self.db.commit()
            break

    def tick(self):
        settings = self.read_settings()
        self.active_names = set(subscriptions(settings))
        if os.getenv("IG_TELEGRAM_CONTROL", "1") == "1":
            if getattr(self,"coordinator",None):
                from catalog_scheduler import select_stream
                self.coordinator.pump(settings)
                self.manual_requests(settings)
                selected=select_stream(self,settings,self.clock())
                if selected:self.poll(*selected,settings)
                self.coordinator.refresh_one(settings)
                self.repair(settings)
                self.coordinator.pump(settings)
                self.flush();self.health()
                return
            self.manual_requests(settings)
            for name in subscriptions(settings):
                for kind in KINDS:
                    if STOP.is_set():
                        return
                    self.poll(name, kind, settings)
                    self.health()
            self.drain(settings)
            self.repair(settings)
        self.flush()
        self.health()


def run_catalog_loop(catalog, session, stop):
    busy_failures = 0
    while not stop.is_set():
        try:
            catalog.tick()
        except sqlite3.OperationalError as error:
            if not sqlite_busy(error):
                raise
            catalog.db.rollback()
            catalog.storage_blocked = True
            busy_failures += 1
            delay = min(30, 2 ** min(busy_failures - 1, 5))
            try:
                print(json.dumps({"event": "TIKTOK_CATALOG_STORAGE_BUSY",
                                  "failureCode": "TIKTOK_SQLITE_BUSY",
                                  "retrySeconds": delay,
                                  **safe_diagnostic(error)}), flush=True)
            except OSError:
                pass
            stop.wait(delay)
            continue
        catalog.storage_blocked = False
        busy_failures = 0
        session.idle()
        stop.wait(.25)


def heartbeat_loop(catalog, stop, errors, interval=15):
    while not stop.wait(interval):
        try:
            catalog.heartbeat()
        except Exception as error:
            errors.append(error)
            stop.set()
            try:
                print(json.dumps({"event": "TIKTOK_CATALOG_HEARTBEAT_FAILED",
                                  "failureCode": classify_failure(error).safe_code,
                                  **safe_diagnostic(error)}), flush=True)
            except OSError:
                # A broken logging pipe must not disable shutdown or expose the
                # original private exception through a thread traceback.
                pass
            return


def main():
    logging.disable(logging.CRITICAL)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    from catalog_query import BrowserWorker
    from catalog_scheduler import ArchiveCoordinator
    session = BrowserWorker(stop=STOP)
    catalog = Catalog(
        os.getenv("IG_ARCHIVE_DIR", "/downloads"),
        os.getenv("IG_STATE_DIR", "/app/state"),
        os.getenv("IG_CONTROL_DIR", "/app/control"),
        fetcher=session,
    )

    catalog.coordinator = ArchiveCoordinator(catalog, STOP)
    session.pump = lambda: catalog.coordinator.pump(catalog.read_settings())

    heartbeat_errors = []
    heartbeat = threading.Thread(target=heartbeat_loop,
                                 args=(catalog, STOP, heartbeat_errors), daemon=True)
    catalog.health()
    catalog.heartbeat()
    heartbeat.start()
    try:
        run_catalog_loop(catalog, session, STOP)
    finally:
        STOP.set()
        heartbeat.join(timeout=2)
        try:
            session.close()
            catalog.coordinator.close(catalog.read_settings())
        finally:
            catalog.db.close()
            atomic(catalog.folder / "health.json", {"at": now_ms(), "phase": "stopped"})
    if heartbeat_errors:
        raise RuntimeError("TIKTOK_CATALOG_HEARTBEAT_FAILED") from None


if __name__ == "__main__":
    main()
