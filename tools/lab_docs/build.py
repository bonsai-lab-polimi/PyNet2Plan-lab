#!/usr/bin/env python3
"""
Build the lab handouts (docs/lab/*.pdf)
=======================================

    python tools/lab_docs/build.py all            # screenshots + figures + PDFs + check
    python tools/lab_docs/build.py pdf            # only the PDFs (after editing docs/lab/src/*.md)

Steps
  screenshots  drive the GUI and photograph it  -> docs/lab/screenshots/
  figures      run the lab scripts, keep their console output, and draw the
               figures of the handouts with TikZ from the same data
               (tools/lab_docs/tikz_figures.py, compiled with pdflatex)
                                                 -> docs/lab/figures/, docs/lab/build/outputs/
  pdf          docs/lab/src/*.md -> HTML -> PDF (headless Chromium)
  check        optional: --forbid WORD  stops if WORD appears in a PDF, a
               screenshot or a figure (text and OCR)

The screenshots and the figures are taken in the project given by --project
(default: this one) with its Python (--python), e.g. a fresh student copy made
with tools/make_student_version.py, so that the pictures show what the
students see. On Linux without a screen the GUI runs inside xvfb-run.

The material of Lab 2 needs a completed unsplittable flow formulation: while
it is produced, formulations/unsplittable_flow.py of that project is replaced
by the exercise completed with the code of solutions/unsplittable_flow.py
(see complete_exercise), and restored afterwards.

Needs:  pip install markdown pymdown-extensions playwright pillow
        python -m playwright install chromium
        a TeX installation with TikZ and PGFPlots (pdflatex), and pdftocairo (poppler)
(OCR check: the tesseract program, optional).

Markdown extensions understood in docs/lab/src/*.md (one per line):
  {{var NAME}}                      a value of VARIABLES below (or --var NAME=value)
  {{fact NAME}}                     a value seen while taking the screenshots
  {{output NAME [SECTION]}}         console output of a lab script (or one of its numbered sections)
  {{cell FILE N}}                   the code of cell "# %% N." of a script
  {{excerpt FILE | START | END [| AFTER]}}  the lines of FILE from the one containing START (the first
                                    one after the line containing AFTER) to the one containing END
  {{figure PATH | CAPTION | CLASS}} a picture with its caption
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import html
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DOCS = os.path.join(REPO, "docs", "lab")
SRC = os.path.join(DOCS, "src")
SHOTS = os.path.join(DOCS, "screenshots")
FIGS = os.path.join(DOCS, "figures")
BUILD = os.path.join(DOCS, "build")
OUTPUTS = os.path.join(BUILD, "outputs")
#: Markdown sources: the student handouts and (instructors' repository only) the lab plans
SOURCE_DIRS = [SRC, os.path.join(REPO, "solutions", "lab_docs")]

VARIABLES = {
    "repo_url": "https://github.com/bonsai-lab-polimi/PyNet2Plan-lab",
    "repo_name": "PyNet2Plan-lab",
    "python_version": "3.14",
    "course": "Communication Network Design, Laboratory",
    "date": _dt.date.today().strftime("%B %Y"),
}

#: the figures of the handouts (TikZ), kept as SVG in docs/lab/figures/ and as .tex/.pdf in figures/tikz/
TIKZ = os.path.join(FIGS, "tikz")
#: screenshots of the handouts of Lab 2 (a sub-folder of docs/lab/screenshots)
SHOTS_LAB2 = os.path.join(SHOTS, "lab2")


# ----------------------------------------------------------------------
# running things in the project that is photographed
# ----------------------------------------------------------------------
def gui_prefix():
    """xvfb-run on Linux when there is no screen."""
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        return ["xvfb-run", "-a", "-s", "-screen 0 1700x1200x24"]
    return []


def run(cmd, cwd, capture=False, timeout=1800, ok_codes=(0,)):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", MPLBACKEND=os.environ.get("MPLBACKEND", ""))
    if not env["MPLBACKEND"]:
        env.pop("MPLBACKEND")
    env.pop("PYTHONPATH", None)
    print("  $", " ".join(cmd[-4:]) if len(cmd) > 4 else " ".join(cmd))
    p = subprocess.run(cmd, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                       capture_output=capture, timeout=timeout)
    if p.returncode not in ok_codes:
        if capture:
            print(p.stdout[-4000:], p.stderr[-4000:])
        raise SystemExit(f"command failed ({p.returncode}): {' '.join(cmd)}")
    return p.stdout if capture else ""


def complete_exercise(exercise: str, solution: str) -> str:
    """The text of an exercise file with every ``raise NotCompletedError("TODO n: ...")``
    line replaced by the code of block "TODO n" of the reference solution, i.e. the
    file as a student who completed it would have it (hint comments included)."""
    header = re.compile(r"^\s*# ---- TODO (\d+):")
    any_header = re.compile(r"^\s*# ----")
    blocks, current = {}, None
    for line in solution.splitlines():
        m = header.match(line)
        if m:
            current = m.group(1)
            blocks[current] = []
        elif any_header.match(line):
            current = None
        elif current and line.strip() and not line.strip().startswith("#"):
            blocks[current].append(line)
    out, seen_code = [], set()
    for line in exercise.splitlines():
        m = header.match(line)
        if m:
            seen_code = set()
        todo = re.search(r'raise NotCompletedError\("TODO (\d+):', line)
        if todo:
            code = [c for c in blocks.get(todo.group(1), []) if c.strip() not in seen_code]
            if not code:
                raise SystemExit(f"complete_exercise: no code for TODO {todo.group(1)} in the solution")
            out.extend(code)
            continue
        if line.strip() and not line.strip().startswith("#"):
            seen_code.add(line.strip())
        out.append(line)
    return "\n".join(out) + "\n"


#: the exercises of Lab 2, completed while its material is produced
LAB2_EXERCISES = ("unsplittable_flow", "route_formulation_vwp")


@contextlib.contextmanager
def exercise_completed(project, names=LAB2_EXERCISES):
    """formulations/<name>.py of ``project`` completed for the duration of the block."""
    originals = {}
    try:
        for name in names:
            target = os.path.join(project, "formulations", f"{name}.py")
            originals[target] = read(target)
            completed = complete_exercise(originals[target], read(os.path.join(REPO, "solutions", f"{name}.py")))
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(completed)
        yield
    finally:
        for target, original in originals.items():
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original)


def step_screenshots(args):
    print("== screenshots")
    script = os.path.join(args.project, "tools", "lab_docs", "screenshots.py")
    if not os.path.isfile(script):
        raise SystemExit(f"{script} not found: is --project a copy of this project?")
    for scenes, out in (("lab1", SHOTS), ("lab2", SHOTS_LAB2)):
        cmd = gui_prefix() + [args.python, script, "--scenes", scenes, "--out", out, "--size", args.size,
                              "--text-scale", str(args.text_scale)]
        for w in args.forbid:
            cmd += ["--forbid", w]
        if scenes == "lab1":
            run(cmd, args.project)
        else:
            with exercise_completed(args.project):
                run(cmd, args.project)


def step_figures(args):
    print("== figures and console outputs")
    os.makedirs(FIGS, exist_ok=True)
    os.makedirs(OUTPUTS, exist_ok=True)
    py, proj = args.python, args.project
    exercise = os.path.join("formulations", "unsplittable_flow.py")
    route = os.path.join("formulations", "route_formulation_vwp.py")
    outs = {
        "doctor": run([args.doctor_python or py, "-m", "pynet2plan", "doctor"], proj, capture=True),
        "tour": run([py, os.path.join("labs", "lab1_networkx_tour.py")], proj, capture=True),
        "first_ilp": run([py, os.path.join("labs", "lab1_first_ilp.py")], proj, capture=True),
        "check_todo": run([py, "-m", "pynet2plan", "check", exercise], proj, capture=True, ok_codes=(0, 1)),
        "check_todo_route": run([py, "-m", "pynet2plan", "check", route], proj, capture=True, ok_codes=(0, 1)),
    }
    with exercise_completed(proj):                     # Lab 2: as after completing the exercises
        outs["check_done"] = run([py, "-m", "pynet2plan", "check", exercise], proj, capture=True)
        outs["check_done_route"] = run([py, "-m", "pynet2plan", "check", route], proj, capture=True)
        outs["lab2"] = run([py, os.path.join("labs", "lab2_unsplittable.py")], proj, capture=True)
        outs["lab2r"] = run([py, os.path.join("labs", "lab2_route_formulation.py")], proj, capture=True)
    for key in ("check_done", "check_done_route"):
        outs[key] = re.sub(r"time [0-9.]+ s", "time 0.05 s", outs[key])   # stable text
    for name, text in outs.items():
        text = text.replace(os.path.abspath(proj), "…")         # no absolute paths in the handouts
        with open(os.path.join(OUTPUTS, f"{name}.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
    tikz_figures(args)


def tikz_figures(args):
    """The figures of the handouts: TikZ files written by tools/lab_docs/tikz_figures.py in the
    project (from data/ and the JSON files of the lab scripts), compiled with pdflatex and
    converted to SVG."""
    tmp = os.path.join(BUILD, "tikz")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    run([args.python, os.path.join("tools", "lab_docs", "tikz_figures.py"), "--out", tmp], args.project)
    for old in os.listdir(FIGS):                       # figures of earlier versions (PNG)
        if old.endswith(".png"):
            os.remove(os.path.join(FIGS, old))
    os.makedirs(TIKZ, exist_ok=True)
    env = dict(os.environ, SOURCE_DATE_EPOCH="1767225600", FORCE_SOURCE_DATE="1")   # same bytes every time
    names = sorted(f[:-4] for f in os.listdir(tmp) if f.endswith(".tex"))
    for name in names:
        p = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{name}.tex"], cwd=tmp,
                           capture_output=True, text=True, errors="replace", env=env)
        if p.returncode != 0:
            raise SystemExit(f"pdflatex failed on {name}.tex:\n" + p.stdout[-2500:])
        subprocess.run(["pdftocairo", "-svg", f"{name}.pdf", f"{name}.svg"], cwd=tmp, check=True)
        shutil.copy2(os.path.join(tmp, f"{name}.svg"), os.path.join(FIGS, f"{name}.svg"))
        for ext in (".tex", ".pdf"):
            shutil.copy2(os.path.join(tmp, name + ext), os.path.join(TIKZ, name + ext))
    print(f"  {len(names)} TikZ figures in {os.path.relpath(FIGS, REPO)}")


# ----------------------------------------------------------------------
# Markdown -> HTML
# ----------------------------------------------------------------------
def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def code_block(text, lang=""):
    text = text.rstrip("\n")
    fence = "````" if "```" in text else "```"
    return f"{fence}{lang}\n{text}\n{fence}"


def output_section(text, section):
    """Lines of the numbered section 'N. title' (followed by a line of dashes or '=')."""
    lines = text.splitlines()
    starts = [i for i in range(len(lines) - 1)
              if re.match(r"^\d+\. ", lines[i]) and re.match(r"^[-=]{3,}$", lines[i + 1])]
    for k, i in enumerate(starts):
        if lines[i].split(".")[0] == str(section):
            end = starts[k + 1] if k + 1 < len(starts) else len(lines)
            return "\n".join(lines[i + 2:end]).strip("\n")
    raise SystemExit(f"output section {section} not found")


def cell(path, n):
    lines = read(os.path.join(REPO, path)).splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("# %%")]
    for k, i in enumerate(starts):
        if re.match(rf"^# %% {n}\.", lines[i]):
            end = starts[k + 1] if k + 1 < len(starts) else len(lines)
            return "\n".join(lines[i + 1:end]).strip("\n")
    raise SystemExit(f"cell {n} not found in {path}")


def excerpt(path, start, end, after=""):
    lines = read(os.path.join(REPO, path)).splitlines()
    first = next((k for k, ln in enumerate(lines) if after in ln), 0) if after else 0
    i = next((k for k, ln in enumerate(lines) if k >= first and start in ln), None)
    if i is None:
        raise SystemExit(f"excerpt: '{start}' not found in {path}")
    j = next((k for k in range(i, len(lines)) if end in lines[k]), None)
    if j is None:
        raise SystemExit(f"excerpt: '{end}' not found in {path}")
    block = lines[i:j + 1]
    indent = min((len(ln) - len(ln.lstrip()) for ln in block if ln.strip()), default=0)
    return "\n".join(ln[indent:] for ln in block)


#: printed size of one screenshot pixel: a 1400-pixel window fills a landscape A4 page, and the
#: GUI text (15 px with View > Text size > Large) is printed at about 8 pt
MM_PER_PX = 0.192


def figure(path, caption="", options=""):
    """<figure>; options: 'shot' (screenshot scale), 'crop=x0,y0,x1,y1', 'width=60%', other words = CSS classes."""
    from PIL import Image
    src = os.path.normpath(os.path.join(SRC, path) if not os.path.isabs(path) else path)
    if not os.path.isfile(src):
        raise SystemExit(f"figure not found: {path}")
    classes, style = [], ""
    for opt in options.split():
        if opt.startswith("crop="):
            box = tuple(int(v) for v in opt[5:].split(","))
            os.makedirs(os.path.join(BUILD, "img"), exist_ok=True)
            name = os.path.splitext(os.path.basename(src))[0] + "_" + "_".join(map(str, box)) + ".png"
            dst = os.path.join(BUILD, "img", name)
            Image.open(src).crop(box).save(dst)
            src = dst
        elif opt.startswith("width="):
            style = f"width:{opt[6:]}"
        else:
            classes.append(opt)
    if src.endswith(".svg") and not style:                 # TikZ figures: printed at their own size
        m = re.search(r'<svg[^>]*\swidth="([0-9.]+)(pt|px)?"', read(src))
        if m:
            style = f"width:{float(m.group(1)) * 25.4 / 72:.1f}mm"
    elif "shot" in classes and not style:
        px = Image.open(src).size[0]
        style = f"width:{min(px * MM_PER_PX, 269):.1f}mm"
    uri = "file://" + src
    if caption:
        import markdown
        caption = markdown.markdown(caption).strip()
        caption = re.sub(r"^<p>|</p>$", "", caption)
    cap = f"<figcaption>{caption}</figcaption>" if caption else ""
    return (f'<figure class="{html.escape(" ".join(classes))}"><img src="{uri}" alt="" '
            f'style="{style}">{cap}</figure>')


def expand(text, facts, variables, base=SRC):
    outputs = {}

    def get_output(name):
        if name not in outputs:
            outputs[name] = read(os.path.join(OUTPUTS, f"{name}.txt"))
        return outputs[name]

    def repl(m):
        kind, rest = m.group(1), m.group(2).strip()
        if kind == "var":
            return str(variables[rest])
        if kind == "fact":
            if rest not in facts:
                raise SystemExit(f"fact '{rest}' unknown: run the screenshots step")
            return str(facts[rest])
        if kind == "output":
            parts = rest.split()
            text_ = get_output(parts[0])
            return code_block(output_section(text_, parts[1]) if len(parts) > 1 else text_.strip("\n"),
                              "text")
        if kind == "cell":
            path, n = rest.rsplit(" ", 1)
            return code_block(cell(path, n), "python")
        if kind == "excerpt":
            parts = [p.strip() for p in rest.split("|")]
            return code_block(excerpt(*parts), "python")
        if kind == "figure":
            parts = [p.strip() for p in rest.split("|")] + ["", ""]
            return figure(os.path.join(base, parts[0]), parts[1], parts[2])
        raise SystemExit(f"unknown directive {kind}")
    text = re.sub(r"\{\{(var|fact)\s+([^{}\n]*?)\}\}", repl, text)      # first the values (also in captions)
    return re.sub(r"\{\{(output|cell|excerpt|figure)\s+(.*?)\}\}(?!\})", repl, text)


def front_matter(text):
    meta = {}
    if text.startswith("---\n"):
        head, text = text[4:].split("\n---\n", 1)
        for line in head.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta, text


def to_html(md_text, meta, css):
    import markdown
    body = markdown.markdown(md_text, extensions=["tables", "pymdownx.superfences", "pymdownx.highlight",
                                                  "attr_list", "md_in_html", "sane_lists", "toc",
                                                  "def_list"],
                             extension_configs={"toc": {"permalink": False},
                                                "pymdownx.highlight": {"use_pygments": False}})
    title = html.escape(meta.get("title", "Lab handout"))
    sub = html.escape(meta.get("subtitle", ""))
    tag = html.escape(meta.get("tag", ""))
    cover = (f'<header class="cover"><div class="course">{html.escape(VARIABLES["course"])}</div>'
             f'<h1 class="doc-title">{title}</h1>'
             + (f'<div class="subtitle">{sub}</div>' if sub else "")
             + f'<div class="date">{html.escape(VARIABLES["date"])}</div>'
             + (f'<div class="tag">{tag}</div>' if tag else "") + "</header>")
    orient = meta.get("orientation", "portrait")
    page = f"@page {{ size: A4 {orient}; }}"
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{title}</title>"
            f"<style>{css}\n{page}</style></head><body class='{orient}'>{cover}{body}</body></html>")


def step_pdf(args):
    print("== PDFs")
    from playwright.sync_api import sync_playwright
    css = read(os.path.join(SRC, "style.css"))
    facts = {}
    for folder in (SHOTS, SHOTS_LAB2):
        sj = os.path.join(folder, "screenshots.json")
        if os.path.isfile(sj):
            facts.update(json.loads(read(sj)).get("facts", {}))
    variables = dict(VARIABLES)
    for kv in args.var:
        k, v = kv.split("=", 1)
        variables[k] = v
    os.makedirs(os.path.join(BUILD, "html"), exist_ok=True)
    docs = [os.path.join(d, f) for d in SOURCE_DIRS if os.path.isdir(d) for f in sorted(os.listdir(d))
            if f.endswith(".md") and f != "README.md" and (not args.only or f.startswith(tuple(args.only)))]
    made = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium) if args.chromium else pw.chromium.launch()
        for path in docs:
            f = os.path.basename(path)
            meta, text = front_matter(read(path))
            page_html = to_html(expand(text, facts, variables, os.path.dirname(path)), meta, css)
            hp = os.path.join(BUILD, "html", f[:-3] + ".html")
            with open(hp, "w", encoding="utf-8") as fh:
                fh.write(page_html)
            out = os.path.join(REPO, meta.get("output", os.path.join("docs", "lab", f[:-3] + ".pdf")))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            page = browser.new_page()
            page.goto("file://" + hp)
            page.wait_for_load_state("networkidle")
            landscape = meta.get("orientation") == "landscape"
            foot = html.escape(meta.get("footer", meta.get("title", "")))
            page.pdf(path=out, format="A4", landscape=landscape, print_background=True,
                     prefer_css_page_size=True,
                     display_header_footer=True,
                     header_template="<div></div>",
                     footer_template=(
                         "<div style='font-family: \"Latin Modern Roman\", \"Times New Roman\", serif; "
                         "font-size:8pt; color:#333; width:100%; padding:0 14mm; display:flex; "
                         "justify-content:space-between'>"
                         f"<span>{foot}</span>"
                         "<span><span class='pageNumber'></span></span></div>"),
                     margin=dict(top="13mm", bottom="15mm", left="14mm", right="14mm"))
            page.close()
            made.append(out)
            print(f"  {os.path.relpath(out, REPO)}")
        browser.close()
    return made


# ----------------------------------------------------------------------
def step_check(args):
    if not args.forbid:
        return
    print("== check: " + ", ".join(args.forbid))
    words = [w.lower() for w in args.forbid]
    bad = []
    for root, _dirs, files in os.walk(DOCS):
        if os.path.relpath(root, DOCS).startswith("build"):
            continue
        for f in files:
            p = os.path.join(root, f)
            text = ""
            if f.endswith(".pdf") and shutil.which("pdftotext"):
                text = subprocess.run(["pdftotext", p, "-"], capture_output=True, text=True).stdout
            elif f.endswith(".png") and shutil.which("tesseract"):
                text = subprocess.run(["tesseract", p, "-", "--psm", "11"], capture_output=True,
                                      text=True).stdout
            elif f.endswith((".md", ".json", ".txt", ".css", ".tex", ".svg")):
                text = read(p)
            if any(w in text.lower() for w in words):
                bad.append(os.path.relpath(p, REPO))
    plans = os.path.join(REPO, "solutions")
    for f in (os.listdir(plans) if os.path.isdir(plans) else []):
        if f.endswith(".pdf") and shutil.which("pdftotext"):
            text = subprocess.run(["pdftotext", os.path.join(plans, f), "-"], capture_output=True, text=True).stdout
            if any(w in text.lower() for w in words):
                bad.append(os.path.relpath(os.path.join(plans, f), REPO))
    for root, _dirs, files in os.walk(OUTPUTS):
        for f in files:
            if any(w in read(os.path.join(root, f)).lower() for w in words):
                bad.append(os.path.relpath(os.path.join(root, f), REPO))
    if bad:
        raise SystemExit("forbidden word found in:\n  " + "\n  ".join(bad))
    print("  ok")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("steps", nargs="*", default=["all"],
                    help="all | screenshots | figures | pdf | check (default: all)")
    ap.add_argument("--project", default=REPO, help="project to photograph (default: this one)")
    ap.add_argument("--python", default=sys.executable, help="Python of that project")
    ap.add_argument("--doctor-python", default=None, help="Python used for the 'doctor' output")
    ap.add_argument("--size", default="1360x720", help="window size of the screenshots")
    ap.add_argument("--text-scale", type=float, default=1.25, help="text size of the screenshots")
    ap.add_argument("--forbid", action="append", default=[], help="word that must not appear (repeatable)")
    ap.add_argument("--var", action="append", default=[], help="override a variable: NAME=value")
    ap.add_argument("--only", action="append", default=[], help="build only the sources starting with this")
    ap.add_argument("--chromium", default=os.environ.get("LAB_DOCS_CHROMIUM"),
                    help="path of a Chromium executable (default: the one of playwright)")
    args = ap.parse_args(argv)
    args.project = os.path.abspath(args.project)
    steps = args.steps
    if "all" in steps:
        steps = ["screenshots", "figures", "pdf", "check"]
    for s in steps:
        {"screenshots": step_screenshots, "figures": step_figures, "pdf": step_pdf,
         "check": step_check}[s](args)


if __name__ == "__main__":
    main()
