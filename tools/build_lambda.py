"""Build the Lambda packages into build/<name>/.

    python -m tools.build_lambda [--arch x86_64|aarch64]

detector     detection engine, common helpers, trained bundle + a Linux NumPy wheel for Python 3.12
remediation  playbooks, common helpers (standard library + boto3 only)
approval     approval page and decision (standard library + boto3 only)

Only runtime code is copied, and the NumPy wheel is downloaded for the Lambda platform, so no
Docker is needed to build.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = {
    "common/__init__.py": "common/__init__.py",
    "common/catalog.py": "common/catalog.py",
    "common/topology.py": "common/topology.py",
}
PACKAGES = {
    "detector": ({
        "lambdas/detector/handler.py": "handler.py",
        "detection/__init__.py": "detection/__init__.py",
        "detection/features.py": "detection/features.py",
        "detection/models.py": "detection/models.py",
        "detection/engine.py": "detection/engine.py",
        "detection/models/bundle.json": "detection/models/bundle.json",
        "detection/models/bundle.npz": "detection/models/bundle.npz",
        **COMMON,
    }, ["numpy>=2.0,<2.4"]),
    "remediation": ({
        "lambdas/remediation/handler.py": "handler.py",
        "playbooks/__init__.py": "playbooks/__init__.py",
        "playbooks/catalog.py": "playbooks/catalog.py",
        **COMMON,
    }, []),
    "approval": ({"lambdas/approval/handler.py": "handler.py"}, []),
}


def build(name: str, arch: str = "x86_64") -> Path:
    files, wheels = PACKAGES[name]
    out = ROOT / "build" / name
    missing = [src for src in files if not (ROOT / src).exists()]
    if missing:
        sys.exit(f"missing {missing}; train the detectors first (make train)")
    shutil.rmtree(out, ignore_errors=True)
    for src, dst in files.items():
        (out / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / src, out / dst)
    if wheels:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", str(out),
                        "--platform", f"manylinux2014_{arch}", "--implementation", "cp",
                        "--python-version", "3.12", "--only-binary=:all:", *wheels], check=True)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    print(f"built {out} ({size:.1f} MB unzipped{', numpy for ' + arch if wheels else ''})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Lambda packages")
    ap.add_argument("--arch", default="x86_64", choices=["x86_64", "aarch64"])
    ap.add_argument("--only", choices=sorted(PACKAGES))
    args = ap.parse_args()
    for name in [args.only] if args.only else PACKAGES:
        build(name, args.arch)


if __name__ == "__main__":
    main()
