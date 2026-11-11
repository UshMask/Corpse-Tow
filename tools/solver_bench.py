"""Reproducible JVM benchmark for the native towing solver (Stage 5 evidence).

Compiles the current production Java sources together with a renamed copy of the
frozen baseline solver (tests/fixtures/solver_baseline/TowingSolver.java ->
cvpworld.TowingSolverBaseline), runs tests/BenchmarkTowingSolver.java in the real
game JVM/Kahlua fixture, and reports per-scenario runtimes plus FNV-1a checksums
that prove the current solver is bit-identical to the frozen baseline.

Paths come from local/settings.json (Game, Jdk, ZombieBuddy, Viewpoint). All
generated artifacts and reports go under local/runs/solver-bench-<timestamp>/:
classes/, tests/, baseline-src/, home/, compile logs, benchmark.log,
java-results.json, results.csv and report.json. A pointer is written to
local/latest-solver-bench.json.

Usage:
  .venv\\Scripts\\python.exe -B tools/solver_bench.py
  .venv\\Scripts\\python.exe -B tools/solver_bench.py --repeats 5 --warmup 2
  .venv\\Scripts\\python.exe -B tools/solver_bench.py --scenarios 6,7,8,9,10,11
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "cvp-solver-bench/1"
BASELINE_CLASS = "TowingSolverBaseline"
BASELINE_LUA_CLASS = "CVPSolverNativeBaseline"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_tree(root: Path) -> str | None:
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def resolve_path(repo: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def read_settings(repo: Path) -> tuple[Path, dict]:
    path = repo / "local" / "settings.json"
    if not path.is_file():
        raise SystemExit(f"missing settings file: {path}")
    with path.open("r", encoding="utf-8-sig") as handle:
        return path, json.load(handle)


def classpath(game: Path, zombiebuddy: Path, viewpoint: Path | None, extra: list[Path]) -> str:
    # The Java launcher expands the wildcard itself, so pass game/* literally.
    parts = [str(path) for path in extra]
    parts.append(str(game / "projectzomboid.jar"))
    parts.append(str(game / "*"))
    parts.append(str(zombiebuddy))
    if viewpoint and viewpoint.is_file():
        parts.append(str(viewpoint))
    return ";".join(parts)


def run_step(cmd: list[str], cwd: Path, log_path: Path, label: str) -> bytes:
    started = time.perf_counter()
    completed = subprocess.run(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - started
    header = (
        f"[solver_bench] {label}\n"
        f"[solver_bench] cwd: {cwd}\n"
        f"[solver_bench] seconds: {elapsed:.3f}\n"
        f"[solver_bench] exit: {completed.returncode}\n"
        f"[solver_bench] command: {subprocess.list2cmdline(cmd)}\n\n"
    ).encode("utf-8")
    log_path.write_bytes(header + completed.stdout)
    if completed.returncode != 0:
        text = completed.stdout.decode("utf-8", "replace")
        raise SystemExit(f"{label} failed (exit {completed.returncode}); log: {log_path}\n{text[-4000:]}")
    return completed.stdout


def version_of(cmd: list[str], cwd: Path, log_path: Path, label: str) -> str:
    completed = subprocess.run(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = completed.stdout.decode("utf-8", "replace").strip()
    log_path.write_text(f"[solver_bench] {label}\n[exit: {completed.returncode}]\n{output}\n", encoding="utf-8")
    return output.splitlines()[0] if output else "unknown"


def git_head(repo: Path) -> dict:
    def call(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args], cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10
            )
            return result.stdout.decode("utf-8", "replace").strip() if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""
    return {"head": call("rev-parse", "HEAD"), "branch": call("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(call("status", "--porcelain"))}


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--warmup", type=int, default=1, help="warmup passes per solver per scenario (default 1)")
    parser.add_argument("--repeats", type=int, default=3, help="timed passes per solver per scenario (default 3)")
    parser.add_argument("--scenarios", default=None, help="comma-separated scenario indices (default all 12)")
    parser.add_argument("--label", default=None, help="optional label recorded in the report")
    parser.add_argument("--output", default=None, help="run directory (default local/runs/solver-bench-<timestamp>)")
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")
    if args.warmup < 0:
        raise SystemExit("--warmup must be >= 0")

    repo = Path(__file__).resolve().parents[1]
    settings_path, settings = read_settings(repo)
    game = resolve_path(repo, settings.get("Game"))
    jdk = resolve_path(repo, settings.get("Jdk"))
    zombiebuddy = resolve_path(repo, settings.get("ZombieBuddy"))
    viewpoint = resolve_path(repo, settings.get("Viewpoint"))
    missing = []
    for name, path in (("Game", game), ("Jdk", jdk), ("ZombieBuddy", zombiebuddy)):
        if not path or not path.exists():
            missing.append(f"{name}={path}")
    if missing:
        raise SystemExit("local/settings.json points at missing dependencies: " + ", ".join(missing))
    javac = jdk / "bin" / "javac.exe"
    game_java = game / "jre64" / "bin" / "java.exe"
    java = game_java if game_java.is_file() else jdk / "bin" / "java.exe"
    if not javac.is_file():
        raise SystemExit(f"javac not found: {javac}")
    if not java.is_file():
        raise SystemExit(f"java not found: {java}")

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = (resolve_path(repo, args.output) if args.output
               else repo / "local" / "runs" / f"solver-bench-{timestamp}")
    classes = run_dir / "classes"
    tests_dir = run_dir / "tests"
    baseline_src = run_dir / "baseline-src"
    home = run_dir / "home"
    for path in (run_dir, classes, tests_dir, baseline_src, home):
        path.mkdir(parents=True, exist_ok=True)

    current_source = repo / "CorpseProxyLab" / "source" / "cvpworld" / "TowingSolver.java"
    baseline_source = repo / "tests" / "fixtures" / "solver_baseline" / "TowingSolver.java"
    current_jar = repo / "CorpseProxyLab" / "42" / "media" / "java" / "CorpseProxyWorld.jar"
    if not current_source.is_file():
        raise SystemExit(f"missing current source: {current_source}")
    if not baseline_source.is_file():
        raise SystemExit(f"missing frozen baseline: {baseline_source}")

    shas = {
        "current_source": sha256_file(current_source),
        "baseline_source": sha256_file(baseline_source),
        "current_jar": sha256_file(current_jar),
        "current_jar_mtime": datetime.fromtimestamp(current_jar.stat().st_mtime, timezone.utc).isoformat()
        if current_jar.is_file() else None,
    }

    # Rename the frozen baseline so it can link beside the production solver.
    text = baseline_source.read_text(encoding="utf-8-sig")
    replacements = {
        "public final class TowingSolver {": f"public final class {BASELINE_CLASS} {{",
        '@LuaClass(name="CVPSolverNative")': f'@LuaClass(name="{BASELINE_LUA_CLASS}")',
    }
    for old, new in replacements.items():
        if old not in text:
            raise SystemExit(f"frozen baseline no longer matches expected marker: {old}")
        text = text.replace(old, new)
    generated = baseline_src / f"{BASELINE_CLASS}.java"
    generated.write_text(text, encoding="utf-8")
    shas["baseline_generated_source"] = sha256_file(generated)

    cp = classpath(game, zombiebuddy, viewpoint, [])
    sources = sorted(str(path) for path in (repo / "CorpseProxyLab" / "source").rglob("*.java"))
    if not sources:
        raise SystemExit("no java sources under CorpseProxyLab/source")
    run_step([str(javac), "-encoding", "UTF-8", "-cp", cp, "-d", str(classes), *sources],
             repo, run_dir / "compile-current.log", "compile current sources")
    run_step([str(javac), "-encoding", "UTF-8", "-cp", f"{classes};{cp}", "-d", str(classes), str(generated)],
             repo, run_dir / "compile-baseline.log", "compile frozen baseline copy")
    run_step([str(javac), "-encoding", "UTF-8", "-cp", f"{tests_dir};{classes};{cp}", "-d", str(tests_dir),
              str(repo / "tests" / "BenchmarkTowingSolver.java")],
             repo, run_dir / "compile-harness.log", "compile benchmark harness")
    shas["compiled_classes"] = sha256_tree(classes)

    javac_version = version_of([str(javac), "-version"], repo, run_dir / "javac-version.log", "javac -version")
    java_version = version_of([str(java), "-version"], repo, run_dir / "java-version.log", "java -version")

    java_json = run_dir / "java-results.json"
    benchmark_log = run_dir / "benchmark.log"
    command = [
        str(java),
        "--enable-native-access=ALL-UNNAMED",
        f"-Duser.home={home}",
        f"-Dcvp.game={game}",
        "-cp", f"{tests_dir};{classes};{cp}",
        "cvpworld.BenchmarkTowingSolver",
        "--warmup", str(args.warmup),
        "--repeats", str(args.repeats),
        "--json", str(java_json),
    ]
    if args.scenarios:
        normalized = ",".join(part.strip() for part in args.scenarios.split(",") if part.strip())
        if normalized:
            command += ["--scenarios", normalized]
    print(f"[solver_bench] run dir: {run_dir}")
    print(f"[solver_bench] command: {subprocess.list2cmdline(command)}")
    run_step(command, repo, benchmark_log, "run JVM benchmark")
    if args.label:
        (run_dir / "label.txt").write_text(args.label + "\n", encoding="utf-8")

    try:
        benchmark = json.loads(java_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot parse benchmark output {java_json}: {error}")

    scenarios = benchmark["scenarios"]
    summary = {
        "result": benchmark.get("result"),
        "scenarios": len(scenarios),
        "baseline_min_ms": benchmark["totals"]["baselineMinMs"],
        "current_min_ms": benchmark["totals"]["currentMinMs"],
        "speedup": benchmark["totals"]["speedup"],
        "max_abs_error": max((scenario["maxAbsError"] for scenario in scenarios), default=None),
        "total_bit_diffs": sum(scenario["bitDiffs"] for scenario in scenarios),
        "checksums_match": all(s["baselineChecksum"] == s["currentChecksum"] for s in scenarios),
        "counters_checksum_match": all(s["counters"]["checksumMatch"] for s in scenarios),
        "persistent_backend": benchmark["backend"]["currentPersistent"],
    }
    passed = (summary["result"] == "pass" and summary["checksums_match"]
              and summary["counters_checksum_match"] and summary["total_bit_diffs"] == 0
              and summary["max_abs_error"] == 0.0)

    report = {
        "schema": SCHEMA,
        "label": args.label,
        "generated_at": datetime.now().astimezone().isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "repo": str(repo),
        "command_line": subprocess.list2cmdline([sys.executable, *sys.argv]),
        "settings": {
            "path": str(settings_path),
            "game": str(game),
            "jdk": str(jdk),
            "zombiebuddy": str(zombiebuddy),
            "viewpoint": str(viewpoint) if viewpoint else None,
        },
        "sha256": shas,
        "versions": {
            "javac": javac_version,
            "java": java_version,
            "git": git_head(repo),
            "solver_backend": benchmark.get("backend"),
        },
        "harness": {
            "name": "tests/BenchmarkTowingSolver.java",
            "warmup": args.warmup,
            "repeats": args.repeats,
            "scenarios_filter": args.scenarios,
            "checksum_algorithm": benchmark.get("checksumAlgorithm"),
            "timed_region": "solver calls only (fixture/Kahlua/checksum excluded)",
        },
        "summary": summary,
        "benchmark": benchmark,
    }
    report_json = run_dir / "report.json"
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_path = run_dir / "results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "scenario", "name", "bodies", "ticks", "requested_steps",
            "baseline_min_ms", "baseline_median_ms", "current_min_ms", "current_median_ms", "speedup",
            "baseline_checksum", "current_checksum", "checksums_match", "bit_diffs", "max_abs_error",
            "counters_substeps", "counters_iterations", "counters_calls", "counters_search_entries",
            "counters_limit_hits", "counters_fallbacks", "counters_backend", "counters_checksum_match",
        ])
        for scenario in scenarios:
            base = scenario["baselineMs"]
            current = scenario["currentMs"]
            counters = scenario["counters"]
            writer.writerow([
                scenario["index"], scenario["name"], scenario["bodies"], scenario["ticks"],
                scenario["requestedSteps"],
                f"{min(base):.6f}", f"{median(base):.6f}", f"{min(current):.6f}", f"{median(current):.6f}",
                f"{min(base) / min(current):.6f}" if min(current) else "",
                scenario["baselineChecksum"], scenario["currentChecksum"],
                scenario["baselineChecksum"] == scenario["currentChecksum"],
                scenario["bitDiffs"], scenario["maxAbsError"],
                counters["substeps"], counters["iterations"], counters["constraintCalls"],
                counters["searchEntries"], counters["limitHits"], counters["fallbacks"],
                counters["backend"], counters["checksumMatch"],
            ])

    pointer = repo / "local" / "latest-solver-bench.json"
    pointer.write_text(json.dumps({
        "schema": SCHEMA,
        "generated_at_utc": report["generated_at_utc"],
        "run_dir": str(run_dir),
        "result": "pass" if passed else "fail",
        "current_source_sha256": shas["current_source"],
        "baseline_source_sha256": shas["baseline_source"],
        "current_jar_sha256": shas["current_jar"],
        "baseline_min_ms": summary["baseline_min_ms"],
        "current_min_ms": summary["current_min_ms"],
        "speedup": summary["speedup"],
    }, indent=2), encoding="utf-8")

    for scenario in scenarios:
        print(
            f"[solver_bench] scenario={scenario['index']} name={scenario['name']} "
            f"baseline_min_ms={min(scenario['baselineMs']):.3f} "
            f"current_min_ms={min(scenario['currentMs']):.3f} "
            f"speedup={min(scenario['baselineMs']) / min(scenario['currentMs']):.3f} "
            f"checksums_match={scenario['baselineChecksum'] == scenario['currentChecksum']} "
            f"bit_diffs={scenario['bitDiffs']} max_abs_error={scenario['maxAbsError']}"
        )
    print(
        f"[solver_bench] TOTAL baseline_min_ms={summary['baseline_min_ms']} "
        f"current_min_ms={summary['current_min_ms']} speedup={summary['speedup']} "
        f"max_abs_error={summary['max_abs_error']} bit_diffs={summary['total_bit_diffs']}"
    )
    print(f"[solver_bench] current source sha256={shas['current_source']}")
    print(f"[solver_bench] baseline source sha256={shas['baseline_source']}")
    print(f"[solver_bench] current jar sha256={shas['current_jar'] or 'missing'} (built jar is context only; the run compiles from source)")
    print(f"[solver_bench] report: {report_json}")
    print(f"[solver_bench] csv:    {csv_path}")
    print(f"[solver_bench] {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
