"""Verify and reproduce an exported workbench simulation offline, without outcomes."""

import argparse
import json
from copy import deepcopy
from pathlib import Path

from .event_replay import digest, verify_frozen
from .strategy_exploration import _engine_manifest, propose_exploration


def replay_record(record):
    document = deepcopy(record)
    expected = document.pop("record_sha256", None)
    if digest(document) != expected:
        raise ValueError("导出记录哈希不匹配；文件已改变或不完整")
    frozen, assumptions = document["frozen_decision"], document["assumptions"]
    verify_frozen(frozen)
    if digest(assumptions) != document["assumptions_sha256"]:
        raise ValueError("假设哈希不匹配")
    stored = document["exploration"]
    if stored["engine_source_sha256"] != _engine_manifest():
        raise ValueError("模拟引擎版本不同；请恢复导出记录指定的 Git 版本再重放")
    # source_evidence and reveal are deliberately never passed to the simulator.
    reproduced = propose_exploration(frozen, assumptions)
    if digest(reproduced) != digest(stored):
        raise ValueError("重放结果与导出模拟不同；不能宣称已复现")
    return {
        "status": "exact_match",
        "record_sha256": expected,
        "exploration_sha256": digest(reproduced),
        "model_scope": reproduced["model_scope"],
        "rollouts": reproduced["budget"]["rollouts_executed"],
        "future_evidence_used": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    args = parser.parse_args(argv)
    try:
        result = replay_record(json.loads(args.record.read_text()))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"重放失败：{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
