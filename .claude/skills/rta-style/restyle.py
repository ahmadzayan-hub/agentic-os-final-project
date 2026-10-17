#!/usr/bin/env python3
"""Restyle HTML written in the project's default palette into the print
variant of the house style, without touching a word of it.

    python .claude/skills/rta-style/restyle.py --in slides/ --out themed/      # every .html file
    python .claude/skills/rta-style/restyle.py --in cover.html --out cover.themed.html

Built for slides and pages whose colours and fonts are inline styles. Each
colour is mapped by its role (a background, a text colour or a border, from
`from_default` in tokens.json), then every text colour is checked against
the background it actually sits on, inherited from its ancestors: if the
mapped colour falls below 4.5:1, white or the body text colour is used,
whichever reads. Serif and sans families become the one document family,
as the Dubai Design System asks (hierarchy from size and weight). Standard
library only.
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAG = re.compile(r"<(/?)([a-zA-Z][\w-]*)((?:\"[^\"]*\"|'[^']*'|[^'\">])*)>")
STYLE = re.compile(r"""style=(["'])(.*?)\1""", re.S)
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
HEADINGS = {"h1", "h2", "h3"}


def luminance(colour):
    r, g, b = (int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class Restyler:
    def __init__(self, tokens=None):
        tokens = tokens or json.loads((HERE / "tokens.json").read_text(encoding="utf-8"))
        self.doc = tokens["document"]
        self.font = tokens["document_font"]
        self.maps = {kind: {k.lower(): self.doc[v] for k, v in table.items()}
                     for kind, table in tokens["from_default"].items()}

    def text_on(self, colour, background, heading=False):
        """The mapped text colour, or the first that reads on this background."""
        if heading and colour == self.doc["text"] and contrast(self.doc["primary"], background) >= 4.5:
            colour = self.doc["primary"]          # headings in the brand blue, where it reads
        for candidate in (colour, self.doc["on-primary"], self.doc["text"]):
            if contrast(candidate, background) >= 4.5:
                return candidate
        return colour

    def declarations(self, style, tag, background):
        """(new style, background for the children)."""
        out = []
        pending_colour = None
        for part in [p for p in style.split(";") if p.strip()]:
            prop, _, value = part.partition(":")
            name = prop.strip().lower()
            value = value.strip()
            if name in ("background", "background-color"):
                value = HEX.sub(lambda m: self.maps["background"].get(m.group(0).lower(), m.group(0)), value)
                found = HEX.search(value)
                background = found.group(0).lower() if found else background
            elif name == "color":
                pending_colour = len(out)
                value = HEX.sub(lambda m: self.maps["color"].get(m.group(0).lower(), m.group(0)), value)
            elif name.startswith("border"):
                value = HEX.sub(lambda m: self.maps["border"].get(m.group(0).lower(), m.group(0)), value)
            elif name == "font-family":
                value = self.font
            elif name == "font":
                value = re.sub(r"'[^']+'(\s*,\s*[\w\s-]+)*$", self.font, value)
            out.append([prop.strip(), value])
        if pending_colour is not None:
            colour = HEX.search(out[pending_colour][1])
            if colour:
                out[pending_colour][1] = self.text_on(colour.group(0).lower(), background, tag in HEADINGS)
        return ";".join(f"{p}:{v}" for p, v in out), background

    def restyle(self, html, background=None):
        background = background or self.doc["page"]
        stack, out, pos = [("", background)], [], 0
        for match in TAG.finditer(html):
            out.append(html[pos:match.start()])
            pos = match.end()
            closing, tag, attrs = match.group(1), match.group(2).lower(), match.group(3)
            if closing:
                for depth in range(len(stack) - 1, 0, -1):
                    if stack[depth][0] == tag:
                        del stack[depth:]
                        break
                out.append(match.group(0))
                continue
            here = stack[-1][1]
            found = STYLE.search(attrs)
            if found:
                new, here = self.declarations(found.group(2), tag, here)
                attrs = attrs[:found.start()] + f'style="{new}"' + attrs[found.end():]
            out.append(f"<{match.group(2)}{attrs}>")
            if tag not in VOID and not attrs.rstrip().endswith("/"):
                stack.append((tag, here))
        out.append(html[pos:])
        return "".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--in", dest="source", required=True, help="an .html file or a folder of them")
    parser.add_argument("--out", required=True, help="a file, or a folder for a folder")
    args = parser.parse_args(argv)
    source, target = Path(args.source), Path(args.out)
    restyler = Restyler()
    files = sorted(source.glob("*.html")) if source.is_dir() else [source]
    if not files:
        print(f"restyle: no .html files in {source}", file=sys.stderr)
        return 2
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
    for file in files:
        dest = target / file.name if source.is_dir() else target
        dest.write_text(restyler.restyle(file.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"restyled {len(files)} file(s) into {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
