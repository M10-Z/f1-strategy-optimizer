"""Bounded, read-only OpenF1 historical browsing, isolated from forecasting.

No credentials, subscription, live stream, prediction fitting or holdout scoring.
"""

import hashlib
import json
import math
import re
import threading
import time
from collections import OrderedDict, deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://api.openf1.org/v1/"
MAX_RESPONSE_BYTES = 2_000_000
MAX_CACHE_BYTES = 16_000_000
MAX_CACHE_ENTRIES = 64
PROTECTED_SESSIONS = {9539, 9566, 9574, 9582}
PROTECTED_COUNTRIES_2024 = {"Spain", "Hungary", "Belgium", "Netherlands"}
LIMITATIONS = [
    "历史赛后观测，不是预测、独立验证或实时建议",
    "事件日期来自历史归档；received_at_utc只是当前HTTP拉取完成时刻",
    "没有核验当年的消息发布时间，历史数据可能包含赛后修订",
    "不会将本面板数据加入现有冻结预测、模拟或揭晓流程",
]


class HistoryError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HistoryError("历史API重定向已拒绝；未访问其他地址", 502)


def integer(value, name, minimum=1, maximum=999999):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise HistoryError(f"{name}必须是明确整数，不支持latest或任意URL")
    result = int(value)
    if not minimum <= result <= maximum:
        raise HistoryError(f"{name}超出支持范围")
    return result


def timestamp(value):
    if not isinstance(value, str):
        raise HistoryError("历史会话缺少可靠时间信息", 502)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timezone missing")
        return result.astimezone(timezone.utc)
    except ValueError as exc:
        raise HistoryError("历史会话时间格式无效", 502) from exc


def _reject_constant(value):
    raise ValueError(f"Nonstandard JSON constant: {value}")


class HistoryAPI:
    def __init__(self, *, opener=None, now=None, ttl_seconds=3600, min_interval=1.0):
        self.opener = opener or build_opener(_NoRedirect())
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.ttl = ttl_seconds
        self.min_interval = min_interval
        self.lock = threading.RLock()
        self.network_gate = threading.Lock()
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.request_times = deque()

    def _fetch(self, kind, params, max_rows):
        if kind not in {"sessions", "drivers", "laps", "stints"}:
            raise HistoryError("未允许的数据类型")
        url = BASE_URL + kind + "?" + urlencode(sorted(params.items()))
        # The only caller-supplied data are validated numeric selectors.
        with self.lock:
            now_mono = time.monotonic()
            cached = self.cache.get(url)
            if cached and now_mono - cached["saved_at"] <= self.ttl:
                self.cache.move_to_end(url)
                return deepcopy(cached["rows"]), {**cached["receipt"], "cache_status": "hit"}
        if not self.network_gate.acquire(blocking=False):
            raise HistoryError("已有历史API请求处理中，请稍后重试；没有排队新请求", 429)
        try:
            # Another request may have refreshed or evicted the entry before
            # this caller acquired the network gate. Never reuse that snapshot.
            with self.lock:
                cached = self.cache.get(url)
                if cached and time.monotonic() - cached["saved_at"] <= self.ttl:
                    self.cache.move_to_end(url)
                    return deepcopy(cached["rows"]), {**cached["receipt"], "cache_status": "hit"}
            return self._fetch_network(url, max_rows, cached)
        finally:
            self.network_gate.release()

    def _fetch_network(self, url, max_rows, cached):
        now_mono = time.monotonic()
        while self.request_times and now_mono - self.request_times[0] >= 60:
            self.request_times.popleft()
        if len(self.request_times) >= 30:
            raise HistoryError("历史API请求已达每分钟30次上限，请稍后重试", 429)
        if self.request_times:
            wait = self.min_interval - (now_mono - self.request_times[-1])
            if wait > 0:
                time.sleep(wait)
        self.request_times.append(time.monotonic())
        started_mono = time.monotonic()
        started = self.now().isoformat()
        try:
            request = Request(url, headers={"User-Agent": "F1-Historical-Workbench/0.1"})
            with self.opener.open(request, timeout=12) as response:
                if response.geturl() != url:
                    raise HistoryError("历史API返回非预期地址", 502)
                length = response.headers.get("Content-Length")
                if length and int(length) > MAX_RESPONSE_BYTES:
                    raise HistoryError("历史API响应超过2MB上限", 502)
                deadline = time.monotonic() + 12
                chunks, size = [], 0
                read_chunk = getattr(response, "read1", response.read)
                while True:
                    if time.monotonic() > deadline:
                        raise HistoryError("历史API正文读取超时", 502)
                    chunk = read_chunk(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise HistoryError("历史API响应超过2MB上限", 502)
                raw = b"".join(chunks)
                received = self.now().isoformat()
                status = response.status
                if status != 200:
                    raise HistoryError("历史API未成功返回数据", 502)
            rows = json.loads(raw, parse_constant=_reject_constant)
            if not isinstance(rows, list) or len(rows) > max_rows:
                raise HistoryError("历史API数据数量或格式不符合约定", 502)
            if any(not isinstance(row, dict) for row in rows):
                raise HistoryError("历史API记录格式无效", 502)
        except (HTTPError, URLError, HTTPException, OSError, ValueError, RecursionError) as exc:
            if cached:
                return deepcopy(cached["rows"]), {
                    **cached["receipt"],
                    "cache_status": "stale_fallback",
                    "warning": "本次拉取失败，显示该同一查询此前缓存；不是新数据",
                }
            status = 429 if isinstance(exc, HTTPError) and exc.code == 429 else 502
            if isinstance(exc, HistoryError):
                raise exc
            raise HistoryError("历史API暂不可用或响应无效；没有替代或编造数据", status) from exc
        receipt = {
            "url": url,
            "request_started_at_utc": started,
            "received_at_utc": received,
            "retrieved_at_utc": received,
            "http_status": status,
            "request_elapsed_monotonic_seconds": time.monotonic() - started_mono,
            "receipt_time_semantics": "local_system_utc_after_http_body_read",
            "receipt_clock_accuracy": "unknown",
            "raw_bytes": len(raw),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "cache_status": "miss",
        }
        with self.lock:
            current = self.cache.pop(url, None)
            if current:
                self.cache_bytes -= current["size"]
            self.cache[url] = {
                "rows": rows,
                "receipt": receipt,
                "saved_at": time.monotonic(),
                "size": len(raw),
            }
            self.cache_bytes += len(raw)
            while len(self.cache) > MAX_CACHE_ENTRIES or self.cache_bytes > MAX_CACHE_BYTES:
                _, removed = self.cache.popitem(last=False)
                self.cache_bytes -= removed["size"]
        return deepcopy(rows), dict(receipt)

    def _source(self, receipts):
        statuses = {row["cache_status"] for row in receipts}
        received = min(row["received_at_utc"] for row in receipts)
        return {
            "provider": "OpenF1",
            "urls": [row["url"] for row in receipts],
            "url": receipts[-1]["url"],
            "retrieved_at_utc": received,
            "received_at_utc": received,
            "latest_response_received_at_utc": max(row["received_at_utc"] for row in receipts),
            "received_time_summary": "oldest_component_receipt; see individual receipts",
            "served_at_utc": self.now().isoformat(),
            "availability_basis": "post_event_download",
            "event_time_basis": "provider_archive_event_time_not_publication_time",
            "live": False,
            "source_publication_verified": False,
            "cache_status": "stale_fallback"
            if "stale_fallback" in statuses
            else "hit"
            if statuses == {"hit"}
            else "miss",
            "receipts": receipts,
            "warnings": [row["warning"] for row in receipts if row.get("warning")],
            "storage": "bounded_in_memory_cache; resets_on_server_restart",
        }

    def _session(self, row):
        key = integer(row.get("session_key"), "session_key")
        year = integer(row.get("year"), "year", 2023, self.now().year)
        start, end = timestamp(row.get("date_start")), timestamp(row.get("date_end"))
        if end <= start:
            raise HistoryError("比赛结束时间早于开始时间", 502)
        reason = None
        if key in PROTECTED_SESSIONS or (
            year == 2024 and row.get("country_name") in PROTECTED_COUNTRIES_2024
        ):
            reason = "封存验证赛事，禁止通过历史面板读取其比赛数据"
        elif row.get("session_name") != "Race" or row.get("session_type") != "Race":
            reason = "当前仅支持正式Race历史会话"
        elif row.get("is_cancelled") is True:
            reason = "该比赛已取消"
        elif end > self.now() - timedelta(hours=24):
            reason = "仅允许已结束至少24小时的历史比赛；不接实时或未来会话"
        return {
            "session_key": key,
            "meeting_key": integer(row.get("meeting_key"), "meeting_key"),
            "year": year,
            "meeting_name": f"{year} {row.get('country_name') or row.get('location') or key}",
            "session_name": row.get("session_name"),
            "location": row.get("location"),
            "country_name": row.get("country_name"),
            "date_start": start.isoformat(),
            "date_end": end.isoformat(),
            "available": reason is None,
            "blocked_reason": reason,
        }

    def sessions(self, year):
        year = integer(year, "year", 2023, self.now().year)
        rows, receipt = self._fetch("sessions", {"year": year, "session_name": "Race"}, 100)
        races = [self._session(row) for row in rows]
        if any(row["year"] != year for row in races):
            raise HistoryError("返回赛事不属于所选年份", 502)
        if len({row["session_key"] for row in races}) != len(races):
            raise HistoryError("重复会话标识", 502)
        return {
            "races": sorted(races, key=lambda row: row["date_start"]),
            "source": self._source([receipt]),
            "limitations": LIMITATIONS,
        }

    def _selected_session(self, session_key):
        key = integer(session_key, "session_key")
        if key in PROTECTED_SESSIONS:
            raise HistoryError("封存验证赛事禁止读取")
        rows, receipt = self._fetch("sessions", {"session_key": key}, 1)
        if len(rows) != 1 or rows[0].get("session_key") != key:
            raise HistoryError("找不到唯一匹配的历史会话", 502)
        session = self._session(rows[0])
        if not session["available"]:
            raise HistoryError(session["blocked_reason"])
        return session, receipt

    @staticmethod
    def _check_identity(rows, session, driver_number=None):
        for row in rows:
            if (row.get("session_key"), row.get("meeting_key")) != (
                session["session_key"],
                session["meeting_key"],
            ):
                raise HistoryError("数据会话/赛事标识不匹配，拒绝混入其他比赛", 502)
            if driver_number is not None and row.get("driver_number") != driver_number:
                raise HistoryError("数据车手与选择不匹配", 502)

    def _drivers(self, session):
        rows, receipt = self._fetch("drivers", {"session_key": session["session_key"]}, 40)
        self._check_identity(rows, session)
        drivers = []
        for row in rows:
            drivers.append(
                {
                    "driver_number": integer(row.get("driver_number"), "driver_number", 1, 99),
                    "full_name": row.get("full_name") or row.get("broadcast_name") or "Unknown",
                    "name_acronym": row.get("name_acronym"),
                    "team_name": row.get("team_name"),
                }
            )
        if len({row["driver_number"] for row in drivers}) != len(drivers):
            raise HistoryError("车手编号重复", 502)
        return sorted(drivers, key=lambda row: row["driver_number"]), receipt

    def drivers(self, session_key):
        session, first = self._selected_session(session_key)
        drivers, second = self._drivers(session)
        return {
            "session": session,
            "drivers": drivers,
            "source": self._source([first, second]),
            "limitations": LIMITATIONS,
        }

    def history(self, session_key, driver_number):
        number = integer(driver_number, "driver_number", 1, 99)
        session, first = self._selected_session(session_key)
        drivers, second = self._drivers(session)
        driver = next((row for row in drivers if row["driver_number"] == number), None)
        if driver is None:
            raise HistoryError("所选车手不属于该比赛")
        params = {"session_key": session["session_key"], "driver_number": number}
        laps, third = self._fetch("laps", params, 500)
        stints, fourth = self._fetch("stints", params, 100)
        for rows in (laps, stints):
            self._check_identity(rows, session, number)
        seen = set()
        for row in laps:
            lap = integer(row.get("lap_number"), "lap_number", 1, 500)
            if lap in seen:
                raise HistoryError("圈号重复，拒绝静默覆盖", 502)
            seen.add(lap)
            if row.get("date_start") is not None:
                event = timestamp(row["date_start"])
                if (
                    not timestamp(session["date_start"]) - timedelta(hours=2)
                    <= event
                    <= (timestamp(session["date_end"]) + timedelta(hours=2))
                ):
                    raise HistoryError("圈开始时间超出所选会话", 502)
            duration = row.get("lap_duration")
            if duration is not None and (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or duration <= 0
            ):
                raise HistoryError("圈时包含无效数值", 502)
        stint_numbers = set()
        for row in stints:
            for name, lower in (
                ("stint_number", 1),
                ("lap_start", 1),
                ("lap_end", 1),
                ("tyre_age_at_start", 0),
            ):
                if row.get(name) is not None:
                    value = row[name]
                    if type(value) is not int or not lower <= value <= 500:
                        raise HistoryError(f"轮胎分段字段{name}无效", 502)
            if row.get("stint_number") is not None:
                if row["stint_number"] in stint_numbers:
                    raise HistoryError("轮胎分段编号重复", 502)
                stint_numbers.add(row["stint_number"])
            if row.get("lap_start") is not None and row.get("lap_end") is not None:
                if row["lap_start"] > row["lap_end"]:
                    raise HistoryError("轮胎分段结束圈早于开始圈", 502)
            compound = row.get("compound")
            if compound is not None and (
                not isinstance(compound, str) or not compound.strip() or len(compound) > 64
            ):
                raise HistoryError("轮胎配方字段格式无效", 502)
        return {
            "session": session,
            "driver": driver,
            "laps": sorted(laps, key=lambda row: row["lap_number"]),
            "stints": stints,
            "source": self._source([first, second, third, fourth]),
            "mode": "historical_observations_only",
            "forecast_created": False,
            "limitations": LIMITATIONS,
        }
