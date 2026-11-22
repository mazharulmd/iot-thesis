"""Build the thesis plan (Savonia reporting template) from the Markdown files in this folder.

    python3 thesis/plan/build_plan.py

Uses the thesis build script (thesis/report/build.py) with this folder as the source.
Outputs: thesis/plan/thesis-plan.docx and thesis/plan/thesis-plan.pdf.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "report"))
import build  # noqa: E402

build.HERE = HERE
build.BUILD = HERE / "build"
build.OUT_DOCX = HERE / "thesis-plan.docx"
build.OUT_PDF = HERE / "thesis-plan.pdf"
build.BUILD.mkdir(exist_ok=True)

if __name__ == "__main__":
    sys.exit(build.main())
