# ADR 0033 — Modelling stages: four models as plugins, each against its baseline

**Status:** Accepted
**Date:** 2026-10-17
**Milestone:** A6 in `project-progress.md`; phase 5 of `docs/UI_PLAN.md`
**Keeps:** custom stages as plugins under the same governance (ADR 0020), reports in the reader's language (ADR 0022), measured agents (ADR 0027), the standard-library core, no statistical jargon in claims

## Context

The pipeline's only model is a straight-line trend with a backtest. The questions an analytics team asks next need more:

- **What predicts the measure?** A regression on the other columns.
- **Which records are likely to be high-value, or in a given class?** A classification.
- **Do the records fall into natural groups?** A clustering.
- **Does the measure follow a season?** A seasonal forecast.

Every one of these can look impressive and be worthless. A model is only worth reporting against what a person would have guessed without it, so **every model here reports its baseline**, and a model that does not beat it is reported as weak, never dressed up.

## Decision

### 1. Four plugins, shipped and registered, not built in

`server/modelling.py` holds four stages written to the ADR 0020 contract: `RegressionModel`, `ClassificationModel`, `ClusteringModel` and `SeasonalForecast`. They run after the Sensitivity Agent, so provenance, validation and reporting audit them like any custom stage. `config.json` registers them and a profile named `models` selects them; the `default` profile stays empty, so a run that does not ask for models has exactly the stages it had.

Standard library only: least squares by Gaussian elimination, a naive Bayes classifier, k-means with a seeded start, an additive trend-and-season model. Every figure has a method string a reader can recompute.

### 2. How each model is tested, and against what

| Model | Target | Held out | Model metric | Baseline |
| --- | --- | --- | --- | --- |
| Regression | The run's measure | The latest 20% of periods, or every fifth record without a date | Average error on held-out records | The training average |
| Classification | A text column named in the options, else "is this record in the top quarter of the measure?" | As above | Balanced accuracy (the average of each class's hit rate) | Always the most common class |
| Clustering | Natural groups in the measures | Not applicable | Share of the spread the groups explain, and how well separated they are (0 to 1) | One group: nothing explained |
| Seasonal forecast | The measure's total per period | The last full season | Average error on the held-out season | The best of "same as last period", "same as a season ago" and the straight trend alone, so a season is only found when it adds to the trend |

A model **beats its baseline** when it improves on it by at least 5%; clustering counts as found when the groups are separated by at least 0.25 on the 0–1 scale. Otherwise the stage succeeds and says, as a limitation claim, that the model is weak and should not be used. Too few records (under 30) or periods (under three seasons) is a limitation, not a failure.

Inputs are every other measure, and up to three text columns with at most ten values each, as indicators. A model cannot know which columns were recorded after the outcome, so every model says so: an input observed after the outcome makes a model look better than it is.

### 3. The model card

Each stage puts a `model_card` in its output: kind, target, inputs, records used for training and testing, how they were split, the metric for the model and for its baseline, whether the model beats it and by how much, and the details a reader needs (coefficients, class hit rates, group profiles, the next season's forecast). `GET /api/runs/{id}` lists the cards as `models`, and the Runs view shows them with the verdict first.

### 4. Two additions to the plugin contract

- A claim may carry `text_ar` beside `text`. The Validation Expert already checks that both cite the same figures, so a plugin's claims are held to the same rule as the built-in ones.
- A descriptor may carry `title_ar`, used as the task's title in an Arabic run.

Each model writes its summary, headline and report section in the run's language.

## Consequences

- A run can answer "what predicts this, and how well?" with a number that means something: its improvement over the obvious guess.
- A weak model is a finding. "Nothing here predicts the measure better than its average" is reported, with the figures that show it.
- The models are associations. The regression's coefficients say what moves with the measure, not what moves it, and the claims say so.

## Not done here

- Trees, ensembles, neural models or anything that needs a library outside the standard one.
- Choosing inputs by when they were recorded; that needs the owner's word, which the mapping does not yet carry.
- Tuning beyond the fixed, documented settings; tuning on the held-out data would make the comparison with the baseline dishonest.
