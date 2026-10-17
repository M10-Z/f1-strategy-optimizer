"""Small starter product: source, wheel, exact runtime dependencies and real cached sample."""

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path


def main():
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-dir", type=Path, default=repo / "output/freshness-product")
    parser.add_argument("--archive", type=Path,
                        default=repo.parent / "f1-workbench-starter-20261017.zip")
    parser.add_argument("--profile", choices=["freshness", "horizon"], default="freshness")
    args = parser.parse_args()
    stage = args.product_dir / "stage/f1-research-workbench"
    archive = args.archive
    if stage.exists() or archive.exists():
        raise ValueError("Preserve prior product; use a new build directory/name")
    stage.mkdir(parents=True)
    shutil.copytree(
        repo / "src/f1_strategy_optimizer",
        stage / "src/f1_strategy_optimizer",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for path in (repo / "delivery").iterdir():
        if path.is_file():
            shutil.copy2(path, stage / path.name)
    for name in ("LICENSE", "pyproject.toml", "README.md"):
        shutil.copy2(repo / name, stage / name)
    if args.profile == "horizon":
        (stage / "recovery").mkdir()
        bundle = (stage / "recovery/source.bundle").resolve()
        subprocess.run(["git", "bundle", "create", str(bundle), "--all"], cwd=repo, check=True)
        shutil.copytree(repo / "docs", stage / "docs")
        (stage / "examples").mkdir()
        shutil.copy2(repo / "examples/observation-envelope.json", stage / "examples")
        (stage / "verification").mkdir()
        for name in ("acceptance.json", "regression.xml", "cached-immediate.json",
                     "cached-later.json", "cached-receipts-missing.json",
                     "synthetic-delayed-revision.json", "synthetic-delayed-revision-input.json",
                     "simulation-with-selected-horizon.json"):
            shutil.copy2(repo / "output/horizon-browser" / name, stage / "verification" / name)
    (stage / "reports").mkdir()
    reports = ["freshness-validation.zh-CN.md", "freshness-validation-evidence.json"]
    if args.profile == "horizon":
        reports += ["action-model-v2.zh-CN.md", "action-model-v2-evidence.json",
                    "observation-ingestion-contract.zh-CN.md", "horizon-ui-acceptance.zh-CN.md"]
    for name in reports:
        shutil.copy2(repo / "docs" / name, stage / "reports" / name)
    (stage / "protocol").mkdir()
    for name in ("freshness-validation-reservation.json", "freshness-validation-freeze.json"):
        shutil.copy2(repo / "examples" / name, stage / "protocol" / name)
    (stage / "wheel").mkdir()
    wheel = next((args.product_dir / "dist").glob("*.whl"))
    shutil.copy2(wheel, stage / "wheel" / wheel.name)
    (stage / "start.sh").chmod(0o755)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    manifest = {
        "git_commit": commit,
        "product_version": "horizon-ui-20261017" if args.profile == "horizon" else "freshness",
        "python_tested": "3.12",
        "runtime_dependencies": "requirements-runtime.txt",
        "cache": "3 frozen Bahrain observations; derived visible context + separate reveal data",
        "original_large_data": "Separate full recovery package; not included here",
        "scope": "Historical research; reserved validation failed accuracy threshold",
        "default_model": "v1",
        "v2_status": "experimental_failed_accuracy_gates",
        "live_received_at_or_pit_exit_feed": "not connected",
        "sha256": {
            str(p.relative_to(stage)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in stage.rglob("*")
            if p.is_file()
        },
    }
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                stream.write(path, str(path.relative_to(stage.parent)))
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".sha256").write_text(sha + "  " + archive.name + "\n")
    print(
        json.dumps(
            {
                "path": str(archive),
                "bytes": archive.stat().st_size,
                "sha256": sha,
                "git_commit": commit,
            }
        )
    )


if __name__ == "__main__":
    main()
