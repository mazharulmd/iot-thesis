# Thesis plan for the supervisor meeting

| File | Content |
| --- | --- |
| `project-plan.pptx` | Seven-slide project plan: overview, problem and research questions, architecture, closed loop and guardrails, detection and operating modes, evaluation plan, roadmap and deliverables |
| `thesis-plan.docx` / `.pdf` | Thesis plan in the Savonia reporting template: title, planned abstract, table of contents with the planned content of every chapter, key references, and the work plan and schedule (Appendix 1) |
| `00-front.md` … `10-appendix-1.md` | Sources of the thesis plan |

Build:

```bash
python3 thesis/plan/build_plan.py                                  # thesis-plan.docx and .pdf (uses thesis/report/build.py)
NODE_PATH=<node_modules with pptxgenjs, react-icons, react, react-dom, sharp> node thesis/plan/make_deck.js
```

Before the meeting, fill in the degree programme and the date in `00-front.md`, and adjust the weeks in
Appendix 1 to the real schedule.
