"""Compile a WriterReport to a styled PDF via xelatex.

Pipeline:
    WriterReport.model_dump()
        → Python string builder → report.tex
        → xelatex (×2 for TOC / cross-refs)
        → final_report.pdf

Fonts: Linux Libertine O (body) + Linux Biolinum O (headings).
Requires: xelatex from TeX Live (system package), jinja2 not needed.

Public API
----------
report_to_pdf(report_data, output_path, diagram_path=None, depth="standard")
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from datetime import date
from typing import Optional

# ─── LaTeX text escaping ──────────────────────────────────────────────────── #

_ESCAPE_MAP = str.maketrans({
    "\\": r"\textbackslash{}",
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\textasciicircum{}",
})

_BOLD_RE   = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC_RE = re.compile(r"\*(.+?)\*",   re.DOTALL)
_CITE_RE   = re.compile(r"\[(\d+)\]")
_URL_RE    = re.compile(r"https?://\S+")


def _esc(text: str) -> str:
    """Escape LaTeX special characters and convert simple inline markdown."""
    if not text:
        return ""
    # Protect URLs before escaping (they contain _ ~ etc.)
    urls: list[str] = []
    def stash_url(m: re.Match) -> str:
        urls.append(m.group(0))
        return f"\x00URL{len(urls)-1}\x00"
    text = _URL_RE.sub(stash_url, text)

    text = text.translate(_ESCAPE_MAP)
    text = _BOLD_RE.sub(r"\\textbf{\1}", text)
    text = _ITALIC_RE.sub(r"\\textit{\1}", text)
    text = _CITE_RE.sub(r"\\textsuperscript{[\1]}", text)

    # Restore URLs wrapped in \url{}
    for i, url in enumerate(urls):
        text = text.replace(f"\x00URL{i}\x00", f"\\url{{{url}}}")
    return text


def _esc_para(text: str) -> str:
    """Escape text preserving blank-line paragraph breaks as LaTeX \\par."""
    if not text:
        return ""
    paragraphs = re.split(r"\n\s*\n", text)
    return "\n\n".join(_esc(p.strip()) for p in paragraphs if p.strip())


# ─── Markdown table → LaTeX tabularx ─────────────────────────────────────── #

def _parse_md_table(md_table: str) -> Optional[str]:
    """Convert a GFM markdown table to a LaTeX tabularx. Returns None on failure."""
    lines = [l.strip() for l in md_table.strip().splitlines() if l.strip()]
    data_lines = [l for l in lines if not re.match(r"^[\|\s\-:]+$", l)]
    if len(data_lines) < 2:
        return None

    def split_row(line: str) -> list[str]:
        return [c.strip() for c in line.strip("|").split("|")]

    header = split_row(data_lines[0])
    rows   = [split_row(l) for l in data_lines[1:]]
    n = len(header)
    col_spec = "|".join(["X"] * n)

    parts = [
        r"\begin{center}",
        r"\renewcommand{\arraystretch}{1.25}",
        rf"\begin{{tabularx}}{{\textwidth}}{{|{col_spec}|}}",
        r"\hline",
        r"\rowcolor{reportblue}",
    ]
    # Header: each cell gets white color independently
    header_cells = " & ".join(
        r"{{\color{{white}}\textbf{{{}}}}}".format(_esc(h)) for h in header
    )
    parts.append(header_cells + r" \\")
    parts.append(r"\hline")

    for i, row in enumerate(rows):
        padded = row + [""] * (n - len(row))
        cells = " & ".join(_esc(c) for c in padded[:n])
        if i % 2 == 1:
            parts.append(r"\rowcolor{rowalt}")
        parts.append(cells + r" \\")
        parts.append(r"\hline")

    parts += [r"\end{tabularx}", r"\end{center}"]
    return "\n".join(parts)


# ─── LaTeX preamble ───────────────────────────────────────────────────────── #

_PREAMBLE = r"""
\documentclass[11pt, a4paper]{article}

\usepackage{geometry}
\usepackage{fontspec}
\usepackage{microtype}
\usepackage[dvipsnames,table]{xcolor}
\usepackage{tcolorbox}
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage[hidelinks,colorlinks=true,linkcolor=reportblue,urlcolor=reportblue]{hyperref}
\usepackage{graphicx}
\usepackage{titlesec}
\usepackage{parskip}
\usepackage{array}
\usepackage{multicol}

\tcbuselibrary{skins, breakable}

%% Page geometry
\geometry{a4paper, top=2.8cm, bottom=2.8cm, left=2.5cm, right=2.5cm, headheight=14pt}

%% Fonts
\setmainfont{Linux Libertine O}
\setsansfont{Linux Biolinum O}
\setmonofont{DejaVu Sans Mono}[Scale=0.88]

%% Colors
\definecolor{reportblue}{RGB}{15, 52, 96}
\definecolor{lightblue}{RGB}{232, 244, 253}
\definecolor{accentblue}{RGB}{180, 210, 235}
\definecolor{claimgray}{RGB}{245, 247, 250}
\definecolor{rowalt}{RGB}{240, 244, 248}

%% Section headings
\titleformat{\section}
  {\sffamily\Large\bfseries\color{reportblue}}{\thesection}{0.8em}{}
  [\vspace{-4pt}{\color{accentblue}\rule{\linewidth}{1.2pt}}\vspace{2pt}]
\titleformat{\subsection}
  {\sffamily\large\bfseries\color{reportblue!80}}{\thesubsection}{0.8em}{}
\titleformat{\subsubsection}
  {\sffamily\normalsize\bfseries\color{reportblue!70}}{}{0em}{}
\titlespacing{\section}{0pt}{18pt}{6pt}
\titlespacing{\subsection}{0pt}{12pt}{4pt}

%% Headers / footers
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\sffamily\small\color{gray} Deep Research Report}
\fancyhead[R]{\sffamily\small\color{gray} \leftmark}
\fancyfoot[C]{\sffamily\small\color{gray} \thepage}
\renewcommand{\headrulewidth}{0.4pt}
\renewcommand{\footrulewidth}{0pt}

%% Executive summary box
\newtcolorbox{execbox}{
  enhanced, breakable,
  colback=lightblue, colframe=reportblue,
  boxrule=1.2pt, arc=3pt,
  title={\sffamily\bfseries\large Executive Summary},
  coltitle=white,
  attach boxed title to top left={yshift=-2mm, xshift=6mm},
  boxed title style={colback=reportblue, arc=2pt, boxrule=0pt},
  left=8pt, right=8pt, top=10pt, bottom=8pt,
}

%% Claim evidence box
\newtcolorbox{claimbox}{
  enhanced, breakable,
  colback=claimgray, colframe=accentblue,
  boxrule=0pt, leftrule=2.5pt, arc=0pt,
  left=8pt, right=6pt, top=6pt, bottom=6pt,
  before skip=4pt, after skip=4pt,
}

%% Lists
\setlist[itemize]{leftmargin=1.4em, topsep=3pt, itemsep=1pt}
\setlist[enumerate]{leftmargin=1.6em, topsep=3pt, itemsep=2pt}
\setlength{\parskip}{5pt}
\setlength{\parindent}{0pt}
\renewcommand{\arraystretch}{1.2}
"""


# ─── Document section builders ────────────────────────────────────────────── #

def _title_page(question: str, task_mode: str, depth: str, today: str) -> str:
    q = _esc(question)
    return (
        r"\begin{titlepage}" + "\n"
        r"  \vspace*{3cm}" + "\n"
        r"  \begin{center}" + "\n"
        r"    {\color{reportblue}\rule{\linewidth}{2pt}}\\[1.2em]" + "\n"
        r"    {\sffamily\Huge\bfseries\color{reportblue} Research Report}\\[0.8em]" + "\n"
        r"    {\color{reportblue}\rule{\linewidth}{0.6pt}}\\[1.8em]" + "\n"
        f"    {{\\sffamily\\large\\color{{reportblue!80}} {q}}}\\\\[2em]\n"
        r"    \vfill" + "\n"
        f"    {{\\sffamily\\small\\color{{gray}}\n"
        f"      Task mode: \\textbf{{{task_mode}}} \\quad|\\quad\n"
        f"      Depth: \\textbf{{{depth}}} \\quad|\\quad\n"
        f"      Generated: \\textbf{{{today}}}}}\n"
        r"  \end{center}" + "\n"
        r"\end{titlepage}"
    )


def _exec_summary(text: str, comparison_targets: list[str]) -> str:
    parts = [
        r"\section*{Executive Summary}",
        r"\addcontentsline{toc}{section}{Executive Summary}",
        r"\begin{execbox}",
        _esc_para(text),
        r"\end{execbox}",
    ]
    if comparison_targets:
        ncols = min(len(comparison_targets), 3)
        parts += [
            r"\subsubsection*{Compared Targets}",
            rf"\begin{{multicols}}{{{ncols}}}",
            r"\begin{itemize}",
        ]
        for t in comparison_targets:
            parts.append(rf"  \item \textbf{{{_esc(t)}}}")
        parts += [r"\end{itemize}", r"\end{multicols}"]
    return "\n".join(parts)


def _comparison_table_section(table_latex: str) -> str:
    return "\n".join([
        r"\section*{Comparison Table}",
        r"\addcontentsline{toc}{section}{Comparison Table}",
        table_latex,
    ])


def _diagram_section(diagram_path: str) -> str:
    return "\n".join([
        r"\section*{Architecture Diagram}",
        r"\addcontentsline{toc}{section}{Architecture Diagram}",
        r"\begin{figure}[htbp]",
        r"  \centering",
        rf"  \includegraphics[width=0.95\textwidth]{{{diagram_path}}}",
        r"  \caption{System Architecture}",
        r"\end{figure}",
    ])


def _claims_table(claims: list[dict]) -> str:
    parts = [
        r"\renewcommand{\arraystretch}{1.3}",
        r"\begin{center}",
        r"\begin{tabularx}{\textwidth}{|c|p{2cm}|p{3cm}|X|}",
        r"\hline",
        r"\rowcolor{reportblue}",
        r"{\color{white}\textbf{\#}} & {\color{white}\textbf{Confidence}} & "
        r"{\color{white}\textbf{Source Agreement}} & {\color{white}\textbf{Claim}} \\",
        r"\hline",
    ]
    for i, claim in enumerate(claims, 1):
        if i % 2 == 0:
            parts.append(r"\rowcolor{rowalt}")
        row = (
            f"{i} & {_esc(claim.get('confidence',''))} & "
            f"{_esc(claim.get('source_agreement',''))} & "
            f"{_esc(claim.get('claim',''))} \\\\"
        )
        parts.append(row)
        parts.append(r"\hline")
    parts += [r"\end{tabularx}", r"\end{center}"]
    return "\n".join(parts)


def _claim_evidence_box(i: int, claim: dict) -> str:
    parts = [
        r"\begin{claimbox}",
        rf"\textbf{{Claim {i}:}} {_esc(claim.get('claim',''))}\\[3pt]",
        rf"\textit{{Confidence:}} {_esc(claim.get('confidence',''))} \quad "
        rf"\textit{{Source Agreement:}} {_esc(claim.get('source_agreement',''))}",
    ]
    evidence = claim.get("evidence", [])
    if evidence:
        parts.append(r"\begin{itemize}[topsep=2pt,itemsep=1pt]")
        for ev in evidence:
            parts.append(rf"  \item {_esc(ev)}")
        parts.append(r"\end{itemize}")
    parts.append(r"\end{claimbox}")
    return "\n".join(parts)


def _section_block(section: dict) -> str:
    parts = [
        rf"\section{{{_esc(section.get('title',''))}}}",
        "",
        _esc_para(section.get("narrative", "")),
    ]

    stats = section.get("key_statistics", [])
    if stats:
        parts += [
            "",
            r"\subsubsection*{Key Statistics}",
            r"\begin{itemize}",
        ]
        for stat in stats:
            parts.append(rf"  \item {_esc(stat)}")
        parts.append(r"\end{itemize}")

    claims = section.get("claims", [])
    if claims:
        parts += ["", r"\subsubsection*{Claims}", "", _claims_table(claims), ""]
        for i, claim in enumerate(claims, 1):
            parts.append(_claim_evidence_box(i, claim))

    return "\n".join(parts)


def _recommendations(items: list[str]) -> str:
    parts = [r"\section{Recommendations}", r"\begin{enumerate}"]
    for item in items:
        parts.append(rf"  \item {_esc(item)}")
    parts.append(r"\end{enumerate}")
    return "\n".join(parts)


def _methodology(notes: str, confidence: str) -> str:
    return "\n".join([
        r"\section{Methodology \& Confidence}",
        "",
        r"\subsection*{Methodology}",
        _esc_para(notes),
        "",
        r"\subsection*{Confidence Assessment}",
        _esc_para(confidence),
    ])


def _open_questions(items: list[str]) -> str:
    if not items:
        return ""
    parts = [r"\section{Open Questions}", r"\begin{itemize}"]
    for q in items:
        parts.append(rf"  \item {_esc(q)}")
    parts.append(r"\end{itemize}")
    return "\n".join(parts)


def _sources_section(sources: list[str]) -> str:
    parts = [r"\section{Sources}", r"\begin{enumerate}[leftmargin=2em]"]
    for src in sources:
        parts.append(rf"  \item \small {_esc(src)}")
    parts.append(r"\end{enumerate}")
    return "\n".join(parts)


# ─── Full document assembly ───────────────────────────────────────────────── #

def _build_tex(
    report_data: dict,
    diagram_path: Optional[str],
    depth: str,
) -> str:
    today = date.today().strftime("%B %d, %Y")
    blocks: list[str] = [_PREAMBLE, r"\begin{document}", ""]

    blocks.append(_title_page(
        report_data.get("question", ""),
        report_data.get("task_mode", "standard"),
        depth, today,
    ))
    blocks.append("")

    # TOC
    blocks += [
        r"\tableofcontents",
        r"\thispagestyle{empty}",
        r"\newpage",
        r"\setcounter{page}{1}",
        "",
    ]

    # Executive summary + comparison targets
    blocks.append(_exec_summary(
        report_data.get("executive_summary", ""),
        report_data.get("comparison_targets", []),
    ))
    blocks.append("")

    # Comparison table (if any)
    md_table = report_data.get("comparison_table_markdown") or ""
    if md_table.strip():
        table_latex = _parse_md_table(md_table)
        if table_latex:
            blocks.append(_comparison_table_section(table_latex))
            blocks.append("")

    # Architecture diagram (if any)
    if diagram_path and os.path.exists(diagram_path):
        blocks.append(_diagram_section(diagram_path))
        blocks.append("")

    # Thematic sections
    for section in report_data.get("sections", []):
        blocks.append(_section_block(section))
        blocks.append("")

    # Recommendations
    recs = report_data.get("recommendations", [])
    if recs:
        blocks.append(_recommendations(recs))
        blocks.append("")

    # Methodology & confidence
    blocks.append(_methodology(
        report_data.get("methodology_notes", ""),
        report_data.get("confidence_summary", ""),
    ))
    blocks.append("")

    # Open questions
    oq = _open_questions(report_data.get("open_questions", []))
    if oq:
        blocks.append(oq)
        blocks.append("")

    # Sources
    sources = report_data.get("sources", [])
    if sources:
        blocks.append(_sources_section(sources))
        blocks.append("")

    blocks.append(r"\end{document}")
    return "\n".join(blocks)


# ─── Public API ──────────────────────────────────────────────────────────── #

def report_to_pdf(
    report_data: dict,
    output_path: str,
    diagram_path: Optional[str] = None,
    depth: str = "standard",
) -> None:
    """Compile *report_data* (WriterReport.model_dump()) to a PDF at *output_path*.

    Also writes <output_path>.tex beside the PDF for inspection / debugging.
    Raises RuntimeError if xelatex is missing or compilation produces no PDF.
    """
    xelatex = shutil.which("xelatex")
    if not xelatex:
        raise RuntimeError("xelatex not found — install texlive-xetex")

    if diagram_path:
        diagram_path = os.path.abspath(diagram_path)

    tex_source = _build_tex(report_data, diagram_path, depth)

    # Save .tex alongside the PDF for inspection
    tex_debug_path = output_path.replace(".pdf", ".tex")
    with open(tex_debug_path, "w", encoding="utf-8") as fh:
        fh.write(tex_source)

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = os.path.join(tmpdir, "report.tex")
        with open(tex_path, "w", encoding="utf-8") as fh:
            fh.write(tex_source)

        # If diagram_path is absolute xelatex can find it; make it absolute if not.
        cmd = [
            xelatex,
            "-interaction=nonstopmode",
            "-output-directory", tmpdir,
            tex_path,
        ]
        for _ in range(2):
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=tmpdir)

        compiled_pdf = os.path.join(tmpdir, "report.pdf")
        if not os.path.exists(compiled_pdf):
            log_tail = (proc.stdout or proc.stderr or "")[-4000:]
            raise RuntimeError(
                f"xelatex produced no PDF.\n\nLog tail:\n{log_tail}"
            )

        shutil.copy2(compiled_pdf, output_path)
