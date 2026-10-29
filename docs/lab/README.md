# Lab handouts

| handout | file | content |
|---|---|---|
| 0 | [`00_installation.pdf`](00_installation.pdf) | installation of Python 3.14, of the lab code and of the required packages on macOS and Windows |
| 1 | [`01_tool_overview.pdf`](01_tool_overview.pdf) | description of the graphical interface, one annotated screenshot per page |
| 2 | [`02_networkx_backend.pdf`](02_networkx_backend.pdf) | representation of networks as NetworkX graphs, with the script `labs/lab1_networkx_tour.py` |
| 3 | [`03_first_ilp.pdf`](03_first_ilp.pdf) | the splittable flow formulation on Spain-7: effect of the capacity, fibre cuts |

The folder `screenshots/` contains the screenshots of the handouts with the numbered labels,
and `screenshots/raw/` the same screenshots without them. The folder `figures/` contains the
figures of the handouts, drawn with TikZ from the data of the scripts in `labs/`
(`tools/lab_docs/tikz_figures.py`); their LaTeX sources and PDF versions, which can be reused
in slides, are in `figures/tikz/`.

## Building the handouts

The sources are the Markdown files in `src/` and, in the repository of the instructors, in
`solutions/lab_docs/`. After a change of the interface or of the data, everything is rebuilt
with

```bash
pip install markdown pymdown-extensions playwright pillow
python -m playwright install chromium          # and a TeX installation with PGFPlots (pdflatex)
python tools/make_student_version.py --release labs1-2 --out ../lab-shots   # copy for the screenshots
python tools/lab_docs/build.py all --project ../lab-shots --python ../lab-shots/.venv/bin/python
```

after creating the environment `.venv` of `../lab-shots` as described in handout 0. When only
the text has changed, `python tools/lab_docs/build.py pdf` is sufficient. On Linux without a
display the screenshots are taken inside `xvfb-run`. The address of the student repository
quoted in handout 0 is set with `--var repo_url=https://github.com/<owner>/<repo>`.

The values quoted in the handouts are checked by `tests/test_labs.py`. Console outputs and
figures are inserted from the scripts by the directives `{{output ...}}` and `{{figure ...}}`
of the sources, described in `tools/lab_docs/build.py`.
