---
type: project
aliases: [Capstone, Group 9226 capstone]
tags: [project, course]
status: active
updated: 2026-10-17
review_every_days: 3
sources: [project-progress.md, docs/AGENT_TEAM.md, Memory.md]
---

# Team 3 Capstone

The course capstone of the [[User]]'s team: an executive analytics package on predictive maintenance and asset reliability, built from the [[Team 3 maintenance dataset]].

## Deliverables and dates

| Deliverable | Format | State on 2026-10-17 |
| --- | --- | --- |
| Executive dashboard | Power BI `.pbix` | Build kit ready: Power Query, DAX, theme, 30 expected values. Not yet built: only Power BI Desktop can save a `.pbix` |
| Executive presentation | `.pptx`, 12 to 15 slides | Release candidate: 15 slides, 16:9, with speaker notes and alt text, in the [[House style]] |
| Analytical report | `.pdf`, 20 to 25 pages | Release candidate: 23 A4 pages with a cover and contents, in the [[House style]]; team-owned items highlighted |

- Moodle submission closes on 22 October 2026, and the team uploads on 21 October 2026 to keep a buffer.
- The team presents to the instructors on 25 October 2026.
- Reconciled on 16 October: all 30 expected dashboard values agree with the report, three of them rounded there to whole hours, and every number in the deck appears in the report, exactly or abbreviated. A submission checklist went to the user with the files.
- **Reviewed on 16 October** by the [[Agent team]]'s review loop. The gates went 50.0% → 62.5%; all ten the session could act on pass.
    - The build fixes are in the files: a tagged PDF with bookmarks, titled slides with readable alt text, and clip sources a reader can follow.
    - The rest is the team's: the `.pbix`, their highlighted items, and corrections to two headline claims. The corrections went to the user as a memo, with recomputed figures and replacement wording.
- **Restyled on 17 October**, at the user's request: blue and white, IBM Plex Sans, no logos. The style is applied when the files are built, so the team's text is untouched. The gates were unchanged, with the same ten passing in round 6, and the Power BI theme in the kit matches.

The plan, the report draft and the deck draft are private documents shared with the team. Roles, names and registration numbers stay there, never in this public repository.

## What carries over to the product

- **Measuring correctly:** one weighted register for every KPI ([[Weighted KPIs]]). The review showed the first row-average comparison was not like for like. Placeholder rates in 985 preventive records inflated the gaps. The stored SLA score (75.8%) is a capped ratio, a different measure from the 46.1% of targets met.
- **Checking identity before analysis:** the dataset's asset IDs repeat every 180 rows, so the record, not the asset, is the unit of analysis.
- **Honest models:** on all 2026 records a classifier beat the supplied score by 0.02 AUC (0.746 against 0.727). On the 792 corrective records, where the question is real, the gain's 95% interval includes zero (−0.010 to +0.035). A rule by work-order type also beat the downtime model. So the recommendation is a pilot, not a rollout ([[Soul]]).
- **Look past the obvious cut:** failure modes were a flat Pareto.
    - **Stockouts:** records with a stockout average twice the downtime, but also twice the failures. Downtime per failure is about the same (12.4 h against 12.0 h), so they mark repeated failure; the data cannot show that they lengthen outages.
    - **Reactive maintenance:** worst per record, by 27% on corrective records once preventive placeholders are set aside.
    - **Totals:** monthly loss "fell 39%" only because 2026 months hold half the records. Per record it was flat (ADR 0026).
- **Dashboard expectations:** landing page, slicers, drill-through and a ranked action queue, which feed the [[Analytics OS roadmap]].

## Related

- [[Agentic OS]]: the product whose methods the analysis reuses.
- [[Team collaboration]]: how the five members share work.
