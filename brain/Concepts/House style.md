---
type: concept
aliases: [RTA style, rta-style, Print variant]
tags: [design, output]
status: active
updated: 2026-10-17
review_every_days: 30
sources: [.claude/skills/rta-style/SKILL.md, .claude/skills/rta-style/tokens.json, Memory.md, docs/adr/0027-agents-are-measured.md]
---

# House style

The look of what the agents make: dashboards, clips, evaluation reports, and the capstone report and deck. It comes from the [[User]]'s own executive-dashboard work. It is not the app's interface, which follows the [[Design system]].

## Facts

- **Palettes.** One source, `.claude/skills/rta-style/tokens.json`, holds two palettes:
    - **Screens:** a red bar, navy and grey charts, light and dark.
    - **Print:** blue and white led, with red for the one figure to look at.
    - **Tested:** every text pair meets WCAG 2.2 AA (4.5:1) and every chart colour 3:1, in both modes (`tests/test_rta_style.py`).
- **Colours, type and layout only.** No logo, emblem, name or data of any organisation; themed outputs are tested for that.
    - **No official colours:** RTA publishes no colour codes.
    - **The red is not RTA's:** #C8102E is Pantone 186, the UAE flag red. So the style is "RTA-inspired", never official.
- **Typeface (17 October 2026, the user's choice).** IBM Plex Sans with IBM Plex Sans Arabic: one system for English and Arabic, under the SIL Open Font License, so PDFs and slides can embed it.
    - Dubai, the Dubai Government's font, can replace it where its files are supplied. The Dubai Design System allows either.
    - RTA's own typeface is a private commission, so it is never used.
- **Applied at build time.** `restyle.py` recolours HTML by role and checks each text colour against its real background, and no words change. The capstone files were restyled this way, and the review gates were unchanged afterwards.

## Related

- [[Home]]
- [[User]]: whose look it is, and who chose the typeface.
- [[Design system]]: the app's own interface rules, kept separate.
- [[Team 3 Capstone]]: the report and deck that wear the print variant.
- [[Agent evaluation]]: its report page is the screen variant's first use.
