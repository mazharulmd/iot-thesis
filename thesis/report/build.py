"""Build the thesis report from the Markdown chapters into the Savonia reporting template.

    python3 thesis/report/build.py            (needs python-docx, PyMuPDF and LibreOffice)

Steps: convert the Savonia template (.odt) to .docx with LibreOffice; fill the cover page and
the abstract table from 00-front.md; replace the template's sample chapters with the chapters
01-*.md ... 11-*.md; let LibreOffice update the table of contents and export a PDF; read the
figure pages and the page count back from the PDF; build a second time with the list of figures
and the Pages/Appendices field filled in.

Markdown conventions: '#' main chapter (numbered by the template), '##' / '###' subchapters,
'# References' and '# Appendix N: ...' unnumbered; a line 'Table N. ...' before a table is its
title; '![alt](figures/x.png)' followed by 'Figure N. ...' is a figure and its caption;
'- ' bullet lists; **bold**, *italic*, `code`; text in [square brackets] that starts with a
capital letter and spans a whole paragraph or sentence is highlighted as a to-do.

Outputs: thesis/thesis.docx and thesis/thesis.pdf.
"""
from __future__ import annotations

import copy
import re
import subprocess
import sys
from pathlib import Path

import docx
import pymupdf
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATE_ODT = ROOT / "Thesis Format" / "Reporting Template.odt"
BUILD = HERE / "build"
OUT_DOCX = ROOT / "thesis" / "thesis.docx"
OUT_PDF = ROOT / "thesis" / "thesis.pdf"
TEXT_INDENT_TWIPS = 1304          # Normal1 left indent in the template (2.3 cm)
FIGURE_WIDTH = Cm(15.0)


# ---------------------------------------------------------------- Markdown input

def read_front() -> tuple[dict, list[str]]:
    text = (HERE / "00-front.md").read_text(encoding="utf-8")
    _, meta_txt, body = text.split("---", 2)
    meta = {}
    for line in meta_txt.strip().splitlines():
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip().strip('"')
    abstract = body.split("## Abstract", 1)[1].strip()
    return meta, [p.strip() for p in abstract.split("\n\n") if p.strip()]


def chapter_files() -> list[Path]:
    return sorted(p for p in HERE.glob("[0-9][0-9]-*.md") if not p.name.startswith("00-"))


# ---------------------------------------------------------------- docx helpers

def S(d, name: str):
    """Find a style by its display name (python-docx renames some built-in names)."""
    for st in d.styles:
        if st.name == name:
            return st
    raise KeyError(name)


def add_runs(par, text: str, highlight_todo: bool = True) -> None:
    for part in re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**"):
            run = par.add_run(part[2:-2]); run.bold = True
        elif part.startswith("*"):
            run = par.add_run(part[1:-1]); run.italic = True
        elif part.startswith("`"):
            run = par.add_run(part[1:-1]); run.font.name = "Courier New"; run.font.size = Pt(10)
        else:
            for piece in re.split(r"(\[(?:Step 8|E5 results)[^\]]*\])", part):
                if piece:
                    run = par.add_run(piece)
                    if highlight_todo and piece.startswith(("[Step 8", "[E5 results")):
                        run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def set_par_text(par, text: str) -> None:
    for r in list(par.runs):
        r._r.getparent().remove(r._r)
    par.add_run(text)


def page_break_before(par) -> None:
    ppr = par._p.get_or_add_pPr()
    el = OxmlElement("w:pageBreakBefore")
    ppr.insert(0, el)


def keep_with_next(par) -> None:
    par.paragraph_format.keep_with_next = True


def set_cell_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single"); el.set(qn("w:sz"), "4"); el.set(qn("w:space"), "0"); el.set(qn("w:color"), "808080")
        borders.append(el)
    tbl_pr.append(borders)
    ind = OxmlElement("w:tblInd"); ind.set(qn("w:w"), str(TEXT_INDENT_TWIPS)); ind.set(qn("w:type"), "dxa")
    tbl_pr.append(ind)


TABLE_WIDTH_CM = 15.7   # text width (18 cm) minus the 2.3 cm body-text indent


def column_widths(rows: list[list[str]]) -> list[float]:
    """Share the table width by content length, with a minimum per column."""
    n = len(rows[0])
    need = []
    for j in range(n):
        lengths = [len(r[j]) for r in rows if j < len(r)]
        longest = max(lengths)
        mean = sum(lengths) / len(lengths)
        need.append(max(6, min(longest, 1.4 * mean + 4)))
    # never narrower than the longest word (bold header words are a little wider)
    minimum = []
    for j in range(n):
        words = [w for r in rows if j < len(r) for w in re.split(r"[\s/]+", r[j].replace("*", ""))]
        longest_word = max((len(w) for w in words), default=4)
        minimum.append(max(1.3, 0.2 * longest_word + 0.35))
    total = sum(need)
    widths = [max(m, TABLE_WIDTH_CM * x / total) for m, x in zip(minimum, need)]
    for _ in range(20):                        # take the excess from columns above their minimum
        excess = sum(widths) - TABLE_WIDTH_CM
        if excess <= 0.01:
            break
        flexible = [k for k in range(n) if widths[k] > minimum[k] + 0.05]
        if not flexible:
            break
        room = sum(widths[k] - minimum[k] for k in flexible)
        for k in flexible:
            widths[k] -= excess * (widths[k] - minimum[k]) / room
    scale = TABLE_WIDTH_CM / sum(widths)
    return [w * scale for w in widths]


def add_table(d, rows: list[list[str]]) -> None:
    t = d.add_table(rows=len(rows), cols=len(rows[0]))
    set_cell_borders(t)
    widths = column_widths(rows)
    tbl_pr = t._tbl.tblPr
    for tag in ("w:tblW", "w:tblLayout"):
        old = tbl_pr.find(qn(tag))
        if old is not None:
            tbl_pr.remove(old)
    tw = OxmlElement("w:tblW"); tw.set(qn("w:w"), str(int(TABLE_WIDTH_CM * 567))); tw.set(qn("w:type"), "dxa")
    tbl_pr.append(tw)
    lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); tbl_pr.append(lay)
    grid = t._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(int(w * 567)))
    for row in t.rows:
        for cell, w in zip(row.cells, widths):
            cell.width = Cm(w)
    for i, row in enumerate(rows):
        for j, txt in enumerate(row):
            cell = t.cell(i, j)
            par = cell.paragraphs[0]
            par.style = S(d, "No Spacing")
            add_runs(par, txt)
            for r in par.runs:
                r.font.size = Pt(9)
                if i == 0:
                    r.bold = True
            if i == 0:
                shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:fill"), "EDEDED")
                cell._tc.get_or_add_tcPr().append(shd)
    # repeat the header row on every page
    trpr = t.rows[0]._tr.get_or_add_trPr(); hdr = OxmlElement("w:tblHeader"); trpr.append(hdr)
    sp = d.add_paragraph(style=S(d, "Normal1")); sp.paragraph_format.space_after = Pt(4)


def add_chapter(d, path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    para_buf: list[str] = []

    def flush():
        if para_buf:
            p = d.add_paragraph(style=S(d, "Normal1"))
            add_runs(p, " ".join(para_buf))
            para_buf.clear()

    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("# "):
            flush()
            title = line[2:].strip()
            if title == "References" or title.startswith("Appendix"):
                p = d.add_paragraph(style=S(d, "Sisällysluettelon muu otsikko"))
                p.add_run(title.upper()); page_break_before(p)
            else:
                d.add_paragraph(title, style=S(d, "Heading 1"))
        elif line.startswith("### "):
            flush(); d.add_paragraph(line[4:].strip(), style=S(d, "Heading 3"))
        elif line.startswith("## "):
            flush(); d.add_paragraph(line[3:].strip(), style=S(d, "Heading 2"))
        elif line.startswith("- "):
            flush(); p = d.add_paragraph(style=S(d, "List Bullet")); add_runs(p, line[2:].strip())
            p.paragraph_format.left_indent = Cm(2.3 + 0.63)
            p.paragraph_format.first_line_indent = Cm(-0.63)
        elif line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    rows.append(cells)
                i += 1
            add_table(d, rows)
            continue
        elif line.startswith("!["):
            flush()
            src = re.search(r"\(([^)]+)\)", line).group(1)
            p = d.add_paragraph(style=S(d, "Normal1"))
            p.add_run().add_picture(str(HERE / src), width=FIGURE_WIDTH)
            p.paragraph_format.space_after = Pt(2); keep_with_next(p)
        elif re.match(r"^Figure \d+\. ", line):
            flush(); p = d.add_paragraph(style=S(d, "Caption")); add_runs(p, line)
            p.paragraph_format.space_after = Pt(12)
        elif re.match(r"^Table [A-Z]?\d+\. ", line):
            flush(); p = d.add_paragraph(style=S(d, "Caption")); add_runs(p, line); keep_with_next(p)
            p.paragraph_format.space_before = Pt(6)
        elif not line.strip():
            flush()
        else:
            para_buf.append(line.strip())
        i += 1
    flush()


def build_docx(meta: dict, abstract: list[str], figures: list[tuple[str, int]], pages: str) -> Path:
    tmpl = BUILD / "Reporting Template.docx"
    if not tmpl.exists():
        BUILD.mkdir(exist_ok=True)
        subprocess.run(["soffice", "--headless", "--convert-to", "docx", "--outdir", str(BUILD),
                        str(TEMPLATE_ODT)], check=True, capture_output=True)
    d = docx.Document(str(tmpl))
    body = d.element.body

    # Cover page (the colour block exists twice: DrawingML and its VML fallback). LibreOffice's
    # .odt -> .docx conversion gives the report-type text box a white fill, which hides its
    # white text on the pink block; make the box transparent again.
    WPS = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}"
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    VML = "{urn:schemas-microsoft-com:vml}"
    for wsp in body.iter(WPS + "wsp"):
        if "rEPORT TYPE" in "".join(wsp.itertext()):
            sppr = wsp.find(WPS + "spPr")
            fill = sppr.find(A + "solidFill")
            if fill is not None:
                sppr.replace(fill, OxmlElement("a:noFill"))
    for shape in body.iter(VML + "shape", VML + "rect"):
        if "rEPORT TYPE" in "".join(shape.itertext()):
            shape.set("filled", "f")
    swaps = {"rEPORT TYPE": "Thesis", "tYPE OF Degree": "Bachelor's degree",
             "Select Field of Study": meta["field_of_study"]}
    for t in body.iter(qn("w:t")):
        if t.text in swaps:
            t.text = swaps[t.text]
    pars = d.paragraphs
    for p in pars:
        if p.style is not None and p.style.name == "Title page Thesis title":
            set_par_text(p, meta["title"])
        elif p.style is not None and p.style.name == "Title page Subtitle":
            set_par_text(p, meta.get("subtitle", ""))
    # A long title takes several lines: drop as many empty spacer lines below the subtitle
    sub = next(i for i, p in enumerate(pars) if p.style is not None and p.style.name == "Title page Subtitle")
    extra_lines = max(0, len(meta["title"]) // 28)
    removed = 0
    for p in pars[sub + 1:]:
        if removed >= extra_lines + 1 or p.text.strip() or p._p.find(".//" + qn("w:drawing")) is not None:
            break
        p._p.getparent().remove(p._p)
        removed += 1
    pars = d.paragraphs
    # Author lines: keep the page break that ends the cover page
    for idx, p in enumerate(pars):
        if p.text.startswith("AUTHOR/S"):
            set_par_text(p, f"AUTHOR\t{meta['author']}")
            for q in (pars[idx + 1], pars[idx + 2]):
                for t in q._p.iter(qn("w:t")):
                    t.text = ""
                for tab in list(q._p.iter(qn("w:tab"))):
                    if tab.getparent().tag == qn("w:r"):
                        tab.getparent().remove(tab)
            break

    # Abstract table
    t = d.tables[0]

    def put(row, col, text, para_index=None):
        cell = t.cell(row, col)
        par = cell.paragraphs[para_index] if para_index is not None else cell.paragraphs[-1]
        set_par_text(par, text)

    put(0, 0, meta["field_of_study"], 1)
    put(2, 0, meta["degree_programme"], 1)
    put(4, 0, meta["author"])
    put(6, 0, meta["title"] + (f": {meta['subtitle']}" if meta.get("subtitle") else ""))
    put(7, 1, meta["date"])
    put(7, 3, pages)
    put(9, 0, meta["client"])
    cell = t.cell(10, 0)
    first = cell.paragraphs[0]
    for r in list(first.runs):
        r._r.getparent().remove(r._r)
    template_p = copy.deepcopy(first._p)
    for k, text in enumerate(abstract):
        if k == 0:
            par = first
        else:
            cell._tc.append(copy.deepcopy(template_p))           # empty line between paragraphs
            new = copy.deepcopy(template_p)
            cell._tc.append(new)
            par = Paragraph(new, cell)
        for piece in re.split(r"(\[Step 8[^\]]*\])", text):
            if piece:
                run = par.add_run(piece)
                if piece.startswith("[Step 8"):
                    run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    for row in (4, 6, 9):
        for par in t.cell(row, 0).paragraphs:
            par.style = S(d, "No Spacing")
            par.paragraph_format.left_indent = Cm(0)
            par.paragraph_format.first_line_indent = Cm(0)
    kw = t.cell(11, 0).paragraphs
    set_par_text(kw[-1], meta["keywords"])

    # List of figures: replace the template's sample entries with static ones
    children = list(body)
    lof_heading = next(i for i, el in enumerate(children)
                       if el.tag == qn("w:p") and "LIST OF FIGURES" in "".join(el.itertext()))
    sample = children[lof_heading + 1]
    j = lof_heading + 1
    while children[j].tag == qn("w:p") and re.match(r"Figure \d", "".join(children[j].itertext())):
        j += 1
    for el in children[lof_heading + 1:j]:
        body.remove(el)
    anchor = children[lof_heading]
    for text, page in reversed(figures):
        p = OxmlElement("w:p")
        ppr = OxmlElement("w:pPr"); ps = OxmlElement("w:pStyle"); ps.set(qn("w:val"), "TableofFigures")
        ppr.append(ps); p.append(ppr)
        for piece, is_tab in ((text, False), (None, True), (str(page), False)):
            r = OxmlElement("w:r")
            if is_tab:
                r.append(OxmlElement("w:tab"))
            else:
                tt = OxmlElement("w:t"); tt.text = piece; tt.set(qn("xml:space"), "preserve"); r.append(tt)
            p.append(r)
        anchor.addnext(p)
    del sample

    # The list of figures heading stays with its entries; the page break after the list is
    # dropped because every main chapter heading already starts a new page.
    lof = next(el for el in body if el.tag == qn("w:p") and "LIST OF FIGURES" in "".join(el.itertext()))
    Paragraph(lof, d._body).paragraph_format.keep_with_next = True
    nxt = lof.getnext()
    while nxt is not None and nxt.tag == qn("w:p"):
        txt = "".join(nxt.itertext())
        if not txt.strip() and nxt.find(".//" + qn("w:br")) is not None:
            for br in list(nxt.iter(qn("w:br"))):
                if br.get(qn("w:type")) == "page":
                    br.getparent().remove(br)
        if any(st.get(qn("w:val")) == "Heading1" for st in nxt.iter(qn("w:pStyle"))):
            break
        nxt = nxt.getnext()

    # Remove the template's sample chapters, references and appendix
    children = list(body)
    start = next(i for i, el in enumerate(children)
                 if el.tag == qn("w:p") and el.find(qn("w:pPr")) is not None
                 and el.find(qn("w:pPr")).find(qn("w:pStyle")) is not None
                 and el.find(qn("w:pPr")).find(qn("w:pStyle")).get(qn("w:val")) == "Heading1")
    for el in children[start:]:
        if el.tag != qn("w:sectPr"):
            body.remove(el)

    for path in chapter_files():
        add_chapter(d, path)

    BUILD.mkdir(exist_ok=True)
    out = BUILD / "thesis-raw.docx"
    d.save(str(out))
    return out


# ---------------------------------------------------------------- LibreOffice pass

UNO_SCRIPT = r'''
import sys, time, subprocess, uno
from com.sun.star.beans import PropertyValue
def prop(n, v):
    p = PropertyValue(); p.Name = n; p.Value = v; return p
src, out_docx, out_pdf = sys.argv[1:4]
proc = subprocess.Popen(["soffice", "--headless", "--invisible", "--norestore",
                         "--accept=socket,host=localhost,port=2083;urp;"])
ctx = None
for _ in range(60):
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        ctx = resolver.resolve("uno:socket,host=localhost,port=2083;urp;StarOffice.ComponentContext")
        break
    except Exception:
        time.sleep(1)
smgr = ctx.ServiceManager
desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
doc = desktop.loadComponentFromURL(uno.systemPathToFileUrl(src), "_blank", 0, (prop("Hidden", True),))
if doc is None:
    proc.kill()
    sys.exit("LibreOffice could not load " + src)
for _ in range(2):
    idx = doc.getDocumentIndexes()
    for i in range(idx.getCount()):
        idx.getByIndex(i).update()
    doc.getTextFields().refresh()
doc.storeToURL(uno.systemPathToFileUrl(out_docx), (prop("FilterName", "MS Word 2007 XML"),))
doc.storeToURL(uno.systemPathToFileUrl(out_pdf), (prop("FilterName", "writer_pdf_Export"),))
doc.close(True)
try:
    desktop.terminate()
except Exception:
    pass
try:
    proc.wait(timeout=60)
except Exception:
    proc.kill()
'''


def libreoffice_pass(raw: Path) -> None:
    script = BUILD / "uno_update.py"
    script.write_text(UNO_SCRIPT)
    subprocess.run(["/usr/bin/python3", str(script), str(raw), str(OUT_DOCX), str(OUT_PDF)],
                   check=True, timeout=600)


def read_layout(meta_figs: list[str]) -> tuple[list[tuple[str, int]], str]:
    pdf = pymupdf.open(str(OUT_PDF))
    figures = []
    for caption in meta_figs:
        prefix = caption.split(". ", 1)[0] + ". "
        page_no = None   # the caption is the last occurrence; the list of figures comes first
        for i, page in enumerate(pdf):
            if any(line.strip().startswith(prefix) for line in page.get_text().splitlines()):
                page_no = i + 1
        figures.append((caption, page_no or 0))
    ref_page = next(i + 1 for i in range(len(pdf) - 1, -1, -1)
                    if pdf[i].get_text().lstrip().startswith(("REFERENCES",)) or
                    "\nREFERENCES\n" in "\n" + pdf[i].get_text())
    # last page before the first appendix
    first_app = next((i + 1 for i in range(len(pdf)) if re.search(r"^\s*APPENDIX 1", pdf[i].get_text(), re.M)
                      and i + 1 > ref_page), len(pdf) + 1)
    n_app = len([p for p in chapter_files() if p.read_text().startswith("# Appendix")])
    return figures, f"{first_app - 1}/{n_app}"


def main() -> None:
    meta, abstract = read_front()
    captions = []
    for path in chapter_files():
        captions += [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
                     if re.match(r"^Figure \d+\. ", l)]
    placeholder = [(c, 0) for c in captions]
    libreoffice_pass(build_docx(meta, abstract, placeholder, ""))
    figures, pages = read_layout(captions)
    libreoffice_pass(build_docx(meta, abstract, figures, pages))
    figures2, pages2 = read_layout(captions)
    if figures2 != figures or pages2 != pages:
        libreoffice_pass(build_docx(meta, abstract, figures2, pages2))
    n = pymupdf.open(str(OUT_PDF)).page_count
    print(f"{OUT_PDF.relative_to(ROOT)}: {n} pages, Pages/Appendices {pages2}")
    for c, p in figures2:
        print(f"  p.{p:>3}  {c}")


if __name__ == "__main__":
    sys.exit(main())
