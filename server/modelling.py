"""Modelling stages (ADR 0033): four models as plugins, each against its
baseline.

A model is only worth reporting against what a person would have guessed
without it, so every stage here holds back records it never trained on,
measures the model and a plain baseline on them, and says which won. A
model that does not beat its baseline by at least 5% is reported as weak,
with the figures that show it.

The stages follow the custom-stage contract (ADR 0020): they read a copy
of the run's context, change nothing, give every figure a method a reader
can recompute, and run before provenance, validation and reporting, which
audit them like any other stage. Standard library only:

- RegressionModel     least squares on the other columns
- ClassificationModel a naive Bayes classifier of a class, or of the top
                      quarter of the measure
- ClusteringModel     k-means, choosing the number of groups by how well
                      separated they are
- SeasonalForecast    trend plus a repeating season, backtested on the
                      last season

What a model finds is an association. The claims say what moves with
the measure, never what moves it.
"""

import math
import random
import statistics
from collections import Counter

from server import analytics

MIN_ROWS = 30
# A model beats its baseline when it improves on it by at least this much.
BEATS = 0.05
# Groups count as found when they are at least this well separated (0 to 1).
SEPARATED = 0.25
MAX_NUMERIC_INPUTS = 12
MAX_TEXT_INPUTS = 3
MAX_LEVELS = 10
MAX_CLASSES = 6
# Records a model trains on, evenly spaced, so a 50,000-row run stays fast.
TRAIN_CAP = 5000
CLUSTER_CAP = 2000
SILHOUETTE_CAP = 400
SEASONS = {"day": 7, "month": 12, "quarter": 4}
RIDGE = 1e-3


# ---------------------------------------------------------------------------
# Shared parts
# ---------------------------------------------------------------------------

def _arabic(ctx):
    return analytics.report_language(ctx) == "ar"


def _say(ctx, en, ar):
    return ar if _arabic(ctx) else en


def _claim(ctx, role, name, kind, en, ar, evidence):
    claim = {"id": f"{role}.{name}", "type": kind, "text": en,
             "evidence": [f"{role}.{e}" for e in evidence], "status": "verified"}
    if _arabic(ctx):
        claim["text_ar"] = ar
    return claim


def _calc(role, name, label, value, method):
    return {"id": f"{role}.{name}", "name": label, "value": value, "method": method}


def _even(items, cap):
    """At most `cap` items, evenly spaced, in order."""
    if len(items) <= cap:
        return list(items)
    step = len(items) / cap
    return [items[int(index * step)] for index in range(cap)]


def _table(ctx):
    return (analytics._rows(ctx), analytics._columns(ctx), analytics._numeric(ctx),
            ctx["governance"]["measure"], ctx["preparer"].get("date_col"))


def _inputs(rows, columns, numeric, exclude):
    """Numeric inputs, and text inputs with their levels (most common first,
    which is the level the others are compared with)."""
    numbers = [c for c in numeric if c not in exclude][:MAX_NUMERIC_INPUTS]
    texts = []
    for column in columns:
        if column in numeric or column in exclude:
            continue
        levels = Counter(str(row.get(column) or "") for row in rows)
        if 2 <= len(levels) <= MAX_LEVELS:
            texts.append((column, [level for level, _ in levels.most_common()]))
        if len(texts) == MAX_TEXT_INPUTS:
            break
    return numbers, texts


def _vectoriser(numbers, texts):
    names = list(numbers) + [f"{column} = {level}" for column, levels in texts
                             for level in levels[1:]]

    def vector(row):
        values = []
        for column in numbers:
            value = row.get(column)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return None
            values.append(float(value))
        for column, levels in texts:
            value = str(row.get(column) or "")
            values += [1.0 if value == level else 0.0 for level in levels[1:]]
        return values
    return names, vector


def _split(rows, date):
    """Training and held-out positions: the latest fifth of the periods when
    the run has a date, otherwise every fifth record."""
    if date:
        periods = sorted({row.get(date) for row in rows if row.get(date) not in (None, "")},
                         key=str)
        if len(periods) >= 5:
            first = periods[int(len(periods) * 0.8)]
            train = [i for i, row in enumerate(rows)
                     if row.get(date) not in (None, "") and str(row[date]) < str(first)]
            test = [i for i, row in enumerate(rows)
                    if row.get(date) not in (None, "") and str(row[date]) >= str(first)]
            return train, test, {"kind": "time", "first_held_out": first}
    train = [i for i in range(len(rows)) if i % 5]
    test = [i for i in range(len(rows)) if not i % 5]
    return train, test, {"kind": "every_fifth"}


def _split_text(ctx, split):
    if split["kind"] == "time":
        return _say(ctx, f"trained on periods before {split['first_held_out']}, tested from it on",
                    f"دُرّب على الفترات قبل {split['first_held_out']} واختُبر من بعدها")
    return _say(ctx, "every fifth record held out for testing",
                "أُبقي كل خامس سجل جانباً للاختبار")


def _scaler(vectors):
    width = len(vectors[0])
    means = [statistics.fmean(v[i] for v in vectors) for i in range(width)]
    spreads = []
    for i in range(width):
        spread = math.sqrt(statistics.fmean((v[i] - means[i]) ** 2 for v in vectors))
        spreads.append(spread or 1.0)
    return lambda v: [(x - m) / s for x, m, s in zip(v, means, spreads)]


def _improvement(model, baseline, lower_is_better):
    if not baseline:
        return 0.0
    return (baseline - model) / baseline if lower_is_better else (model - baseline) / baseline


def _weak(ctx, role, label_en, label_ar, improvement):
    """The claim a weak model makes about itself."""
    return _claim(
        ctx, role, "cl_weak", "limitation",
        f"The {label_en} does not beat its baseline by the 5% needed "
        f"(it improves on it by {improvement:.0%}), so it should not be used to "
        "make decisions.",
        f"لا يتفوق {label_ar} على خط الأساس بنسبة 5% المطلوبة (يتحسن عليه بنسبة "
        f"{improvement:.0%})، فلا ينبغي استخدامه في اتخاذ القرارات.",
        ["c_improvement"])


def _leakage(ctx, role):
    return _claim(
        ctx, role, "cl_inputs", "limitation",
        "The model uses every other measure as an input. A measure recorded after "
        "the outcome would make it look better than it is.",
        "يستخدم النموذج كل مقياس آخر مدخلاً. والمقياس المسجَّل بعد النتيجة يجعله يبدو "
        "أفضل مما هو عليه.",
        ["c_inputs"])


def _thin(ctx, role, title, needed, have, what_en, what_ar):
    calcs = [_calc(role, "c_available", f"{what_en}_available", have,
                   f"usable {what_en} for this model")]
    text_en = (f"There are {have} usable {what_en}; this model needs at least {needed}, "
               "so it was not fitted.")
    text_ar = (f"يوجد {have} من {what_ar} الصالحة، ويحتاج هذا النموذج إلى {needed} على "
               "الأقل، فلم يُبنَ.")
    summary = _say(ctx, text_en, text_ar)
    return {"status": "succeeded", "summary": summary,
            "claims": [_claim(ctx, role, "cl_thin", "limitation", text_en, text_ar,
                              ["c_available"])],
            "calculations": calcs, "quality_checks": [],
            "output": {"headline": summary, "fitted": False,
                       "report_markdown": _section(ctx, title, summary, calcs)}}


def _section(ctx, title, headline, calculations, lines=()):
    out = [f"# {title}", "", f"**{headline}**", ""]
    out += list(lines)
    if calculations:
        out += ["", _say(ctx, "| Figure | Value | Method |", "| الرقم | القيمة | الطريقة |"),
                "| --- | --- | --- |"]
        out += [f"| {c['name']} | {c['value']} | {c['method']} |" for c in calculations]
    return "\n".join(out)


def _card(kind, target, inputs, train, test, split, metric, model, baseline,
          baseline_name, improvement, beats, details):
    return {"kind": kind, "target": target, "inputs": inputs, "train_records": train,
            "test_records": test, "split": split,
            "metric": {"name": metric, "model": model, "baseline": baseline,
                       "baseline_name": baseline_name},
            "improvement": improvement, "beats_baseline": beats, "details": details}


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------

def _solve(matrix, vector):
    """Gaussian elimination with partial pivoting. None when singular."""
    size = len(vector)
    rows = [list(matrix[i]) + [vector[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(col + 1, size):
            factor = rows[r][col] / rows[col][col]
            if factor:
                for c in range(col, size + 1):
                    rows[r][c] -= factor * rows[col][c]
    solution = [0.0] * size
    for r in range(size - 1, -1, -1):
        solution[r] = (rows[r][size] - sum(rows[r][c] * solution[c]
                                           for c in range(r + 1, size))) / rows[r][r]
    return solution


def fit_least_squares(vectors, targets, ridge=RIDGE):
    """Coefficients and the intercept by least squares on centred inputs,
    with a small ridge so a repeated input cannot break it. A prediction
    is intercept + Σ coefficient × input."""
    width = len(vectors[0])
    mean = statistics.fmean(targets)
    centres = [statistics.fmean(v[i] for v in vectors) for i in range(width)]
    gram = [[0.0] * width for _ in range(width)]
    cross = [0.0] * width
    for vector, target in zip(vectors, targets):
        centred = target - mean
        x = [vector[i] - centres[i] for i in range(width)]
        for i in range(width):
            xi = x[i]
            cross[i] += xi * centred
            row = gram[i]
            for j in range(i, width):
                row[j] += xi * x[j]
    n = len(vectors)
    for i in range(width):
        gram[i][i] += ridge * n
        for j in range(i):
            gram[i][j] = gram[j][i]
    coefficients = _solve(gram, cross) or [0.0] * width
    return coefficients, mean - sum(c * m for c, m in zip(coefficients, centres))


def fit_naive_bayes(vectors, labels):
    """Per class: its share, and each input's average and spread."""
    model = {}
    for label in sorted(set(labels)):
        members = [v for v, l in zip(vectors, labels) if l == label]
        width = len(members[0])
        means = [statistics.fmean(m[i] for m in members) for i in range(width)]
        spreads = [max(statistics.fmean((m[i] - means[i]) ** 2 for m in members), 1e-3)
                   for i in range(width)]
        model[label] = (math.log(len(members) / len(vectors)), means, spreads)
    return model


def predict_naive_bayes(model, vector):
    best, score = None, -math.inf
    for label, (prior, means, spreads) in model.items():
        total = prior
        for x, m, s in zip(vector, means, spreads):
            total -= (x - m) ** 2 / (2 * s) + 0.5 * math.log(s)
        if total > score:
            best, score = label, total
    return best


def _distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def kmeans(points, k, seed=7, iterations=60):
    """Groups by k-means, started k-means++ style from a fixed seed."""
    rng = random.Random(seed + k)
    centres = [points[rng.randrange(len(points))]]
    while len(centres) < k:
        weights = [min(_distance(p, c) for c in centres) for p in points]
        total = sum(weights)
        if not total:
            break
        pick, running = rng.random() * total, 0.0
        for point, weight in zip(points, weights):
            running += weight
            if running >= pick:
                centres.append(point)
                break
    assignment = [0] * len(points)
    for _ in range(iterations):
        changed = False
        for index, point in enumerate(points):
            nearest = min(range(len(centres)), key=lambda c: _distance(point, centres[c]))
            if nearest != assignment[index]:
                assignment[index], changed = nearest, True
        for c in range(len(centres)):
            members = [p for p, a in zip(points, assignment) if a == c]
            if members:
                centres[c] = [statistics.fmean(m[i] for m in members)
                              for i in range(len(points[0]))]
        if not changed:
            break
    spread = sum(_distance(p, centres[a]) for p, a in zip(points, assignment))
    return assignment, centres, spread


def silhouette(points, assignment):
    """How well separated the groups are, from -1 to 1 (Rousseeuw, 1987)."""
    groups = set(assignment)
    if len(groups) < 2:
        return 0.0
    scores = []
    for index, point in enumerate(points):
        own = assignment[index]
        by_group = {}
        for other, (q, group) in enumerate(zip(points, assignment)):
            if other != index:
                by_group.setdefault(group, []).append(math.sqrt(_distance(point, q)))
        if not by_group.get(own):
            scores.append(0.0)
            continue
        inside = statistics.fmean(by_group[own])
        nearest = min(statistics.fmean(d) for g, d in by_group.items() if g != own)
        scores.append((nearest - inside) / max(inside, nearest) if max(inside, nearest) else 0.0)
    return statistics.fmean(scores)


def seasonal_fit(series, season, rounds=8):
    """A straight trend plus an average repeating season, fitted in turn
    until each settles: the trend on the series without its season, the
    season on the series without its trend."""
    pattern = [0.0] * season
    slope = intercept = 0.0
    for _ in range(rounds):
        slope, intercept, _ = analytics._linear_fit(
            [value - pattern[index % season] for index, value in enumerate(series)])
        leftovers = [value - (intercept + slope * index) for index, value in enumerate(series)]
        pattern = []
        for position in range(season):
            values = leftovers[position::season]
            pattern.append(statistics.fmean(values) if values else 0.0)
        centre = statistics.fmean(pattern)
        pattern = [p - centre for p in pattern]
    return slope, intercept, pattern


def seasonal_forecast(series, season, steps):
    slope, intercept, pattern = seasonal_fit(series, season)
    start = len(series)
    return [intercept + slope * (start + i) + pattern[(start + i) % season]
            for i in range(steps)]


# ---------------------------------------------------------------------------
# The stages
# ---------------------------------------------------------------------------

class RegressionModel:
    role = "regression_model"
    title = "Regression Model Agent — what predicts the measure?"
    title_ar = "وكيل نموذج التنبؤ بالمقياس: ما الذي يتنبأ به؟"
    after = "sensitivity"
    question = "What predicts the measure, and how well?"
    can_fail_run = False

    def run(self, ctx):
        role = self.role
        rows, columns, numeric, measure, date = _table(ctx)
        title = _say(ctx, "What predicts the measure?", "ما الذي يتنبأ بالمقياس؟")
        exclude = {measure, date}
        numbers, texts = _inputs(rows, columns, numeric, exclude)
        names, vector = _vectoriser(numbers, texts)
        if not names:
            return _thin(ctx, role, title, 1, 0, "inputs", "المدخلات")
        usable = [i for i, row in enumerate(rows)
                  if isinstance(row.get(measure), (int, float)) and vector(row) is not None]
        if len(usable) < MIN_ROWS:
            return _thin(ctx, role, title, MIN_ROWS, len(usable), "records", "السجلات")
        subset = [rows[i] for i in usable]
        train, test, split = _split(subset, date)
        if len(train) < MIN_ROWS - 10 or len(test) < 5:
            train, test, split = _split(subset, None)
        train_rows = _even([subset[i] for i in train], TRAIN_CAP)
        test_rows = [subset[i] for i in test]
        raw = [vector(r) for r in train_rows]
        scale = _scaler(raw)
        coefficients, intercept = fit_least_squares([scale(v) for v in raw],
                                                    [r[measure] for r in train_rows])

        def predict(row):
            return intercept + sum(c * x for c, x in zip(coefficients, scale(vector(row))))

        actual = [r[measure] for r in test_rows]
        predicted = [predict(r) for r in test_rows]
        model_error = statistics.fmean(abs(a - p) for a, p in zip(actual, predicted))
        base_error = statistics.fmean(abs(a - intercept) for a in actual)
        mean_actual = statistics.fmean(actual)
        total = sum((a - mean_actual) ** 2 for a in actual)
        explained = 1 - sum((a - p) ** 2 for a, p in zip(actual, predicted)) / total if total else 0.0
        improvement = _improvement(model_error, base_error, lower_is_better=True)
        beats = improvement >= BEATS
        ranked = sorted(zip(names, coefficients), key=lambda nc: -abs(nc[1]))[:5]

        calcs = [
            _calc(role, "c_inputs", "inputs", len(names),
                  f"other measures and indicators of up to {MAX_TEXT_INPUTS} text columns"),
            _calc(role, "c_train", "training_records", len(train_rows),
                  f"records before the held-out ones, at most {TRAIN_CAP} evenly spaced"),
            _calc(role, "c_test", "held_out_records", len(test_rows), split["kind"]),
            _calc(role, "c_model_error", "model_average_error", round(model_error, 4),
                  f"mean of |actual − predicted| {measure} on held-out records, "
                  "least squares on standardised inputs (ridge 0.001)"),
            _calc(role, "c_base_error", "baseline_average_error", round(base_error, 4),
                  f"mean of |actual − training average| {measure} on held-out records"),
            _calc(role, "c_improvement", "improvement_over_baseline", round(improvement, 4),
                  "(baseline error − model error) / baseline error"),
            _calc(role, "c_explained", "held_out_share_explained", round(explained, 4),
                  "1 − squared errors / squared spread around the held-out average"),
        ]
        claims = [
            _claim(ctx, role, "cl_fit", "calculation",
                   f"On {len(test_rows)} records the model never saw, its average error in "
                   f"{measure} is {model_error:,.2f}, against {base_error:,.2f} for always "
                   f"guessing the average: {improvement:.0%} better.",
                   f"على {len(test_rows)} من السجلات التي لم يرها النموذج، متوسط خطئه في "
                   f"{measure} هو {model_error:,.2f} مقابل {base_error:,.2f} عند تخمين "
                   f"المتوسط دائماً: أفضل بنسبة {improvement:.0%}.",
                   ["c_model_error", "c_base_error", "c_improvement", "c_test"]),
            _leakage(ctx, role),
        ]
        if beats and ranked:
            top_name, top_value = ranked[0]
            direction_en = "higher" if top_value > 0 else "lower"
            direction_ar = "أعلى" if top_value > 0 else "أدنى"
            claims.append(_claim(
                ctx, role, "cl_strongest", "fact",
                f"Of the inputs, {top_name} moves most with {measure}: records with more of "
                f"it tend to have {direction_en} {measure}. This is an association, not a "
                "cause.",
                f"من بين المدخلات، {top_name} هو الأكثر تحركاً مع {measure}: السجلات الأعلى "
                f"فيه تميل إلى {measure} {direction_ar}. وهذا ارتباط لا سبب.",
                ["c_model_error", "c_inputs"]))
        else:
            claims.append(_weak(ctx, role, "regression model", "نموذج التنبؤ", improvement))
        headline = _say(
            ctx,
            (f"The other columns predict {measure} {improvement:.0%} better than its average."
             if beats else
             f"Nothing here predicts {measure} much better than its average "
             f"({improvement:.0%} better)."),
            (f"تتنبأ الأعمدة الأخرى بـ {measure} أفضل من متوسطه بنسبة {improvement:.0%}."
             if beats else
             f"لا شيء هنا يتنبأ بـ {measure} أفضل كثيراً من متوسطه (أفضل بنسبة "
             f"{improvement:.0%})."))
        lines = [_say(ctx, "| Input | Weight on the measure |", "| المدخل | الوزن على المقياس |"),
                 "| --- | --- |"]
        lines += [f"| {name} | {value:,.4f} |" for name, value in ranked]
        lines += ["", _split_text(ctx, split) + "."]
        return {
            "status": "succeeded", "summary": headline, "claims": claims,
            "calculations": calcs,
            "quality_checks": [{"name": "regression_beats_its_baseline", "passed": beats,
                                "detail": _say(ctx, f"{improvement:.1%} better than the average.",
                                               f"أفضل من المتوسط بنسبة {improvement:.1%}.")}],
            "output": {
                "headline": headline, "fitted": True,
                "question": _say(ctx, self.question, "ما الذي يتنبأ بالمقياس، وبأي دقة؟"),
                "report_markdown": _section(ctx, title, headline, calcs, lines),
                "model_card": _card(
                    "regression", measure, names, len(train_rows), len(test_rows), split,
                    "average_error", round(model_error, 4), round(base_error, 4),
                    "training_average", round(improvement, 4), beats,
                    {"weights": [{"input": n, "weight": round(v, 6)} for n, v in ranked],
                     "held_out_share_explained": round(explained, 4)}),
            },
        }


class ClassificationModel:
    role = "classification_model"
    title = "Classification Model Agent — which class will a record be in?"
    title_ar = "وكيل نموذج التصنيف: في أي فئة سيقع السجل؟"
    after = "sensitivity"
    question = "Which class will a record be in, and how reliably?"
    can_fail_run = False

    def __init__(self, target=None):
        self.target = target

    def run(self, ctx):
        role = self.role
        rows, columns, numeric, measure, date = _table(ctx)
        title = _say(ctx, "Which class will a record be in?", "في أي فئة سيقع السجل؟")
        if self.target and self.target in columns and self.target not in numeric:
            target = self.target
            labels_of = lambda row: str(row.get(target) or "")  # noqa: E731
            exclude = {target, date}
            target_name = target
        else:
            values = sorted(r[measure] for r in rows if isinstance(r.get(measure), (int, float)))
            if len(values) < MIN_ROWS:
                return _thin(ctx, role, title, MIN_ROWS, len(values), "records", "السجلات")
            cut = values[int(len(values) * 0.75)]
            top_en = _say(ctx, "top quarter", "الربع الأعلى")
            rest_en = _say(ctx, "rest", "البقية")
            labels_of = lambda row: (top_en if isinstance(row.get(measure), (int, float))  # noqa: E731
                                     and row[measure] >= cut else rest_en)
            exclude = {measure, date}
            target_name = _say(ctx, f"{measure} in its top quarter (≥ {cut:,.2f})",
                               f"{measure} في ربعه الأعلى (≥ {cut:,.2f})")
        numbers, texts = _inputs(rows, columns, numeric, exclude)
        names, vector = _vectoriser(numbers, texts)
        if not names:
            return _thin(ctx, role, title, 1, 0, "inputs", "المدخلات")
        usable = [r for r in rows if vector(r) is not None]
        if len(usable) < MIN_ROWS:
            return _thin(ctx, role, title, MIN_ROWS, len(usable), "records", "السجلات")
        classes = Counter(labels_of(r) for r in usable)
        if len(classes) < 2:
            return _thin(ctx, role, title, 2, len(classes), "classes", "الفئات")
        if len(classes) > MAX_CLASSES:
            return _too_many_classes(ctx, role, title, target_name, len(classes))
        train, test, split = _split(usable, date)
        if len(train) < MIN_ROWS - 10 or len(test) < 5:
            train, test, split = _split(usable, None)
        train_rows = _even([usable[i] for i in train], TRAIN_CAP)
        test_rows = [usable[i] for i in test]
        raw = [vector(r) for r in train_rows]
        scale = _scaler(raw)
        train_labels = [labels_of(r) for r in train_rows]
        if len(set(train_labels)) < 2:
            return _thin(ctx, role, title, 2, 1, "classes", "الفئات")
        model = fit_naive_bayes([scale(v) for v in raw], train_labels)
        majority = Counter(train_labels).most_common(1)[0][0]
        actual = [labels_of(r) for r in test_rows]
        predicted = [predict_naive_bayes(model, scale(vector(r))) for r in test_rows]
        present = sorted(set(actual))

        def balanced(guesses):
            hits = []
            for label in present:
                members = [g for a, g in zip(actual, guesses) if a == label]
                hits.append(sum(1 for g in members if g == label) / len(members))
            return statistics.fmean(hits)

        model_score = balanced(predicted)
        base_score = balanced([majority] * len(actual))
        accuracy = sum(1 for a, p in zip(actual, predicted) if a == p) / len(actual)
        improvement = _improvement(model_score, base_score, lower_is_better=False)
        beats = improvement >= BEATS
        confusion = {label: dict(Counter(p for a, p in zip(actual, predicted) if a == label))
                     for label in present}
        hit_rates = {label: round(confusion[label].get(label, 0) / sum(confusion[label].values()), 4)
                     for label in present}
        calcs = [
            _calc(role, "c_inputs", "inputs", len(names),
                  f"other measures and indicators of up to {MAX_TEXT_INPUTS} text columns"),
            _calc(role, "c_train", "training_records", len(train_rows),
                  f"records before the held-out ones, at most {TRAIN_CAP} evenly spaced"),
            _calc(role, "c_test", "held_out_records", len(test_rows), split["kind"]),
            _calc(role, "c_model_score", "model_balanced_accuracy", round(model_score, 4),
                  "average over classes of the share of held-out records of that class "
                  "classified correctly (naive Bayes on standardised inputs)"),
            _calc(role, "c_base_score", "baseline_balanced_accuracy", round(base_score, 4),
                  f"the same, always guessing the most common training class “{majority}”"),
            _calc(role, "c_accuracy", "model_accuracy", round(accuracy, 4),
                  "share of held-out records classified correctly"),
            _calc(role, "c_improvement", "improvement_over_baseline", round(improvement, 4),
                  "(model − baseline) / baseline, balanced accuracy"),
        ]
        claims = [
            _claim(ctx, role, "cl_fit", "calculation",
                   f"On {len(test_rows)} records the model never saw, it gets each class "
                   f"right {model_score:.0%} of the time on average, against "
                   f"{base_score:.0%} for always guessing “{majority}”: "
                   f"{improvement:.0%} better.",
                   f"على {len(test_rows)} من السجلات التي لم يرها النموذج، يصيب في كل فئة "
                   f"بنسبة {model_score:.0%} في المتوسط، مقابل {base_score:.0%} عند تخمين "
                   f"«{majority}» دائماً: أفضل بنسبة {improvement:.0%}.",
                   ["c_model_score", "c_base_score", "c_improvement", "c_test"]),
            _leakage(ctx, role),
        ]
        if not beats:
            claims.append(_weak(ctx, role, "classifier", "نموذج التصنيف", improvement))
        headline = _say(
            ctx,
            (f"The classifier gets each class right {model_score:.0%} of the time, "
             f"{improvement:.0%} better than guessing the most common one."
             if beats else
             f"The classifier does not beat guessing the most common class "
             f"({improvement:.0%} better)."),
            (f"يصيب نموذج التصنيف في كل فئة بنسبة {model_score:.0%}، أفضل بنسبة "
             f"{improvement:.0%} من تخمين الفئة الأكثر شيوعاً."
             if beats else
             f"لا يتفوق نموذج التصنيف على تخمين الفئة الأكثر شيوعاً (أفضل بنسبة "
             f"{improvement:.0%})."))
        lines = [_say(ctx, "| Class | Held-out records | Classified correctly |",
                      "| الفئة | السجلات المختبرة | المصنفة صحيحاً |"), "| --- | --- | --- |"]
        lines += [f"| {label} | {sum(confusion[label].values())} | {hit_rates[label]:.0%} |"
                  for label in present]
        lines += ["", _split_text(ctx, split) + "."]
        return {
            "status": "succeeded", "summary": headline, "claims": claims,
            "calculations": calcs,
            "quality_checks": [{"name": "classifier_beats_its_baseline", "passed": beats,
                                "detail": _say(ctx, f"{improvement:.1%} better than the most "
                                                    "common class.",
                                               f"أفضل من الفئة الأكثر شيوعاً بنسبة "
                                               f"{improvement:.1%}.")}],
            "output": {
                "headline": headline, "fitted": True,
                "question": _say(ctx, self.question, "في أي فئة سيقع السجل، وبأي موثوقية؟"),
                "report_markdown": _section(ctx, title, headline, calcs, lines),
                "model_card": _card(
                    "classification", target_name, names, len(train_rows), len(test_rows),
                    split, "balanced_accuracy", round(model_score, 4), round(base_score, 4),
                    "most_common_class", round(improvement, 4), beats,
                    {"classes": present, "hit_rates": hit_rates, "confusion": confusion,
                     "accuracy": round(accuracy, 4), "majority": majority}),
            },
        }


class ClusteringModel:
    role = "clustering_model"
    title = "Clustering Model Agent — do the records fall into groups?"
    title_ar = "وكيل نموذج التجميع: هل تنقسم السجلات إلى مجموعات؟"
    after = "sensitivity"
    question = "Do the records fall into natural groups?"
    can_fail_run = False

    def run(self, ctx):
        role = self.role
        rows, columns, numeric, measure, date = _table(ctx)
        title = _say(ctx, "Do the records fall into groups?", "هل تنقسم السجلات إلى مجموعات؟")
        features = [c for c in numeric if c != date][:MAX_NUMERIC_INPUTS]
        if len(features) < 2:
            return _thin(ctx, role, title, 2, len(features), "measures", "المقاييس")
        complete = [r for r in rows if all(isinstance(r.get(c), (int, float)) for c in features)]
        if len(complete) < MIN_ROWS:
            return _thin(ctx, role, title, MIN_ROWS, len(complete), "records", "السجلات")
        sample = _even(complete, CLUSTER_CAP)
        raw = [[float(r[c]) for c in features] for r in sample]
        scale = _scaler(raw)
        points = [scale(v) for v in raw]
        centre = [statistics.fmean(p[i] for p in points) for i in range(len(features))]
        whole = sum(_distance(p, centre) for p in points)
        probe = _even(list(range(len(points))), SILHOUETTE_CAP)
        trials = []
        for k in range(2, 6):
            assignment, centres, spread = kmeans(points, k)
            score = silhouette([points[i] for i in probe], [assignment[i] for i in probe])
            trials.append((score, k, assignment, centres, spread))
        score, k, assignment, centres, spread = max(trials, key=lambda t: (t[0], -t[1]))
        explained = 1 - spread / whole if whole else 0.0
        found = score >= SEPARATED
        profiles = []
        for group in range(k):
            members = [r for r, a in zip(sample, assignment) if a == group]
            if not members:
                continue
            marks = sorted(zip(features, centres[group]), key=lambda fc: -abs(fc[1]))[:2]
            profiles.append({
                "group": group + 1, "share": round(len(members) / len(sample), 4),
                "average_measure": round(statistics.fmean(
                    m[measure] for m in members) if measure in features else 0.0, 4),
                "stands_out": [{"input": f, "direction": "higher" if v > 0 else "lower"}
                               for f, v in marks]})
        calcs = [
            _calc(role, "c_records", "records_grouped", len(sample),
                  f"records with every measure filled, at most {CLUSTER_CAP} evenly spaced"),
            _calc(role, "c_groups", "groups", k,
                  "k-means for 2 to 5 groups on standardised measures, keeping the best separated"),
            _calc(role, "c_separation", "separation", round(score, 4),
                  f"average silhouette (−1 to 1) on {len(probe)} evenly spaced records"),
            _calc(role, "c_explained", "share_of_spread_explained", round(explained, 4),
                  "1 − spread within groups / spread around one overall average (the baseline: "
                  "one group explains nothing)"),
            _calc(role, "c_improvement", "improvement_over_baseline", round(explained, 4),
                  "share of spread explained over the one-group baseline"),
        ]
        claims = [_claim(
            ctx, role, "cl_fit", "calculation",
            f"The best split of {len(sample)} records is into {k} groups, which explain "
            f"{explained:.0%} of the spread that one group leaves, with a separation of "
            f"{score:.2f} on a scale from 0 to 1.",
            f"أفضل تقسيم لـ {len(sample)} من السجلات هو إلى {k} مجموعات، تفسر "
            f"{explained:.0%} من التباعد الذي تتركه مجموعة واحدة، بفصل قدره {score:.2f} على "
            "مقياس من 0 إلى 1.",
            ["c_groups", "c_separation", "c_explained", "c_records"])]
        if not found:
            claims.append(_claim(
                ctx, role, "cl_weak", "limitation",
                f"The groups overlap (separation {score:.2f}, below the 0.25 needed), so "
                "the records do not fall into natural groups and the groups should not be "
                "treated as segments.",
                f"المجموعات متداخلة (فصل {score:.2f}، أقل من 0.25 المطلوب)، فالسجلات لا "
                "تنقسم إلى مجموعات طبيعية ولا ينبغي معاملة المجموعات كشرائح.",
                ["c_separation"]))
        headline = _say(
            ctx,
            (f"The records fall into {k} groups that explain {explained:.0%} of the spread."
             if found else
             f"The records do not fall into clear groups (separation {score:.2f})."),
            (f"تنقسم السجلات إلى {k} مجموعات تفسر {explained:.0%} من التباعد."
             if found else
             f"لا تنقسم السجلات إلى مجموعات واضحة (الفصل {score:.2f})."))
        lines = [_say(ctx, "| Group | Share of records | Stands out by |",
                      "| المجموعة | حصة السجلات | تتميز بـ |"), "| --- | --- | --- |"]
        for profile in profiles:
            marks = ", ".join(
                f"{m['input']} {_say(ctx, m['direction'], 'أعلى' if m['direction'] == 'higher' else 'أدنى')}"
                for m in profile["stands_out"])
            lines.append(f"| {profile['group']} | {profile['share']:.0%} | {marks} |")
        return {
            "status": "succeeded", "summary": headline, "claims": claims,
            "calculations": calcs,
            "quality_checks": [{"name": "groups_are_separated", "passed": found,
                                "detail": _say(ctx, f"Separation {score:.2f} (0.25 needed).",
                                               f"الفصل {score:.2f} (المطلوب 0.25).")}],
            "output": {
                "headline": headline, "fitted": True,
                "question": _say(ctx, self.question, "هل تنقسم السجلات إلى مجموعات طبيعية؟"),
                "report_markdown": _section(ctx, title, headline, calcs, lines),
                "model_card": _card(
                    "clustering", ", ".join(features), features, len(sample), len(probe),
                    {"kind": "none"}, "separation", round(score, 4), SEPARATED,
                    "separation_needed", round(explained, 4), found,
                    {"groups": k, "share_of_spread_explained": round(explained, 4),
                     "profiles": profiles}),
            },
        }


class SeasonalForecast:
    role = "seasonal_model"
    title = "Seasonal Forecast Agent — does the measure follow a season?"
    title_ar = "وكيل التوقع الموسمي: هل يتبع المقياس موسماً؟"
    after = "sensitivity"
    question = "Does the measure follow a season, and what comes next?"
    can_fail_run = False

    def run(self, ctx):
        role = self.role
        prep = ctx["preparer"]
        measure = prep["measure"]
        title = _say(ctx, "Does the measure follow a season?", "هل يتبع المقياس موسماً؟")
        labels = list(prep.get("trend") or {})
        series = [prep["trend"][label] for label in labels]
        grain = prep.get("date_grain") or _grain_of(labels)
        season = SEASONS.get(grain)
        if not season:
            return _thin(ctx, role, title, 3, 0, "seasons", "المواسم")
        needed = 3 * season
        if len(series) < needed:
            return _thin(ctx, role, title, needed, len(series), "periods", "الفترات")
        history, held = series[:-season], series[-season:]
        forecast = seasonal_forecast(history, season, season)
        model_error = statistics.fmean(abs(a - f) for a, f in zip(held, forecast))
        naive = statistics.fmean(abs(a - history[-1]) for a in held)
        last_season = statistics.fmean(abs(a - b) for a, b in zip(held, history[-season:]))
        # A trend with no season is a baseline too: a season is only found
        # when it adds to what the trend alone already forecasts.
        slope, intercept, _ = analytics._linear_fit(history)
        straight = statistics.fmean(abs(a - (intercept + slope * (len(history) + i)))
                                    for i, a in enumerate(held))
        base_error, base_name = min((naive, "last_period"), (last_season, "last_season"),
                                    (straight, "trend_only"))
        improvement = _improvement(model_error, base_error, lower_is_better=True)
        beats = improvement >= BEATS
        ahead = seasonal_forecast(series, season, season)
        ahead_labels = analytics._next_labels(labels, season)
        _, _, pattern = seasonal_fit(series, season)
        peak = max(range(season), key=lambda i: pattern[i])
        calcs = [
            _calc(role, "c_periods", "periods", len(series), f"periods at {grain} grain"),
            _calc(role, "c_model_error", "model_average_error", round(model_error, 4),
                  f"mean of |actual − forecast| total {measure} over the last {season} "
                  "periods, fitted on the periods before them"),
            _calc(role, "c_base_error", "baseline_average_error", round(base_error, 4),
                  "the best of repeating the last period, repeating the season before, and "
                  f"the straight trend alone (here: {base_name})"),
            _calc(role, "c_improvement", "improvement_over_baseline", round(improvement, 4),
                  "(baseline error − model error) / baseline error"),
        ]
        claims = [_claim(
            ctx, role, "cl_fit", "calculation",
            f"Forecasting the last {season} periods from the ones before, the seasonal model "
            f"is off by {model_error:,.2f} a period on average, against {base_error:,.2f} "
            f"for the better simple guess: {improvement:.0%} better.",
            f"عند توقع آخر {season} فترات من الفترات السابقة لها، يخطئ النموذج الموسمي "
            f"بمقدار {model_error:,.2f} في الفترة في المتوسط، مقابل {base_error:,.2f} لأفضل "
            f"تخمين بسيط: أفضل بنسبة {improvement:.0%}.",
            ["c_model_error", "c_base_error", "c_improvement"])]
        if beats:
            claims.append(_claim(
                ctx, role, "cl_forecast", "forecast",
                f"If the pattern holds, the next {season} periods total "
                f"{sum(ahead):,.2f} of {measure}; the strongest point in the season is "
                f"position {peak + 1}. This assumes the business keeps operating as it has.",
                f"إذا استمر النمط، فمجموع {measure} في الفترات {season} التالية "
                f"{sum(ahead):,.2f}، وأقوى نقطة في الموسم هي الموضع {peak + 1}. ويفترض هذا "
                "استمرار النشاط على ما كان عليه.",
                ["c_model_error", "c_improvement"]))
        else:
            claims.append(_weak(ctx, role, "seasonal model", "النموذج الموسمي", improvement))
        headline = _say(
            ctx,
            (f"{measure} follows a {season}-period season; the model beats simple guesses "
             f"by {improvement:.0%}." if beats else
             f"No season improves on simple guesses for {measure} ({improvement:.0%} "
             "better)."),
            (f"يتبع {measure} موسماً من {season} فترات، ويتفوق النموذج على التخمينات "
             f"البسيطة بنسبة {improvement:.0%}." if beats else
             f"لا يتحسن أي موسم على التخمينات البسيطة لـ {measure} (أفضل بنسبة "
             f"{improvement:.0%})."))
        lines = [_say(ctx, "| Period | Forecast |", "| الفترة | التوقع |"), "| --- | --- |"]
        lines += [f"| {label} | {value:,.2f} |" for label, value in zip(ahead_labels, ahead)]
        return {
            "status": "succeeded", "summary": headline, "claims": claims,
            "calculations": calcs,
            "quality_checks": [{"name": "seasonal_model_beats_its_baseline", "passed": beats,
                                "detail": _say(ctx, f"{improvement:.1%} better than {base_name}.",
                                               f"أفضل من خط الأساس بنسبة {improvement:.1%}.")}],
            "output": {
                "headline": headline, "fitted": True,
                "question": _say(ctx, self.question, "هل يتبع المقياس موسماً، وماذا بعد؟"),
                "report_markdown": _section(ctx, title, headline, calcs, lines),
                "model_card": _card(
                    "seasonal", measure, [f"{grain} season of {season}"], len(history),
                    season, {"kind": "last_season"}, "average_error", round(model_error, 4),
                    round(base_error, 4), base_name, round(improvement, 4), beats,
                    {"season": season, "grain": grain,
                     "forecast": [{"label": l, "value": round(v, 2)}
                                  for l, v in zip(ahead_labels, ahead)]}),
            },
        }


def _too_many_classes(ctx, role, title, target, count):
    calcs = [_calc(role, "c_available", "classes_available", count,
                   f"distinct values of {target}")]
    text_en = (f"{target} has {count} classes; this model separates at most {MAX_CLASSES}, "
               "so it was not fitted.")
    text_ar = (f"في {target} عدد {count} من الفئات، ويفصل هذا النموذج {MAX_CLASSES} فئات على "
               "الأكثر، فلم يُبنَ.")
    summary = _say(ctx, text_en, text_ar)
    return {"status": "succeeded", "summary": summary,
            "claims": [_claim(ctx, role, "cl_thin", "limitation", text_en, text_ar,
                              ["c_available"])],
            "calculations": calcs, "quality_checks": [],
            "output": {"headline": summary, "fitted": False,
                       "report_markdown": _section(ctx, title, summary, calcs)}}


def _grain_of(labels):
    """The grain of unmapped period labels, read from their shape."""
    sample = [str(label) for label in labels[:5]]
    if sample and all(len(s) == 7 and s[4] == "-" and s[5:].isdigit() for s in sample):
        return "month"
    if sample and all(len(s) == 7 and s[4:6] == "-Q" for s in sample):
        return "quarter"
    if sample and all(len(s) == 10 and s[4] == "-" and s[7] == "-" for s in sample):
        return "day"
    return None
