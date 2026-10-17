"""Loopback-only research workbench over frozen decisions and explicit assumptions."""

import argparse
import gzip
import hashlib
import json
import multiprocessing
import secrets
import subprocess
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .artifacts import _versions
from .event_replay import digest, verify_frozen

ASSETS = Path(__file__).with_name("workbench_static")
DEFAULT_DATA = Path(__file__).with_name("workbench_data")
MAX_BODY = 2_000_000


def _load(path):
    if path.stat().st_size > 20_000_000:
        raise ValueError("数据文件超过 20 MB 上限")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        text = stream.read(20_000_001)
    if len(text) > 20_000_000:
        raise ValueError("解压后数据超过 20 MB 上限")
    return json.loads(text)


def _worker(connection, frozen, assumptions):
    from .strategy_exploration import propose_exploration

    try:
        connection.send({"status": "succeeded", "report": propose_exploration(frozen, assumptions)})
    except Exception as exc:
        connection.send({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        connection.close()


class Workbench:
    def __init__(self, data_dir=DEFAULT_DATA, timeout=45):
        self.root = Path(data_dir).resolve()
        self.timeout = timeout
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.jobs = {}
        self.revealed = {}
        self.races = {}
        self.cases = {}
        catalog = _load(self.root / "catalog.json")
        self.data_hashes = catalog["file_sha256"]
        for row in catalog["races"]:
            race = deepcopy(row)
            records = self._data(race["decisions"])
            race["cases"] = []
            for frozen in records:
                verify_frozen(frozen)
                key = f"{race['id']}:{frozen['decision_sha256']}"
                if key in self.cases:
                    raise ValueError("重复冻结记录")
                self.cases[key] = (race, frozen)
                race["cases"].append({"id": key, "cutoff": frozen["cutoff"]})
            self.races[race["id"]] = race
        if not self.cases:
            raise ValueError("没有可用的冻结记录")
        try:
            self.commit = subprocess.check_output(
                ["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            self.commit = "unavailable; source hashes recorded in export"

    def _path(self, name):
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("数据文件必须位于配置目录内")
        return path

    def _data(self, name):
        path = self._path(name)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != self.data_hashes.get(name):
            raise ValueError(f"示例数据 SHA256 不匹配：{name}")
        return _load(path)

    def catalog(self):
        return {
            "schema_version": 1,
            "token": self.token,
            "timeout_seconds": self.timeout,
            "races": [
                {k: r[k] for k in ("id", "name", "partition", "cases")} for r in self.races.values()
            ],
        }

    def quality_context(self, case):
        race, frozen = self.cases[case]
        if "quality_context" not in race:
            return None
        return self._data(race["quality_context"])[frozen["decision_sha256"]]

    def quality(self, case):
        from .prefix_quality import assess_prefix

        return assess_prefix(self.cases[case][1], self.quality_context(case))

    def decision(self, case):
        _, frozen = self.cases[case]
        return {
            "frozen": frozen,
            "workbench_version": self.commit,
            "prefix_quality": self.quality(case),
        }

    def assumptions(self, case, driver, field="nearby", drivers=None):
        from .workbench_inputs import prefix_assumptions

        race, frozen = self.cases[case]
        return prefix_assumptions(
            frozen, self._data(race["assumptions"]), driver, field, drivers, self.quality(case)
        )

    def start(self, document):
        case, driver = document["case"], document["driver"]
        frozen = self.cases[case][1]
        assumptions = document["assumptions"]
        if document.get("acknowledged") is not True:
            raise ValueError("请先确认已检查人工假设、模拟范围和未知库存")
        if assumptions["planning"]["ego"] != driver:
            raise ValueError("假设中的 ego 必须与当前所选车手一致")
        # The browser is not trusted to preserve the original frozen record.
        verify_frozen(frozen)
        with self.lock:
            if sum(j["status"] == "running" for j in self.jobs.values()) >= 2:
                raise ValueError("已有两个任务运行中；请等待或取消后重试")
            if len(self.jobs) >= 100:
                oldest = next((k for k, j in self.jobs.items() if j["status"] != "running"), None)
                if oldest:
                    del self.jobs[oldest]
                else:
                    raise ValueError("任务存储已满，请稍后重试")
            key = secrets.token_urlsafe(18)
            job = {
                "id": key,
                "case": case,
                "driver": driver,
                "status": "running",
                "started": time.monotonic(),
                "assumptions": deepcopy(assumptions),
                "assumptions_sha256": digest(assumptions),
                "cancel": False,
            }
            self.jobs[key] = job
        threading.Thread(target=self._run, args=(key, frozen, assumptions), daemon=True).start()
        return {"id": key, "status": "running", "timeout_seconds": self.timeout}

    def _run(self, key, frozen, assumptions):
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(target=_worker, args=(send, frozen, assumptions), daemon=True)
        result = {"status": "failed", "error": "模拟进程意外退出，请检查输入后重试"}
        try:
            process.start()
            send.close()
            while True:
                with self.lock:
                    job = self.jobs[key]
                    cancel = job["cancel"]
                    elapsed = time.monotonic() - job["started"]
                if cancel:
                    result = {"status": "cancelled", "error": "任务已取消；没有新模拟结果"}
                    break
                if elapsed >= self.timeout:
                    result = {
                        "status": "timed_out",
                        "error": f"模拟超过 {self.timeout:g} 秒，已停止。请减少候选或情景后重试",
                    }
                    break
                if receive.poll(0.05):
                    result = receive.recv()
                    break
                if not process.is_alive():
                    break
        except (OSError, EOFError, RuntimeError) as exc:
            result = {"status": "failed", "error": f"模拟无法完成：{exc}"}
        finally:
            if process.pid:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=2)
            receive.close()
            send.close()
            with self.lock:
                self.jobs[key].update(result)
                self.jobs[key]["elapsed_seconds"] = time.monotonic() - self.jobs[key]["started"]

    def job(self, key):
        with self.lock:
            job = self.jobs[key]
            return {
                k: deepcopy(v)
                for k, v in job.items()
                if k not in {"started", "assumptions", "cancel"}
            } | {"elapsed_seconds": job.get("elapsed_seconds", time.monotonic() - job["started"])}

    def reveal(self, case, driver):
        race, frozen = self.cases[case]
        if driver not in {c["id"] for c in frozen["state"]["cars"]}:
            raise ValueError("所选车手不在此记录中")
        # Outcome file is opened only in response to this explicit operation.
        evaluations = self._data(race["reveals"])
        evaluation = evaluations[frozen["decision_sha256"]]
        if evaluation["decision_sha256"] != frozen["decision_sha256"]:
            raise ValueError("揭晓结果与冻结记录哈希不匹配")
        row = next(r for r in evaluation["drivers"] if r["driver_id"] == driver)
        key = secrets.token_urlsafe(18)
        record = {
            "id": key,
            "case": case,
            "driver": driver,
            "revealed_at_utc": datetime.now(timezone.utc).isoformat(),
            "evaluation": row,
            "interpretation": "事实观测评分；不验证模拟策略收益或模型终点名次",
        }
        with self.lock:
            self.revealed[key] = record
        return record

    def export(self, document):
        case, driver = document["case"], document["driver"]
        race, frozen = self.cases[case]
        job = self.jobs[document["job_id"]]
        if job["case"] != case or job["driver"] != driver or job["status"] != "succeeded":
            raise ValueError("导出任务与当前比赛、时点或车手不匹配，或尚未完成")
        if document.get("assumptions_sha256") != job["assumptions_sha256"]:
            raise ValueError("假设已修改，请重新比较后导出")
        reveal = self.revealed.get(document.get("reveal_id"))
        if reveal and (reveal["case"] != case or reveal["driver"] != driver):
            raise ValueError("揭晓记录与当前选择不匹配")
        evidence = self._data(race["evidence"])
        payload = {
            "schema_version": 1,
            "kind": "local_workbench_decision_record",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "versions": _versions(),
            "workbench_git_commit": self.commit,
            "workbench_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "frontend_source_sha256": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ASSETS.iterdir())
            },
            "dataset_file_sha256": self.data_hashes,
            "selection": {"case": case, "driver": driver, "race": race["name"]},
            "frozen_decision": frozen,
            "prefix_context": self.quality_context(case),
            "prefix_quality": self.quality(case),
            "assumptions": job["assumptions"],
            "assumptions_sha256": job["assumptions_sha256"],
            "exploration": job["report"],
            "reveal": reveal,
            "source_evidence": evidence,
            "evidence_note": "完整档案证据含事后审计；导出包不再是盲测输入。",
            "interpretation": "冻结事实、人工假设和模拟预测分别保存；无事实策略收益结论",
        }
        payload["record_sha256"] = digest(payload)
        return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "F1LocalWorkbench/1"

    def log_message(self, *_args):
        pass

    def _send(self, value, status=200, content_type="application/json; charset=utf-8"):
        body = (
            value
            if isinstance(value, bytes)
            else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        app = self.server.app
        try:
            if parsed.path == "/api/catalog":
                return self._send(app.catalog())
            if parsed.path == "/api/decision":
                return self._send(app.decision(query["case"][0]))
            if parsed.path == "/api/assumptions":
                return self._send(
                    app.assumptions(
                        query["case"][0],
                        query["driver"][0],
                        query.get("field", ["nearby"])[0],
                        query.get("drivers", [""])[0].split(","),
                    )
                )
            if parsed.path.startswith("/api/jobs/"):
                return self._send(app.job(parsed.path.rsplit("/", 1)[1]))
            files = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            if parsed.path in files:
                name, kind = files[parsed.path]
                return self._send((ASSETS / name).read_bytes(), content_type=kind)
            self._send({"error": "未找到页面或接口"}, 404)
        except (KeyError, ValueError, OSError, TypeError, StopIteration) as exc:
            self._send({"error": f"无法读取所选记录：{exc}"}, 400)

    def do_POST(self):
        app = self.server.app
        if not secrets.compare_digest(self.headers.get("X-Workbench-Token", ""), app.token):
            return self._send({"error": "页面会话已失效，请刷新后重试"}, 403)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                raise ValueError("请求必须是小于 2 MB 的 JSON")
            document = json.loads(self.rfile.read(size))
            if self.path == "/api/explore":
                return self._send(app.start(document), 202)
            if self.path == "/api/reveal":
                return self._send(app.reveal(document["case"], document["driver"]))
            if self.path == "/api/export":
                return self._send(app.export(document))
            if self.path == "/api/cancel":
                with app.lock:
                    app.jobs[document["job_id"]]["cancel"] = True
                return self._send({"status": "cancellation_requested"})
            self._send({"error": "未找到接口"}, 404)
        except (KeyError, ValueError, OSError, TypeError, StopIteration) as exc:
            self._send({"error": f"操作未完成：{exc}"}, 400)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument(
        "--timeout", type=float, default=45, help="Simulation limit in seconds (0..300)"
    )
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 300 or not 0 <= args.port <= 65535:
        parser.error("port must be 0..65535 and timeout must be >0..300")
    try:
        app = Workbench(args.data_dir, timeout=args.timeout)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(2, f"启动失败：{exc}\n")
    server.app = app
    print(f"F1 策略工作台：http://127.0.0.1:{server.server_port}  （Ctrl+C 停止）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with app.lock:
            for job in app.jobs.values():
                job["cancel"] = True
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
