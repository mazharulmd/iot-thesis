# Thesis report (Savonia bachelor's thesis)

The thesis is written as Markdown, one file per chapter, and built into the Savonia reporting
template. The outputs are [`../thesis.docx`](../thesis.docx) and [`../thesis.pdf`](../thesis.pdf).

| File | Content |
| --- | --- |
| `00-front.md` | Title, cover and abstract-page fields (YAML block) and the abstract |
| `01-introduction.md` … `08-discussion.md` | Chapters 1–8 |
| `09-references.md` | References (Savonia Harvard style) and the AI-use entry |
| `10-appendix-1.md`, `11-appendix-2.md` | Appendices |
| `figures/` | Figures used in the report |
| `build.py` | Builds the .docx and .pdf from the files above |

## Build

```bash
python3 -m pip install python-docx pymupdf      # once
python3 thesis/report/build.py                  # needs LibreOffice (soffice) on the PATH
```

The script converts `Thesis Format/Reporting Template.odt` to .docx, fills in the cover page and
the abstract table, replaces the template's sample chapters with the chapters above, lets
LibreOffice update the table of contents and export the PDF, then fills in the list of figures
and the Pages/Appendices field from the PDF. Open the .docx in Word and update fields (F9) if you
edit it there.

Markdown conventions: `#` main chapter (numbered by the template), `##`/`###` subchapters,
`# References` and `# Appendix N: …` unnumbered; a line `Table N. …` directly before a table is its
title; `![…](figures/x.png)` followed by `Figure N. …` is a figure and its caption.

## Before submission

Placeholders are highlighted in yellow in the .docx/.pdf.

- [ ] **Step 8 (real AWS):** run `make aws-deploy aws-check aws-loadtest aws-cost aws-bill` and fill
      in the placeholders in `00-front.md` (abstract), `07-results.md` (Section 7.8 and Table 17,
      H6–H8) and `08-discussion.md` (RQ3, reliability).
- [ ] **Cover and abstract fields** in `00-front.md`: field of study, degree programme, date.
- [ ] **Your own voice:** Sections 8.4 (use of AI) and 8.7 (thesis process and professional
      growth) describe your process and learning; rewrite them so they are accurate for you.
- [ ] **Supervisor's preferences:** whether main chapters start with introductory text or
      directly with subchapters, and whether a list of tables or abbreviations is wanted.
- [ ] **Complete these references** (author lists, volume, pages or DOI could not be verified
      from this environment):
  - AI-driven self-healing across the edge–cloud continuum (2026): authors, volume, article number
  - Aldrini, Chihi & Sidhom (2023): volume, issue, pages
  - Cassel et al. (2021): check the year (published online 2021, volume 128 is 2022)
  - Holly et al. (2022): all authors, pages
  - Huang et al. (2019): all authors, volume, article number
  - Ronchieri et al. (2024): all authors, volume, article number
  - Rouholamini et al. (2024): all authors, volume, issue
  - Vajda et al. (2024): all authors, article number
  - Viola et al. (2022): all authors, article number
  - Benedetti et al. (2021), Shehabi et al. (2024): check the author lists
  - Accessed dates of internet sources (set to 18.11.2026)
- [ ] **Turnitin:** submit through Wihi as instructed by the degree programme.
