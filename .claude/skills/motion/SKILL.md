---
name: motion
description: Make a short animated explainer (MP4) from verified figures. It has title cards, counting KPI cards, growing bar charts and statement cards, in English or Arabic, rendered frame by frame from code like Claude Motion, so no video model is involved. Use when a deliverable needs motion, such as a presentation's animated opener or backup, a dashboard teaser, a capstone briefing clip or a social cut of a finding. The motion-designer subagent runs this skill.
---

# Motion

Anthropic's Claude Motion turns a prompt into an animated explainer by writing code, not by generating footage. It is a hosted beta in claude.ai on Team and Enterprise plans, with no API, so it cannot run in this repository. This skill does the same thing locally:

- a composition whose every frame is a pure function of time (`composition.html`);
- a renderer that steps through those frames in Chromium and encodes them with ffmpeg (`render.mjs`).

Change one number in the spec, render again, and only that number moves.

## When to use

- A deck needs an animated opener, a KPI reveal, or a video backup of the dashboard story.
- A finding needs a 10 to 30 second clip for a briefing or a post.
- Not for analysis: every figure must already exist in a verified source.

## The spec

A JSON file. The sizes allowed are 1920×1080 (default), 1280×720, 1080×1080 and 1080×1920. The frame rate is 24, 25, 30 (default) or 60. `language` is `en` or `ar` (right to left), and `theme` is `light`, `dark`, or `rta` / `rta-dark` (the user's house style from `.claude/skills/rta-style`: colours and type only, no logo or name).

| Scene `type` | Fields | Notes |
| --- | --- | --- |
| `title` | `kicker`, `title`, `subtitle` | The opening card |
| `kpis` | `heading`, `items` (1 to 4) | Each item counts up to its value |
| `bars` | `heading`, `items` (1 to 8), `note` | Horizontal bars grow from zero; `highlight: true` marks one in amber |
| `statement` | `text`, `figure`, `note` | One sentence, with an optional large figure |

Every scene has a `duration` of 1.5 to 15 seconds, and a clip is at most 90 seconds. An item or figure is written like this:

```json
{ "label": "Revenue", "value": 3583440, "format": "currency", "currency": "USD", "decimals": 0,
  "prefix": "", "suffix": "", "source": "sum(revenue), 72 rows" }
```

- **Sources are required.** `render.mjs` refuses any figure without a `source` that says where it was calculated: a file and a measure, or a formula. This is [the Soul's](../../../brain/Soul.md) first rule applied to video.
- **Formats:** `format` is `number` (default) or `currency`. For percentages, use `"suffix": "%"`; the value is the percentage itself.
- **Footers:** `footer` is a source line on every frame, and `brand` sits beside it.

Examples are in `examples/`, one in each language. Both use the bundled sample dataset, and `tests/test_motion.py` checks their figures against it.

## Commands

```bash
node .claude/skills/motion/render.mjs spec.json --check      # validate only: sizes, lengths, every source
node .claude/skills/motion/render.mjs spec.json out/clip.mp4
```

Rendering needs the frontend's Playwright (`npm --prefix frontend ci`), Chromium (`/opt/pw-browsers/chromium` or `PLAYWRIGHT_EXECUTABLE_PATH`) and `ffmpeg` on the path. A 17-second clip at 1080p and 30 fps takes about a minute here. Beside the MP4 it writes:

- `clip.poster.png`: the first figure scene once settled, or the scene numbered in `"poster"` (for example `1`, the title), for a slide or a thumbnail;
- `clip.sheet.png`: one frame per scene. **Read it before delivering**, and check overflow, contrast and text;
- `clip.txt`: every on-screen word and figure in order, exactly as shown, with a note number on each figure and the sources listed at the end: for alt text, captions and checking.

## Rules

1. **Figures** come from a verified register: the KPI register, a run's calculations, `Expected_Values.csv`. Say which in each `source`, in words the viewer can follow, such as "Report, Appendix A: Maintenance Cost", not a working file name.
2. **Course material stays out of Git.** Write specs and renders for the capstone to the scratchpad or a `private/` folder, never to the repository. Only the sample examples live here.
3. **One idea per scene.** At 1080p, labels are at least 23 px and headings much larger. Keep text short enough to read twice in the scene's time.
4. **No sound and no flashing.** Nothing changes more than three times a second. Deliver the transcript beside the MP4, so the content does not depend on seeing the motion.
5. **Arabic:** write the text in Arabic and keep figures as numbers. The composition isolates each figure so `US$` and `%` keep their order.
6. **Hosted Claude Motion:** if the team has Team or Enterprise, Claude Motion in claude.ai can make the same kind of clip interactively. Its MP4 can be opened in Adobe, Descript or Canva through their connectors. The same sourcing rule applies.
