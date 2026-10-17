#!/usr/bin/env python3
"""Check every figure in a deliverable against the register it came from.

    python scripts/figures_check.py --register kpis.csv --value-column Expected \\
        --doc report.pdf --doc deck.pptx [--reference report.pdf] [--json out.json]

Tier 0 of docs/AGENT_TEAM.md: no model, no tokens. Three checks:

1. Coverage: every value in the register appears in the documents, written
   exactly or in a recognised shorter form ($50,430,446 as $50.4 million or
   $50.4M; 219.0 as 219; 26,501 as 26.5k).
2. Sourcing, with --reference: every number in a --doc appears in the
   register or in a reference document, in a compatible unit (a percentage
   is not sourced by a dollar amount). Bare small counts (up to 31) and
   years are ignored, because they are labels far more often than figures;
   "12%" and "$12" are figures. A figure run into a word ("Reactive7988.1",
   from glued table cells) counts. A figure that follows from the sourced
   figures its sentence names (610 staff across 48 stores, 12.7 each) is
   derived; one presented as following from them that does not is wrong.
3. Arithmetic: a calculation written out ("24.4 h − 16.9 h = 7.5 h") must
   hold. A result that holds is a derived figure, sourced by its inputs.

Figures written in words ("one in five") are not read: the figures-auditor
reads the text for those.

Reads .md, .txt, .html, .json, .csv and .tsv (cell by cell), .pdf (with pdftotext) and .pptx (slide
text, alt text and speaker notes). Exits 0 when everything is found, 1
otherwise. Standard library only.
"""

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import zipfile
from html import unescape
from pathlib import Path

NUMBER = re.compile(r"(?<![\w.])[-+−]?\$?\d[\d,]*(?:\.\d+)?%?(?:\s?(?:thousand|million|billion|bn|[MBk]))?(?![\w])")
# A figure run into the word before it, as text extraction does to table
# cells ("Reactive7988.1 y"). Only forms that cannot be part of a name count:
# a decimal or a thousands separator, so "rev37" and "sha256" are left alone,
# and a version such as "v1.0" is not a figure.
GLUED = re.compile(r"(?<=[^\W\d_])(?<!\b[vV])\$?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+)%?(?![\w])")
# A worked calculation written out: "24.4 h − 16.9 h = 7.5 h per record ×
# 862 records × about $2,500 per hour ≈ $16M". Up to three words of unit
# or label may sit between a figure and the next sign.
CALC_TOKEN = re.compile(rf"(?P<num>{NUMBER.pattern})|(?P<rel>[=≈])|(?P<op>[×÷*/+]|(?<=\s)[-x](?=\s))"
                        r"|(?P<word>[^\W\d_][\w'’-]*)|(?P<space>\s+)|(?P<other>.)")


def read_text(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        if not shutil.which("pdftotext"):
            raise RuntimeError("pdftotext is needed to read PDF (install poppler-utils).")
        done = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True)
        if done.returncode:
            raise RuntimeError(f"pdftotext could not read {path.name}: {done.stderr.strip()}")
        text = done.stdout
    elif suffix == ".pptx":
        parts = []
        with zipfile.ZipFile(path) as archive:
            names = sorted(n for n in archive.namelist()
                           if re.match(r"ppt/(slides|notesSlides)/\w+\d+\.xml$", n))
            for name in names:
                xml = archive.read(name).decode("utf-8", "replace")
                parts += re.findall(r"<a:t>([^<]*)</a:t>", xml)
                parts += re.findall(r'\bdescr="([^"]*)"', xml)
        text = "\n".join(unescape(p) for p in parts)
    elif suffix in (".html", ".htm"):
        raw = path.read_text(encoding="utf-8", errors="replace")
        # Chart drawings are skipped: axis ticks are not figures, and a
        # chart's values are checked in the table that carries them.
        raw = re.sub(r"(?is)<(script|style|svg)[^>]*>.*?</\1>", " ", raw)
        text = unescape(re.sub(r"<[^>]+>", " ", raw))
    elif suffix in (".csv", ".tsv"):
        # Cell by cell: the commas between cells would otherwise run
        # neighbouring numbers together ("862,61014.76").
        with open(path, encoding="utf-8-sig", newline="") as handle:
            rows = csv.reader(handle, delimiter="\t" if suffix == ".tsv" else ",")
            text = "\n".join(" ; ".join(cell for cell in row) for row in rows)
    elif suffix == ".json":
        def strings(node):
            if isinstance(node, str):
                yield node
            elif isinstance(node, (int, float)) and not isinstance(node, bool):
                yield str(node)
            elif isinstance(node, dict):
                for value in node.values():
                    yield from strings(value)
            elif isinstance(node, list):
                for value in node:
                    yield from strings(value)
        text = "\n".join(strings(json.loads(path.read_text(encoding="utf-8"))))
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return normalise(text)


# Arabic-Indic and Persian digits, and the Arabic separators, read as figures (ADR 0027).
ARABIC_FIGURES = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٬٫٪", "01234567890123456789,.%")
# An amount in brackets is a negative, as accounts write it: "(1,200)" is -1,200.
ACCOUNTING_NEGATIVE = re.compile(r"\((\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$\d+(?:\.\d+)?)\)")
# A figure the text calls approximate may be rounded further than its digits show.
APPROXIMATE = re.compile(r"(?:\b(?:about|around|roughly|approximately|nearly|almost|some|close to)|~|≈|"
                         r"حوالي|حوالى|نحو|قرابة)\s*(\$?\d[\d,]*(?:\.\d+)?%?(?:\s?(?:thousand|million|billion|bn|[MBk]))?)(?![\w])",
                         re.I)


def normalise(text):
    """One line of text with plain spaces, minus signs and Western digits, as the checks read it."""
    # Time stamps such as "[10.0–15.5 s]" in a clip transcript are not figures.
    text = re.sub(r"\[\d+(?:\.\d+)?\s?[–-]\s?\d+(?:\.\d+)?\s?s\]", " ", text)
    text = text.translate(ARABIC_FIGURES)
    text = ACCOUNTING_NEGATIVE.sub(r"-\1", text)
    return " ".join(text.replace("\u00a0", " ").replace("−", "-").split())


def rounding_unit(token):
    """How far a written figure can be from the value it rounds: half of its
    last significant place. 6,400 is within 50 of its value; 26.5k within 50."""
    parsed = parse(token)
    if parsed is None:
        return 0.0
    number, decimals, scale = parsed
    if decimals:
        unit = 10 ** -decimals
    else:
        digits = str(int(abs(number)))
        unit = 10 ** (len(digits) - len(digits.rstrip("0"))) if digits.strip("0") else 1
    return unit * (scale or 1) / 2


SCALES = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9, "b": 1e9}


def parse(token):
    """(number as written, decimals shown, scale or None) for a figure such
    as '$50.4 million', '26.5k', '14.1%' or '1,200'. None if not a number."""
    token = token.strip().rstrip(",.")
    match = re.fullmatch(r"[-+−]?\$?(\d[\d,]*(?:\.(\d+))?)%?\s?(thousand|million|billion|bn|[MBkmb])?", token)
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    if token.lstrip().startswith(("-", "−")):
        number = -number
    decimals = len(match.group(2) or "")
    scale = SCALES.get((match.group(3) or "").lower()) if match.group(3) else None
    return number, decimals, scale


def same_figure(written, value):
    """True when `written` is `value` as a report may show it: exact,
    rounded to fewer decimals, or abbreviated in thousands or millions."""
    shown = parse(written)
    if shown is None:
        return False
    number, decimals, scale = shown
    # A scale applies only when the text says so ("26.5k", "$50.4 million"):
    # without one, "0" would match anything in thousands. A percentage may
    # be stored as a fraction: 45% is 0.45.
    candidates = [value / (scale or 1)]
    if written.strip().endswith("%"):
        candidates.append(value * 100)
    return any(abs(round(c, decimals) - number) < 1e-9 for c in candidates)


def value_of(text):
    parsed = parse(text)
    if parsed is None:
        return None
    number, _, scale = parsed
    return number * (scale or 1)


def variants(value):
    """Exact forms of a register value, tried before numeric matching."""
    v = str(value).strip()
    out = {v}
    parsed = parse(v)
    if parsed and float(parsed[0]).is_integer() and parsed[1]:
        whole = f"{int(parsed[0]):,}"
        out.add(("$" + whole) if v.startswith("$") else whole + ("%" if v.endswith("%") else ""))
    return out


def found_in(text, value, numbers=None):
    """How a register value appears in a text: an exact form, or a written
    figure that is the same number rounded or abbreviated."""
    for form in variants(value):
        if re.search(r"(?<![\d.,])" + re.escape(form) + r"(?![\d])", text):
            return form
    target = value_of(value)
    if target is None:
        return None
    percent = str(value).strip().endswith("%")
    for token in (numbers if numbers is not None else numbers_in(text, keep_small=True)):
        if percent != token.endswith("%"):
            continue
        if same_figure(token, target):
            return f"{token} (rounded or abbreviated)"
    return None


def _evaluate(terms, ops):
    """terms[0] ops[0] terms[1] …, with × and ÷ before + and −."""
    values, pending = [terms[0]], []
    for op, term in zip(ops, terms[1:]):
        if op in "×x*":
            values[-1] *= term
        elif op in "÷/":
            values[-1] = values[-1] / term if term else float("nan")
        else:
            pending.append(op)
            values.append(term)
    total = values[0]
    for op, value in zip(pending, values[1:]):
        total = total + value if op == "+" else total - value
    return total


def calculations_in(text):
    """Worked calculations in a text: [{"shown", "result", "written", "holds"}].

    "=" holds when the result is the computed value as written, rounded to the
    decimals shown (or within 0.5%, for inputs that were rounded themselves);
    "≈" holds within 5%. A result that holds is a derived figure: sourced by
    its inputs, which are checked like any other number.
    """
    found, terms, ops, words, start = [], [], [], 0, None

    def reset():
        nonlocal terms, ops, words, start
        terms, ops, words, start = [], [], 0, None

    tokens = list(CALC_TOKEN.finditer(text))
    i = 0
    while i < len(tokens):
        kind, token = tokens[i].lastgroup, tokens[i]
        if kind == "num":
            value = value_of(token.group(0))
            if value is None or (terms and len(ops) < len(terms)):
                reset()
                if value is not None:
                    terms, start = [value], token.start()
            else:
                terms.append(value)
                start = token.start() if start is None else start
            words = 0
        elif kind == "op" and terms and len(ops) == len(terms) - 1:
            ops.append(token.group(0))
            words = 0
        elif kind == "rel" and len(terms) >= 2 and len(ops) == len(terms) - 1:
            nxt = next((t for t in tokens[i + 1:] if t.lastgroup != "space"), None)
            if nxt is not None and nxt.lastgroup == "num" and value_of(nxt.group(0)) is not None:
                computed = _evaluate(terms, ops)
                written = nxt.group(0).strip().rstrip(",.")
                shown = value_of(written)
                tolerance = 0.05 if token.group(0) == "≈" else 0.005
                holds = (same_figure(written, computed)
                         or (computed and abs(shown - computed) <= tolerance * abs(computed)))
                found.append({"shown": text[start:nxt.end()], "result": written,
                              "computed": round(computed, 6), "holds": bool(holds)})
                # The result may start the next step: "… = 7.5 h × 862 …".
                terms, ops, words, start = [shown], [], 0, nxt.start()
                i = tokens.index(nxt) + 1
                continue
            reset()
        elif kind == "word" and terms:
            words += 1
            if words > 3:
                reset()
        elif kind != "space":
            reset()
        i += 1
    return found


def numbers_in(text, keep_small=False):
    """Figures in a text, leaving out small counts and years."""
    seen = set()
    matches = list(NUMBER.finditer(text))
    glued = list(GLUED.finditer(text))
    # A glued figure replaces any shorter number found inside it.
    matches = [m for m in matches if not any(g.start() <= m.start() < g.end() for g in glued)] + glued
    for match in matches:
        token = match.group(0).strip().rstrip(",.")
        parsed = parse(token)
        if parsed is None:
            continue
        # Only a bare number can be a label: "12%" and "$12" are figures (ADR 0027).
        if not keep_small and re.fullmatch(r"\d{1,2}", token) and parsed[0] <= 31:
            continue
        if not keep_small and re.fullmatch(r"(19|20)\d{2}", token):
            continue
        seen.add(token)
    return sorted(seen)


def unit_of(token):
    """'%', '$' or '' (a bare number, which may stand for either)."""
    token = token.strip().lstrip("+-−")
    return "%" if token.endswith("%") else "$" if token.startswith("$") else ""


def sourced_by(token, pool):
    """True when a pool entry (value, unit) is this figure, in a compatible unit."""
    unit = unit_of(token)
    return any(same_figure(token, value) for value, other in pool if not (unit and other and unit != other))


# Words that present a figure as computed from others, by the kind of sum.
CUES = {
    "ratio": re.compile(r"\b(each|per|every|average|averages|mean|apiece)\b|لكل|متوسط", re.I),
    "change": re.compile(r"\b(growth|grew|grow|grows|rise|rose|risen|up|down|fell|fall|gain|drop|dropped|change|"
                         r"increase[sd]?|decrease[sd]?)\b|نمو|ارتفع|انخفض|زيادة", re.I),
    "share": re.compile(r"\b(share|of all|proportion|percent of)\b|نسبة|حصة", re.I),
}
# "That is growth of 13.4%": the figures are in the sentence before.
BACK_REFERENCE = re.compile(r"^(that|this|it|these|those|which)\b|^(هذا|هذه|وهذا|وهذه)", re.I)
SENTENCES = re.compile(r"(?<=[.!?؟])\s+")
# A figure this close to a derivation of its sentence's own inputs is a slip
# in that derivation, not an unrelated number (chosen on benchmark A, ADR 0027).
SLIP_FACTOR = 2.0
MAX_SENTENCE, MAX_FIGURES = 300, 6


def _derivations(a, b):
    return {"ratio": [x for x in (a / b if b else None, b / a if a else None) if x is not None],
            "change": [x for x in (a / b - 1 if b else None, b / a - 1 if a else None, a - b, b - a) if x is not None],
            "share": [x for x in (a / b if b else None, b / a if a else None) if x is not None],
            "other": [a * b, a + b]}


def _as_written(token, value):
    """A computed value in the token's terms: a fraction read as a percentage."""
    return value * 100 if unit_of(token) == "%" and abs(value) < 1.5 else value


def _close(token, value):
    """Within the token's own rounding: with no working shown, there is no
    rounded input to allow for."""
    written, unit = value_of(token), rounding_unit(token)
    return any(abs(written - c) <= unit + 1e-9 for c in {value, _as_written(token, value)})


def _distinct(values):
    """One input per quantity: 75.2% and 0.752 are the same figure written twice."""
    out = []
    for v in values:
        if v is not None and not any(abs(v - o) < 1e-9 or abs(v - o * 100) < 1e-6 or abs(v * 100 - o) < 1e-6
                                     for o in out):
            out.append(v)
    return out


def _words(text):
    return {w.rstrip("s") for w in re.findall(r"[^\W\d_]{4,}", text.lower())}


def implied(token, sentence, previous, pool, register):
    """For a figure not in the pool: "derived" when it follows from the
    sourced figures its sentence names (or the register rows it names by
    every word of their label); ("wrong", computed) when the sentence
    presents it as computed from two or more of its figures and it is a
    slip from one of their derivations; None otherwise."""
    # Prose only: a table read as one long "sentence" holds dozens of figures,
    # and any two of them would derive something.
    if len(sentence) > MAX_SENTENCE or len(numbers_in(sentence)) > MAX_FIGURES:
        return None
    body = re.sub(r"^(?:\[\w+\]|[^\w])+", "", sentence)
    explicit = [value_of(t) for t in numbers_in(sentence) if t != token and sourced_by(t, pool)]
    if len(explicit) < 2 and previous and BACK_REFERENCE.match(body):
        explicit += [value_of(t) for t in numbers_in(previous) if sourced_by(t, pool)]
    words = _words(sentence)
    named = [value_of(r["value"]) for r in register
             if _words(re.sub(r"\(.*?\)", " ", r["label"])) and _words(re.sub(r"\(.*?\)", " ", r["label"])) <= words]
    inputs = _distinct(explicit + named)
    pairs = [(a, b) for i, a in enumerate(inputs) for b in inputs[i + 1:]]
    if any(_close(token, c) for a, b in pairs for cs in _derivations(a, b).values() for c in cs):
        return "derived"
    explicit = _distinct(explicit)
    families = [name for name, cue in CUES.items() if cue.search(sentence)]
    if len(explicit) < 2 or not families:
        return None
    written = value_of(token)
    candidates = [_as_written(token, c) for i, a in enumerate(explicit) for b in explicit[i + 1:]
                  for f in families for c in _derivations(a, b)[f]]
    candidates = [c for c in candidates if c and (c > 0) == (written > 0)]
    if not candidates or not written:
        return None
    best = min(candidates, key=lambda c: max(written / c, c / written))
    return ("wrong", best) if max(written / best, best / written) <= SLIP_FACTOR else None


def load_register(path, value_column, label_columns):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or value_column not in rows[0]:
        raise ValueError(f"{path} has no column “{value_column}”.")
    labels = [c for c in label_columns if c in rows[0]] or [c for c in rows[0] if c != value_column][:2]
    return [{"label": " · ".join(r[c] for c in labels if r.get(c)), "value": r[value_column]} for r in rows]


def check(register, docs, references=(), sourcing_only=False):
    texts = {str(d): read_text(d) for d in docs}
    combined = " ".join(texts.values())
    written = numbers_in(combined, keep_small=True)
    coverage = []
    for row in register:
        form = found_in(combined, row["value"], written)
        coverage.append({**row, "found": form is not None, "as": form})
    unsourced, derived, wrong = [], [], []
    for name, text in texts.items():
        for calc in calculations_in(text):
            (derived if calc["holds"] else wrong).append({"doc": Path(name).name, **calc})
    if references or sourcing_only:
        pool_text = " ".join(read_text(r) for r in references)
        pool = {(value_of(t), unit_of(t)) for t in numbers_in(pool_text, keep_small=True)}
        pool |= {(value_of(r["value"]), unit_of(r["value"])) for r in register}
        pool = {(v, u) for v, u in pool if v is not None}
        for name, text in texts.items():
            doc = Path(name).name
            # A result whose working is shown is sourced by its inputs.
            known = pool | {(value_of(d["result"]), unit_of(d["result"])) for d in derived if d["doc"] == doc}
            approximate = {m.group(1).strip().rstrip(",.") for m in APPROXIMATE.finditer(text)}
            sentences = SENTENCES.split(text)
            for token in numbers_in(text):
                if sourced_by(token, known):
                    continue
                if token in approximate:
                    written, unit = value_of(token), rounding_unit(token)
                    if any(abs(written - v) <= unit + 1e-9 for v, _ in pool):
                        continue
                where = next((i for i, s in enumerate(sentences) if token in numbers_in(s)), None)
                verdict = (implied(token, sentences[where], sentences[where - 1] if where else "", pool, register)
                           if where is not None else None)
                if verdict == "derived":
                    continue
                if verdict:
                    wrong.append({"doc": doc, "shown": sentences[where][:160], "result": token,
                                  "computed": round(verdict[1], 6), "holds": False, "implied": True})
                    continue
                unsourced.append({"doc": doc, "number": token})
    missing = [c for c in coverage if not c["found"]]
    return {"register_values": len(register), "found": len(register) - len(missing),
            "missing": [] if sourcing_only else missing, "unsourced": unsourced, "coverage": coverage,
            "derived": derived, "wrong_arithmetic": wrong,
            "passed": (sourcing_only or not missing) and not unsourced and not wrong}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--register", required=True, help="CSV of figures the deliverable must carry")
    parser.add_argument("--value-column", default="Expected")
    parser.add_argument("--label-columns", default="Check,Filter")
    parser.add_argument("--doc", action="append", required=True, help="a document to check (repeatable)")
    parser.add_argument("--reference", action="append", default=[],
                        help="a document whose numbers count as sourced (repeatable)")
    parser.add_argument("--sourcing-only", action="store_true",
                        help="check only that every number in the documents is sourced; a dashboard or "
                             "a deck shows a chosen subset, so missing register values are not failures")
    parser.add_argument("--json", help="also write the full result here")
    args = parser.parse_args(argv)
    try:
        register = load_register(args.register, args.value_column, args.label_columns.split(","))
        result = check(register, args.doc, args.reference, args.sourcing_only)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"figures_check: {error}", file=sys.stderr)
        return 2
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{result['found']}/{result['register_values']} register values found")
    for item in result["missing"]:
        print(f"  MISSING  {item['label']}: {item['value']}")
    if args.reference or args.sourcing_only:
        print(f"{len(result['unsourced'])} number(s) in the documents not found in the register or references")
        for item in result["unsourced"][:50]:
            print(f"  UNSOURCED  {item['doc']}: {item['number']}")
    if result["derived"] or result["wrong_arithmetic"]:
        print(f"{len(result['derived'])} worked calculation(s) hold, {len(result['wrong_arithmetic'])} do not")
        for item in result["wrong_arithmetic"][:20]:
            print(f"  ARITHMETIC  {item['doc']}: “{item['shown']}” computes to {item['computed']:,}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
