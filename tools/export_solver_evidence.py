"""Export an explicit solver evidence allowlist, never game binaries or settings.

Example (output must not exist):
  python tools/export_solver_evidence.py --benchmark local/runs/NAME \
      --oracle local/runs/ORACLE --build local/runs/BUILD \
      --log local/audit-ci-tests.log --output docs/performance/solver-audit

Raw fork JSON is losslessly gzip-compressed (mtime=0). Only private path strings
are replaced; numerical samples/checksums are not recomputed or filtered. Review
all exported files before publishing: this is an allowlist, not a general-purpose
secret scrubber for arbitrary game logs.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN .*PRIVATE KEY-----)")


def decode(data: bytes) -> str:
    return data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")


def replacements(root: Path) -> dict[str, str]:
    values = {str(root.resolve()): "<REPO>", str(Path.home()): "<HOME>"}
    settings = root / "local/settings.json"
    if settings.is_file():
        for key, value in json.loads(settings.read_text(encoding="utf-8-sig")).items():
            if isinstance(value, str) and value:
                values[value] = f"<{key.upper()}>"
    expanded = {}
    for value, alias in values.items():
        variants = (value, value.replace("\\", "/"), value.replace("\\", "\\\\"),
                    json.dumps(value, ensure_ascii=True)[1:-1],
                    json.dumps(value.replace("\\", "/"), ensure_ascii=True)[1:-1],
                    quote(value.replace("\\", "/"), safe="/:"))
        for variant in variants:
            expanded[variant] = alias
    return expanded


def sanitize(text: str, private_paths: dict[str, str], wrapped_log_paths=False) -> str:
    for value in sorted(private_paths, key=len, reverse=True):
        text = re.sub(re.escape(value), lambda _: private_paths[value], text, flags=re.IGNORECASE)
        if wrapped_log_paths and "\n" in text:
            # Windows PowerShell can soft-wrap native stderr inside a private path.
            # Recognize ONLY a known path, never unwrap arbitrary logs/JSON/numeric samples.
            pattern = r"(?:\r*\n[ \t]*)?".join(re.escape(char) for char in value)
            text = re.sub(pattern, lambda _: private_paths[value], text, flags=re.IGNORECASE)
    if SECRET.search(text):
        raise ValueError("credential/private-key pattern detected; refusing to publish")
    # JVM environment metadata must not leak usernames/hostnames through properties.
    path_text = text.replace("\\\\", "\\")  # JSON-escaped path strings as well as plain logs
    if re.search(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]|/(?:home|Users)/", path_text, re.IGNORECASE):
        raise ValueError("unredacted home path detected")
    return text


def export_file(source: Path, target: Path, private_paths: dict[str, str], compress=False) -> dict:
    raw = source.read_bytes()
    text = sanitize(decode(raw), private_paths, source.suffix == ".log")
    # Validate raw JSON, including after path replacement; don't silently export corrupt data.
    if source.suffix == ".json":
        json.loads(text)
    data = text.encode("utf-8")
    if compress:
        data = gzip.compress(data, mtime=0)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "compression": "gzip" if compress else "none"}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benchmark", type=Path, action="append", default=[])
    p.add_argument("--oracle", type=Path)
    p.add_argument("--build", type=Path)
    p.add_argument("--log", type=Path, action="append", default=[])
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    if a.output.exists():
        p.error("output already exists; choose a new evidence directory")
    selected = []
    for i, run in enumerate(a.benchmark):
        prefix = f"benchmark-{i + 1}"
        for name in ("report.json", "results.csv"):
            selected.append((run / name, f"{prefix}/{name}", False))
        for source in sorted(run.glob("fork-*.json")):
            selected.append((source, f"{prefix}/{source.name}.gz", True))
    if a.oracle:
        for name in ("report.json", "oracle.log", "negative-control.log", "negative-java-control.log"):
            source = a.oracle / name
            if source.is_file():
                selected.append((source, f"oracle/{name}", False))
        for control in ("java-old-distance", "java-stale-candidate-trig", "lua-old-distance", "nested-only-jar"):
            for name in ("oracle.log", "compile.log"):
                source = a.oracle / "negative-controls" / control / name
                if source.is_file():
                    selected.append((source, f"oracle/negative-controls/{control}/{name}", False))
    if a.build:
        # Explicit native-build text evidence only; never class directories or dependency JARs.
        for source in sorted(a.build.glob("Validate*.log")):
            selected.append((source, f"build/{source.name}", False))
        for name in ("compile.log", "compile-tests.log", "package-CorpseProxyWorld.jar.log", "result.json"):
            source = a.build / name
            if source.is_file():
                selected.append((source, f"build/{source.name}", False))
    for source in a.log:
        selected.append((source, f"tests/{source.name}", False))
    if not selected or any(not source.is_file() for source, _, _ in selected):
        p.error("missing explicitly requested evidence file")
    names = [name for _, name, _ in selected]
    if len(names) != len(set(names)):
        p.error("duplicate output names")
    paths = replacements(ROOT)
    # Preflight every file before creating the output.
    for source, _, _ in selected:
        text = sanitize(decode(source.read_bytes()), paths, source.suffix == ".log")
        if source.suffix == ".json":
            json.loads(text)
    a.output.mkdir(parents=True)
    manifest = {name: export_file(source, a.output / name, paths, compress)
                for source, name, compress in selected}
    (a.output / "manifest.json").write_text(json.dumps({
        "schema": "cvp-solver-evidence/1", "redactions": "private path strings only; numeric samples retained",
        "files": manifest}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Exported {len(manifest)} allowlisted files; review before publishing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
