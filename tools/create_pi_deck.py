#!/usr/bin/env python3
"""Build the RCP Platform PI review deck from repository evidence.

The deck intentionally reads benchmark artifacts at generation time so that
reported values, hashes, and quality-gate counts cannot drift from the stored
study.  It also uses real browser captures of the current web application.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "presentation_assets"
UI = ASSETS / "ui"
OUT = ROOT / "docs" / "RCP_Platform_PI_Review_Aug_2026.pptx"
RESULT_PATH = ROOT / "data" / "runs" / "benchmark-bc0522c9" / "sim" / "experiment_results.json"
MANIFEST_PATH = ROOT / "data" / "runs" / "benchmark-bc0522c9" / "manifest.json"

W = 13.333
H = 7.5
FONT = "Noto Sans"
MONO = "Liberation Mono"

NAVY = "162231"
INK = "233444"
MUTED = "5E7182"
TEAL = "087F95"
CYAN = "21AFC1"
SKY = "DDF4F7"
VIOLET = "6750A4"
LAVENDER = "EEE9FA"
AMBER = "C98212"
AMBER_BG = "FFF3DC"
GREEN = "16825D"
GREEN_BG = "E2F6EE"
RED = "B94747"
RED_BG = "FBE9E9"
PAPER = "F7F9FB"
WHITE = "FFFFFF"
LINE = "D9E2E8"
SOFT = "EDF2F5"
GRAY = "8393A0"
DARK_BG = "101A24"

# The date printed on the title and closing slides.  One constant so a
# regenerated deck cannot disagree with itself about when it was built.
DECK_DATE = "17 AUGUST 2026"

SECTION_COLOR = {
    "CASE": TEAL,
    "METHOD": VIOLET,
    "MODELS": CYAN,
    "STUDY": AMBER,
    "RESULTS": RED,
    "PRODUCT": TEAL,
    "NEXT": VIOLET,
}


def rgb(hex_value: str) -> RGBColor:
    return RGBColor.from_string(hex_value)


def set_shape_fill(shape, color: str, transparency: int = 0) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(color)
    shape.fill.transparency = transparency


def set_shape_line(shape, color: str, width: float = 1.0, transparency: int = 0) -> None:
    shape.line.color.rgb = rgb(color)
    shape.line.width = Pt(width)
    shape.line.transparency = transparency


def rect(slide, x, y, w, h, fill=WHITE, line=LINE, radius=False, line_width=0.8):
    kind = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    sh = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    set_shape_fill(sh, fill)
    set_shape_line(sh, line, line_width)
    if radius and hasattr(sh, "adjustments"):
        try:
            sh.adjustments[0] = 0.12
        except Exception:
            pass
    return sh


def line(slide, x1, y1, x2, y2, color=LINE, width=1.0, dash=None):
    sh = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT,
        Inches(x1),
        Inches(y1),
        Inches(x2),
        Inches(y2),
    )
    set_shape_line(sh, color, width)
    if dash:
        sh.line.dash_style = dash
    return sh


def text_box(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: float = 16,
    color: str = INK,
    bold: bool = False,
    font: str = FONT,
    align=PP_ALIGN.LEFT,
    valign=MSO_ANCHOR.TOP,
    margin: float = 0.03,
    fit: bool = False,
    rotation: float | None = None,
):
    sh = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if rotation is not None:
        sh.rotation = rotation
    tf = sh.text_frame
    tf.clear()
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(margin)
    tf.vertical_anchor = valign
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.alignment = align
    p.font.name = font
    p.font.size = Pt(size)
    p.font.bold = bold
    p.font.color.rgb = rgb(color)
    p.space_before = p.space_after = Pt(0)
    if fit:
        tf.fit_text(font_family=font, max_size=Pt(size))
    return sh


def rich_text(slide, runs, x, y, w, h, *, size=16, color=INK, valign=MSO_ANCHOR.TOP):
    """Add a single paragraph with (text, bold, color) run tuples."""
    sh = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = sh.text_frame
    tf.clear()
    tf.margin_left = tf.margin_right = Inches(0.03)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = valign
    tf.word_wrap = True
    p = tf.paragraphs[0]
    for value, is_bold, run_color in runs:
        r = p.add_run()
        r.text = value
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.bold = is_bold
        r.font.color.rgb = rgb(run_color or color)
    p.space_before = p.space_after = Pt(0)
    return sh


def bullet_list(slide, items: Sequence[str], x, y, w, h, *, size=16, color=INK, bullet_color=TEAL, gap=8):
    sh = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = sh.text_frame
    tf.clear()
    tf.margin_left = tf.margin_right = Inches(0)
    tf.margin_top = tf.margin_bottom = Inches(0)
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        # A literal bullet is more portable across PowerPoint and LibreOffice
        # than relying on editor-specific list XML.
        p.text = f"•  {item}"
        p.font.name = FONT
        p.font.size = Pt(size)
        p.font.color.rgb = rgb(color)
        p.level = 0
        p.space_after = Pt(gap)
        p.line_spacing = 1.06
        for run in p.runs:
            run.font.name = FONT
    return sh


def add_bg(slide, color=PAPER):
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = rgb(color)


def add_footer(slide, num: int, section: str, source: str | None = None, *, dark=False):
    fg = "B7C7D2" if dark else GRAY
    accent = SECTION_COLOR.get(section, TEAL)
    line(slide, 0.45, 7.18, 12.88, 7.18, "314452" if dark else LINE, 0.7)
    rect(slide, 0.45, 7.28, 0.12, 0.04, accent, accent)
    text_box(slide, f"RCP.2026/11  ·  PI REVIEW  ·  {section}", 0.65, 7.20, 3.8, 0.19, size=7.5, color=fg, bold=True)
    if source:
        text_box(slide, source, 4.1, 7.20, 7.75, 0.19, size=6.8, color=fg, align=PP_ALIGN.RIGHT)
    text_box(slide, f"{num:02d}", 12.2, 7.20, 0.65, 0.19, size=7.5, color=fg, bold=True, align=PP_ALIGN.RIGHT)


def add_title(slide, num: int, section: str, title: str, subtitle: str | None = None, source: str | None = None):
    add_bg(slide)
    accent = SECTION_COLOR.get(section, TEAL)
    rect(slide, 0.45, 0.44, 0.08, 0.50, accent, accent)
    text_box(slide, section, 0.66, 0.39, 2.6, 0.23, size=8.5, color=accent, bold=True)
    # Reserve enough height for a two-line title.  Several PI-facing headings are
    # intentionally declarative sentences, and must remain clear in both
    # PowerPoint and LibreOffice's slightly different font metrics.
    text_box(slide, title, 0.64, 0.61, 12.0, 0.77, size=25.5, color=NAVY, bold=True)
    if subtitle:
        text_box(slide, subtitle, 0.66, 1.39, 11.9, 0.34, size=10.5, color=MUTED)
    add_footer(slide, num, section, source)


def add_full_bleed_title(slide, num, title, subtitle, *, eyebrow="RCP PLATFORM · PI REVIEW", date=DECK_DATE):
    add_bg(slide, DARK_BG)
    rect(slide, 0, 0, W, H, DARK_BG, DARK_BG)
    # Decorative system map, deliberately quiet behind the title.
    for x, y, s, col in [
        (9.1, 0.8, 1.35, TEAL), (10.7, 1.65, 0.84, VIOLET), (11.5, 3.1, 1.2, AMBER),
        (9.0, 4.2, 0.9, CYAN), (10.2, 5.25, 1.55, TEAL), (7.8, 2.55, 0.7, VIOLET),
    ]:
        sh = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(s), Inches(s))
        set_shape_fill(sh, col, 74)
        set_shape_line(sh, col, 1.0, 40)
    for a, b in [((8.35, 2.9), (9.75, 1.48)), ((9.75, 1.48), (11.1, 2.0)), ((11.1, 2.0), (12.05, 3.7)), ((12.05, 3.7), (10.95, 6.0)), ((10.95, 6.0), (9.45, 4.65))]:
        line(slide, a[0], a[1], b[0], b[1], "365265", 1.2)
    rect(slide, 0.62, 0.58, 0.52, 0.52, CYAN, CYAN, radius=True)
    text_box(slide, "R", 0.62, 0.58, 0.52, 0.52, size=16, color=WHITE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    text_box(slide, eyebrow, 1.3, 0.64, 4.0, 0.22, size=9, color="A7C3D1", bold=True)
    text_box(slide, title, 0.68, 2.05, 7.6, 1.45, size=38, color=WHITE, bold=True)
    text_box(slide, subtitle, 0.72, 3.62, 6.85, 1.0, size=18, color="BBD1DC")
    line(slide, 0.72, 5.12, 6.9, 5.12, "395264", 1.0)
    text_box(slide, "MODELICA  ×  LLM-GUIDED RESEARCH  ×  AUDITABLE EVIDENCE", 0.72, 5.32, 7.1, 0.30, size=10.5, color=CYAN, bold=True)
    text_box(slide, date, 0.72, 6.58, 3.2, 0.23, size=9, color="839EAC", bold=True)
    text_box(slide, f"{num:02d}", 12.15, 6.95, 0.6, 0.22, size=8, color="78909E", bold=True, align=PP_ALIGN.RIGHT)


def add_pill(slide, label, x, y, w, *, fill=SKY, color=TEAL, border=None, size=9):
    rect(slide, x, y, w, 0.31, fill, border or fill, radius=True)
    text_box(slide, label, x + 0.04, y + 0.015, w - 0.08, 0.25, size=size, color=color, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)


def add_card(slide, x, y, w, h, title, body, *, accent=TEAL, icon=None, fill=WHITE, title_size=15, body_size=11.2):
    rect(slide, x, y, w, h, fill, LINE, radius=True)
    rect(slide, x, y, 0.08, h, accent, accent)
    if icon:
        sh = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.24), Inches(y + 0.24), Inches(0.48), Inches(0.48))
        set_shape_fill(sh, accent)
        set_shape_line(sh, accent)
        text_box(slide, icon, x + 0.24, y + 0.24, 0.48, 0.48, size=12, color=WHITE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
        tx = x + 0.84
    else:
        tx = x + 0.28
    text_box(slide, title, tx, y + 0.22, w - (tx - x) - 0.20, 0.35, size=title_size, color=NAVY, bold=True)
    text_box(slide, body, x + 0.28, y + 0.78, w - 0.50, h - 0.96, size=body_size, color=MUTED)


def add_kpi(slide, x, y, w, h, value, label, *, accent=TEAL, note=None):
    rect(slide, x, y, w, h, WHITE, LINE, radius=True)
    rect(slide, x, y, w, 0.06, accent, accent)
    text_box(slide, value, x + 0.22, y + 0.23, w - 0.44, 0.54, size=24, color=accent, bold=True)
    text_box(slide, label, x + 0.22, y + 0.82, w - 0.44, 0.38, size=10.5, color=NAVY, bold=True)
    if note:
        text_box(slide, note, x + 0.22, y + 1.18, w - 0.44, h - 1.32, size=8.8, color=MUTED)


def add_numbered_step(slide, n, title, body, x, y, w, *, color=TEAL):
    sh = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(0.48), Inches(0.48))
    set_shape_fill(sh, color)
    set_shape_line(sh, color)
    text_box(slide, str(n), x, y, 0.48, 0.48, size=12, color=WHITE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    text_box(slide, title, x + 0.66, y - 0.01, w - 0.66, 0.30, size=13, color=NAVY, bold=True)
    text_box(slide, body, x + 0.66, y + 0.34, w - 0.66, 0.55, size=9.5, color=MUTED)


def add_picture_crop(slide, path: Path, x, y, w, h, *, border=LINE, radius=False):
    with Image.open(path) as im:
        iw, ih = im.size
    image_aspect = iw / ih
    box_aspect = w / h
    if image_aspect > box_aspect:
        shown_w = ih * box_aspect
        crop = (iw - shown_w) / 2 / iw
        pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), width=Inches(w), height=Inches(h))
        pic.crop_left = crop
        pic.crop_right = crop
    else:
        shown_h = iw / box_aspect
        crop = (ih - shown_h) / 2 / ih
        pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), width=Inches(w), height=Inches(h))
        pic.crop_top = crop
        pic.crop_bottom = crop
    frame = rect(slide, x, y, w, h, WHITE, border, radius=radius, line_width=0.9)
    # `transparency = 100` is interpreted inconsistently by LibreOffice and can
    # become an opaque white cover.  An explicit no-fill frame is portable.
    frame.fill.background()
    return pic


def add_picture_contain(slide, path: Path, x, y, w, h, *, border=LINE, radius=False):
    """Place an image without cropping; used for scientific charts and axes."""
    with Image.open(path) as im:
        iw, ih = im.size
    image_aspect = iw / ih
    box_aspect = w / h
    rect(slide, x, y, w, h, WHITE, border, radius=radius, line_width=0.9)
    if image_aspect > box_aspect:
        pw = w
        ph = w / image_aspect
        px, py = x, y + (h - ph) / 2
    else:
        ph = h
        pw = h * image_aspect
        px, py = x + (w - pw) / 2, y
    pic = slide.shapes.add_picture(str(path), Inches(px), Inches(py), width=Inches(pw), height=Inches(ph))
    frame = rect(slide, x, y, w, h, WHITE, border, radius=radius, line_width=0.9)
    frame.fill.background()
    return pic


def add_callout(slide, text, x, y, w, h, *, fill=SKY, color=TEAL, border=None, title=None):
    rect(slide, x, y, w, h, fill, border or color, radius=True)
    if title:
        text_box(slide, title, x + 0.22, y + 0.18, w - 0.44, 0.27, size=10, color=color, bold=True)
        text_box(slide, text, x + 0.22, y + 0.52, w - 0.44, h - 0.67, size=11, color=INK)
    else:
        text_box(slide, text, x + 0.24, y + 0.16, w - 0.48, h - 0.30, size=11.5, color=color, bold=True, valign=MSO_ANCHOR.MIDDLE)


def add_section_slide(slide, num, section, headline, statement, chips):
    add_bg(slide, NAVY)
    accent = SECTION_COLOR.get(section, TEAL)
    rect(slide, 0.62, 0.62, 0.09, 0.46, accent, accent)
    text_box(slide, section, 0.88, 0.66, 3.0, 0.24, size=9.5, color=accent, bold=True)
    text_box(slide, headline, 0.72, 1.73, 11.6, 0.78, size=34, color=WHITE, bold=True)
    text_box(slide, statement, 0.74, 2.73, 10.8, 1.15, size=19, color="C6D6DF")
    line(slide, 0.74, 4.55, 11.9, 4.55, "405361", 1.0)
    x = 0.74
    for label in chips:
        width = max(1.35, min(2.35, 0.11 * len(label) + 0.55))
        add_pill(slide, label, x, 4.92, width, fill="203442", color="CBEAF0", border="365363", size=9)
        x += width + 0.18
    add_footer(slide, num, section, dark=True)


def short_hash(value: str) -> str:
    return f"{value[:10]}…{value[-6:]}"


def load_benchmark():
    return json.loads(RESULT_PATH.read_text()), json.loads(MANIFEST_PATH.read_text())


def comp_map(result):
    return {(c["pair_id"], c["metric"]): c for c in result["comparisons"]}


def generate_charts(result):
    ASSETS.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.titlesize": 13,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "text.color": "#233444",
        "axes.labelcolor": "#5E7182",
        "xtick.color": "#5E7182",
        "ytick.color": "#5E7182",
        "axes.edgecolor": "#D9E2E8",
    })
    cmap = comp_map(result)
    loads = [400, 500, 600]
    setpoints = [6, 8, 10]

    energy = np.array([[cmap[(f"pair-q{q}-t{t}", "E_HVAC_kWh")]["percent_delta"] for t in setpoints] for q in loads])
    temp = np.array([[cmap[(f"pair-q{q}-t{t}", "T_room_peak_degC")]["absolute_delta"] for t in setpoints] for q in loads])

    def heatmap(values, path, title, subtitle, fmt, vmin, vmax, center=0, cmap_name="RdYlGn_r"):
        fig, ax = plt.subplots(figsize=(7.1, 4.25), dpi=190)
        fig.patch.set_facecolor("#FFFFFF")
        im = ax.imshow(values, cmap=cmap_name, vmin=vmin, vmax=vmax, aspect="auto")
        ax.set_xticks(range(3), [f"{x} °C" for x in setpoints])
        ax.set_yticks(range(3), [f"{x} kW" for x in loads])
        ax.set_xlabel("Chilled-water supply setpoint")
        ax.set_ylabel("Computer-room heat load")
        ax.set_title(title, loc="left", fontweight="bold", color="#162231", pad=20)
        ax.text(0, 1.03, subtitle, transform=ax.transAxes, fontsize=9, color="#5E7182")
        for i in range(3):
            for j in range(3):
                val = values[i, j]
                ax.text(j, i, fmt.format(val), ha="center", va="center", fontsize=12, fontweight="bold", color="#162231")
        ax.spines[:].set_visible(False)
        cbar = fig.colorbar(im, ax=ax, fraction=.036, pad=.035)
        cbar.outline.set_visible(False)
        fig.tight_layout(pad=1.4)
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        plt.close(fig)

    heatmap(energy, ASSETS / "energy_delta_heatmap.png", "Integrated configuration increases screened HVAC energy", "Percent change relative to non-integrated baseline · lower is better", "+{:.1f}%", 0, 20, cmap_name="YlOrRd")
    heatmap(temp, ASSETS / "temperature_delta_heatmap.png", "Thermal effect is concentrated at the 6 °C setpoint", "Absolute change in peak room temperature · negative is cooler", "{:+.3f} °C", -1.0, 0.2, cmap_name="RdYlGn_r")

    # Representative operating-mode allocation.
    case = {c["case_id"]: c for c in result["cases"]}
    ids = ["baseline-q500-t6", "candidate-q500-t6"]
    modes = ["free_cooling_hours", "partial_mechanical_hours", "full_mechanical_hours"]
    labels = ["Free cooling", "Partial mechanical", "Full mechanical"]
    colors = ["#21AFC1", "#C98212", "#6750A4"]
    fig, ax = plt.subplots(figsize=(7.5, 3.9), dpi=190)
    fig.patch.set_facecolor("white")
    left = np.zeros(2)
    for metric, label, color in zip(modes, labels, colors):
        vals = [case[c]["metrics"][metric] for c in ids]
        ax.barh([0, 1], vals, left=left, color=color, height=.46, label=label)
        for yi, (lft, val) in enumerate(zip(left, vals)):
            if val > 1.1:
                ax.text(lft + val / 2, yi, f"{val:.1f} h", ha="center", va="center", color="white", fontsize=9, fontweight="bold")
        left += vals
    ax.set_yticks([0, 1], ["Non-integrated", "Integrated"])
    ax.set_xlim(0, 24)
    ax.set_xlabel("Hours in a 24-hour run")
    ax.set_title("Integration changes how the plant operates", loc="left", fontweight="bold", color="#162231", pad=16)
    ax.text(0, 1.03, "Representative pair: 500 kW load · 6 °C chilled-water setpoint", transform=ax.transAxes, fontsize=9, color="#5E7182")
    ax.legend(loc="lower center", bbox_to_anchor=(.5, -0.34), ncol=3, frameon=False)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", color="#E7EDF1", linewidth=.8)
    ax.set_axisbelow(True)
    fig.tight_layout(pad=1.3)
    fig.savefig(ASSETS / "mode_allocation.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # Screening fractions, parsed from the quality report to avoid recomputation drift.
    check = next(x for x in result["quality_report"]["checks"] if x["id"] == "power-screen-fraction")
    entries = []
    for part in check["observed"].split(", "):
        name, val = part.split("=")
        entries.append((name.replace("baseline", "N").replace("candidate", "I"), float(val.rstrip("%"))))
    fig, ax = plt.subplots(figsize=(8.7, 3.75), dpi=190)
    fig.patch.set_facecolor("white")
    vals = [v for _, v in entries]
    bar_colors = ["#087F95" if n.startswith("I") else "#8393A0" for n, _ in entries]
    ax.bar(range(len(entries)), vals, color=bar_colors, width=.72)
    ax.axhline(1.0, color="#B94747", linewidth=1.5, linestyle="--")
    ax.text(17.4, 1.02, "1% preregistered maximum", ha="right", va="bottom", fontsize=8.5, color="#B94747")
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Screened samples (%)")
    ax.set_xticks(range(len(entries)), [n.replace("-q", " ").replace("-t", "/") for n, _ in entries], rotation=55, ha="right", fontsize=7)
    ax.set_title("Numerical-event screening stays below the approved maximum", loc="left", fontweight="bold", color="#162231", pad=15)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#E7EDF1", linewidth=.8)
    ax.set_axisbelow(True)
    fig.tight_layout(pad=1.2)
    fig.savefig(ASSETS / "screening_fraction.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # Trade-off map: energy delta vs temperature delta.
    fig, ax = plt.subplots(figsize=(7.4, 4.2), dpi=190)
    fig.patch.set_facecolor("white")
    for t, color in zip(setpoints, ["#087F95", "#C98212", "#6750A4"]):
        xs, ys = [], []
        for q in loads:
            pair = f"pair-q{q}-t{t}"
            xs.append(cmap[(pair, "E_HVAC_kWh")]["percent_delta"])
            ys.append(cmap[(pair, "T_room_peak_degC")]["absolute_delta"])
        ax.scatter(xs, ys, s=90, color=color, label=f"{t} °C setpoint", edgecolor="white", linewidth=1.1, zorder=3)
        for x, y, q in zip(xs, ys, loads):
            ax.annotate(f"{q}", (x, y), xytext=(5, 4), textcoords="offset points", fontsize=7, color=color)
    ax.axhline(0, color="#8393A0", linewidth=1)
    ax.axvline(0, color="#8393A0", linewidth=1)
    ax.fill_between([0, 20], -1, 0, color="#E2F6EE", alpha=.7)
    ax.set_xlim(0, 20)
    ax.set_ylim(-1.0, .18)
    ax.set_xlabel("HVAC energy change (%)")
    ax.set_ylabel("Peak room temperature change (°C)")
    ax.set_title("The benchmark reveals a trade-off—not a winner", loc="left", fontweight="bold", color="#162231", pad=14)
    ax.legend(frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(color="#E7EDF1", linewidth=.8)
    ax.set_axisbelow(True)
    fig.tight_layout(pad=1.2)
    fig.savefig(ASSETS / "tradeoff_map.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # Ranking weights.
    weights = [50, 20, 12, 10, 8]
    labels = ["Relevance", "Credibility", "Evidence completeness", "Citation impact", "Recency"]
    colors = ["#087F95", "#21AFC1", "#6750A4", "#C98212", "#8393A0"]
    fig, ax = plt.subplots(figsize=(5.2, 4.1), dpi=190)
    fig.patch.set_facecolor("white")
    wedges, _ = ax.pie(weights, startangle=90, colors=colors, wedgeprops={"width": .34, "edgecolor": "white"})
    ax.text(0, .05, "Paper rank", ha="center", va="center", fontsize=11, color="#5E7182")
    ax.text(0, -.16, "100%", ha="center", va="center", fontsize=20, fontweight="bold", color="#162231")
    ax.legend(wedges, [f"{l}  {w}%" for l, w in zip(labels, weights)], loc="center left", bbox_to_anchor=(.98, .5), frameon=False, fontsize=8.5)
    ax.set(aspect="equal")
    fig.tight_layout()
    fig.savefig(ASSETS / "paper_rank_weights.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # Raw-series view for one representative pair. It demonstrates that scientific
    # conclusions are grounded in trajectories, even though the main deck focuses on metrics.
    def read_series(case_id):
        item = case[case_id]
        with open(ROOT / item["result_file"], newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            inds = [header.index(x) for x in ("time", "T_room_K", "P_HVAC_W")]
            rows = [(float(r[inds[0]]) / 3600, float(r[inds[1]]) - 273.15, float(r[inds[2]]) / 1000) for r in reader]
        arr = np.asarray(rows)
        p = arr[:, 2]
        valid = np.isfinite(p) & (p >= 0) & (p <= 2000)
        if not valid.all():
            p = np.interp(np.arange(len(p)), np.flatnonzero(valid), p[valid])
        return arr[:, 0], arr[:, 1], p

    fig, axes = plt.subplots(2, 1, figsize=(8.3, 5.0), dpi=190, sharex=True)
    fig.patch.set_facecolor("white")
    for cid, label, color in [
        ("baseline-q500-t6", "Non-integrated", "#8393A0"),
        ("candidate-q500-t6", "Integrated", "#087F95"),
    ]:
        t, temp_s, power = read_series(cid)
        axes[0].plot(t, temp_s, color=color, linewidth=1.6, label=label)
        axes[1].plot(t, power, color=color, linewidth=1.2, label=label)
    axes[0].set_ylabel("Room temperature (°C)")
    axes[1].set_ylabel("Screened HVAC power (kW)")
    axes[1].set_xlabel("Simulation time (hours)")
    axes[0].set_title("Stored trajectories support metric-level comparisons", loc="left", fontweight="bold", color="#162231", pad=12)
    axes[0].text(0, 1.04, "Representative pair: 500 kW · 6 °C · 24 hours", transform=axes[0].transAxes, fontsize=9, color="#5E7182")
    axes[0].legend(frameon=False, ncol=2, loc="lower right")
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(color="#E7EDF1", linewidth=.7)
        ax.set_axisbelow(True)
    fig.tight_layout(pad=1.0)
    fig.savefig(ASSETS / "representative_trajectories.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def add_arch_node(slide, x, y, w, h, title, subtitle, color, *, inverted=False):
    fill = color if inverted else WHITE
    fg = WHITE if inverted else NAVY
    rect(slide, x, y, w, h, fill, color, radius=True, line_width=1.2)
    text_box(slide, title, x + .18, y + .16, w - .36, .28, size=12.5, color=fg, bold=True, align=PP_ALIGN.CENTER)
    text_box(slide, subtitle, x + .16, y + .53, w - .32, h - .65, size=8.3, color=("E4EFF3" if inverted else MUTED), align=PP_ALIGN.CENTER)


def build_deck(result, manifest):
    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)
    blank = prs.slide_layouts[6]
    prs.core_properties.title = "RCP Platform — Research Cockpit for Auditable Modelica Studies"
    prs.core_properties.subject = "PI review: research method, Modelica benchmark, LLM orchestration, evidence, and product"
    prs.core_properties.author = "RCP Platform team"
    prs.core_properties.keywords = "Modelica, LLM, OpenModelica, research cockpit, reproducibility, data-center cooling"
    prs.core_properties.comments = f"Generated from repository evidence on {DECK_DATE.title()}."

    cmap = comp_map(result)
    cases = {c["case_id"]: c for c in result["cases"]}
    e_deltas = [c["percent_delta"] for c in result["comparisons"] if c["metric"] == "E_HVAC_kWh"]
    pue_deltas = [c["percent_delta"] for c in result["comparisons"] if c["metric"] == "PUE"]
    t6_abs = [c["absolute_delta"] for c in result["comparisons"] if c["metric"] == "T_room_peak_degC" and c["pair_id"].endswith("t6")]
    quality = result["quality_report"]
    q_pass = sum(c["status"] == "passed" for c in quality["checks"])
    q_warn = sum(c["status"] == "warning" for c in quality["checks"])
    slide_no = 0

    def new():
        nonlocal slide_no
        slide_no += 1
        return prs.slides.add_slide(blank), slide_no

    # 1 — title
    s, n = new()
    add_full_bleed_title(
        s,
        n,
        "From research question\nto auditable simulation evidence",
        "A practical research cockpit combining literature memory, constrained LLM reasoning, reproducible Modelica experiments, and claim-level provenance.",
    )

    # 2 — executive message
    s, n = new()
    add_title(s, n, "CASE", "The platform is a research control plane—not an autonomous scientist", "It accelerates the tractable parts of computational research while making human choices and model limitations visible.")
    add_card(s, .65, 1.92, 3.83, 3.28, "What it automates", "Literature retrieval and screening\nStructured gap and hypothesis drafts\nModel selection and bounded parameterization\nBatch execution, analysis, and reporting", accent=TEAL, icon="01")
    add_card(s, 4.75, 1.92, 3.83, 3.28, "What remains human", "Choice of research direction\nApproval of the scientific plan\nInterpretation of trade-offs\nJudgment about validity and contribution", accent=VIOLET, icon="02")
    add_card(s, 8.85, 1.92, 3.83, 3.28, "What is auditable", "Frozen literature snapshot\nApproved plan and protocol hashes\nPinned runtime and raw-file fingerprints\nRevisioned analysis and claim links", accent=AMBER, icon="03")
    add_callout(s, "Core proposition: move faster without collapsing generation, execution, evidence, and scientific judgment into one opaque step.", .92, 5.56, 11.5, .78, fill=SKY, color=TEAL)

    # 3 — why this matters
    s, n = new()
    add_title(s, n, "CASE", "Computational research is fragmented at exactly the points that matter", "The costly work is not one simulation—it is preserving intent and evidence across the whole loop.")
    labels = [
        ("Literature drift", "Searches change; rationales disappear; missing abstracts are easily overinterpreted."),
        ("Plan drift", "Parameters and metrics change between the research question, execution, and analysis."),
        ("Environment drift", "Model libraries, solvers, and runtime images silently alter behavior."),
        ("Evidence drift", "Final prose becomes detached from cases, files, comparisons, and caveats."),
    ]
    for i, (title, body) in enumerate(labels):
        x = .68 + (i % 2) * 6.15
        y = 1.92 + (i // 2) * 2.18
        add_card(s, x, y, 5.82, 1.78, title, body, accent=[TEAL, VIOLET, AMBER, RED][i], icon=f"{i+1}", body_size=10.5)
    text_box(s, "The design response", .72, 6.19, 2.0, .25, size=9, color=TEAL, bold=True)
    text_box(s, "Treat every transition as a typed, inspectable artifact—not just a prompt or log line.", 2.30, 6.11, 9.8, .42, size=15, color=NAVY, bold=True)

    # 4 — objective and boundaries
    s, n = new()
    add_title(s, n, "CASE", "Scope is intentionally narrow: defensible simulation studies", "The current domain is data-center cooling, but the control pattern is designed to generalize.")
    add_pill(s, "IN SCOPE", .72, 1.88, 1.22, fill=GREEN_BG, color=GREEN)
    bullet_list(s, [
        "Turn a research profile into ranked, traceable hypothesis candidates",
        "Compile approved ideas into registered Modelica experiments",
        "Execute matched studies inside a pinned OpenModelica environment",
        "Verify raw results, analyze under a preregistered protocol, and draft linked claims",
    ], .82, 2.38, 5.55, 3.0, size=15, gap=13)
    line(s, 6.62, 1.90, 6.62, 6.22, LINE, 1.1)
    add_pill(s, "NOT CLAIMED", 6.95, 1.88, 1.55, fill=RED_BG, color=RED)
    bullet_list(s, [
        "Autonomous novelty determination or publication readiness",
        "Physical validation without calibration data",
        "Universal correctness of an LLM-generated hypothesis",
        "Replacement for a PI, domain expert, or independent reviewer",
    ], 7.04, 2.38, 5.35, 3.0, size=15, gap=13)
    add_callout(s, "Success means a shorter path to a reviewable study—not an automated scientific verdict.", .92, 5.68, 11.5, .67, fill=AMBER_BG, color=AMBER)

    # 5 — lifecycle
    s, n = new()
    add_title(s, n, "CASE", "One closed loop connects intent, execution, and evidence", "Eleven workflow nodes create explicit hand-offs; two human gates stop silent scientific drift.", source="Source: /api/health node graph")
    nodes = [
        ("Research\nmemory", "01"), ("Gap\nmining", "02"), ("Hypothesis\ngeneration", "03"), ("Select\nhypothesis", "H1"),
        ("Compile\nspecification", "05"), ("Approve\nplan", "H2"), ("Run\nModelica", "07"), ("Analyze\nresults", "08"),
        ("Review\nevidence", "09"), ("Draft\nreport", "10"),
    ]
    for i, (label, code) in enumerate(nodes):
        x = .63 + (i % 5) * 2.49
        y = 1.95 + (i // 5) * 2.15
        color = VIOLET if code.startswith("H") else (CYAN if i in (6, 7) else TEAL)
        add_arch_node(s, x, y, 2.05, 1.10, label, "human gate" if code.startswith("H") else code, color, inverted=code.startswith("H"))
        if i % 5 < 4:
            line(s, x + 2.06, y + .55, x + 2.40, y + .55, color, 1.6)
    # connection across rows and revision loop
    line(s, 12.58, 2.50, 12.58, 4.08, TEAL, 1.4)
    line(s, 12.58, 4.08, 10.58, 4.08, TEAL, 1.4)
    add_callout(s, "Failure handling is explicit; plan revision loops are bounded to three attempts.", 3.0, 5.70, 7.35, .66, fill=WHITE, color=VIOLET, border=VIOLET)

    # 6 — architecture
    s, n = new()
    add_title(s, n, "CASE", "Four layers separate probabilistic reasoning from deterministic evidence", "This boundary is the core reliability mechanism.")
    layers = [
        ("01 · RESEARCH INTERFACE", "Profiles · gates · run cockpit · evidence review", TEAL),
        ("02 · AGENT WORKFLOW", "Typed state · constrained LLM calls · revision loops", VIOLET),
        ("03 · SCIENTIFIC RUNTIME", "Registry · compiler · OpenModelica · batch analysis", CYAN),
        ("04 · EVIDENCE STORE", "Snapshots · raw series · hashes · revisions · exports", AMBER),
    ]
    for i, (title, body, color) in enumerate(layers):
        y = 1.83 + i * 1.03
        rect(s, .78, y, 8.15, .80, WHITE, color, radius=True, line_width=1.3)
        rect(s, .78, y, 1.08, .80, color, color, radius=True)
        text_box(s, f"{i+1:02d}", .78, y, 1.08, .80, size=18, color=WHITE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
        text_box(s, title, 2.10, y + .13, 3.0, .24, size=11.5, color=NAVY, bold=True)
        text_box(s, body, 5.15, y + .13, 3.45, .40, size=10.2, color=MUTED, align=PP_ALIGN.RIGHT)
    rect(s, 9.48, 1.83, 3.05, 3.89, NAVY, NAVY, radius=True)
    text_box(s, "Boundary rule", 9.82, 2.18, 2.35, .35, size=12, color=CYAN, bold=True)
    text_box(s, "LLMs may propose.\n\nSchemas must validate.\n\nCompilers bound.\n\nRuntimes measure.\n\nHashes prove.", 9.82, 2.78, 2.35, 2.45, size=16, color=WHITE, bold=True)
    add_callout(s, "A fluent answer is never treated as a simulation result.", 1.56, 6.02, 10.20, .58, fill=SKY, color=TEAL)

    # 7 section
    s, n = new()
    add_section_slide(s, n, "METHOD", "Constrained intelligence, not free-form automation", "The LLM is useful where ambiguity is real—synthesis, framing, and drafting. Deterministic components take over where correctness can be checked.", ["Research Memory", "Schema constraints", "Human gates", "Deterministic compiler"])

    # 8 research memory
    s, n = new()
    add_title(s, n, "METHOD", "Research Memory freezes the literature context used by the run", "A reproducible snapshot makes later hypotheses and claims inspectable.")
    flow = [
        ("Query planner", "4 focused queries"), ("Dual retrieval", "OpenAlex + Semantic Scholar"), ("Resolve identity", "DOI deduplication"),
        ("Screen", "Relevance + disclosure"), ("Enrich", "Crossref metadata"), ("Rank", "Deterministic weights"),
        ("Extract", "PaperCards"), ("Map", "Themes + gaps"), ("Freeze", "Snapshot hash"),
    ]
    for i, (t, b) in enumerate(flow):
        x = .65 + (i % 3) * 4.13
        y = 1.82 + (i // 3) * 1.42
        add_arch_node(s, x, y, 3.54, .95, t, b, [TEAL, VIOLET, AMBER][i % 3], inverted=(i == 8))
        if i % 3 < 2:
            line(s, x + 3.54, y + .47, x + 3.93, y + .47, GRAY, 1.2)
    add_callout(s, "Missing abstracts are marked insufficient; the platform does not invent methods or limitations to complete a card.", 1.18, 6.10, 10.95, .55, fill=AMBER_BG, color=AMBER)

    # 9 paper ranking
    s, n = new()
    add_title(s, n, "METHOD", "Ranking is deterministic and credibility is disclosed", "Relevance dominates the score; venue status and evidence completeness remain visible rather than silently blended.")
    add_picture_contain(s, ASSETS / "paper_rank_weights.png", .58, 1.77, 6.0, 4.80, border=WHITE)
    add_card(s, 7.00, 1.90, 5.62, 1.02, "Verified", "Cross-source identity and publication metadata align.", accent=GREEN, icon="✓", body_size=9.5)
    add_card(s, 7.00, 3.06, 5.62, 1.02, "Likely / uncertain", "Evidence is usable with an explicit confidence label.", accent=AMBER, icon="?", body_size=9.5)
    add_card(s, 7.00, 4.22, 5.62, 1.02, "Preprint", "Not discarded—but never presented as peer-reviewed.", accent=VIOLET, icon="P", body_size=9.5)
    add_callout(s, "The ranking can prioritize attention; it cannot determine truth.", 7.15, 5.62, 5.28, .68, fill=SKY, color=TEAL)

    # 10 LLM strategy
    s, n = new()
    add_title(s, n, "METHOD", "The LLM layer is replaceable, constrained, and measured", "Current default: DeepSeek V4 Flash through an OpenRouter-compatible endpoint.", source="Source: src/rcp/config.py and src/rcp/llm/client.py")
    add_kpi(s, .70, 1.90, 2.74, 1.72, "0.2", "Temperature", accent=TEAL, note="Bias toward repeatable structured outputs")
    add_kpi(s, 3.65, 1.90, 2.74, 1.72, "JSON", "Pydantic schemas", accent=VIOLET, note="Reject malformed or incomplete responses")
    add_kpi(s, 6.60, 1.90, 2.74, 1.72, "Retry", "Validation repair", accent=AMBER, note="A bounded second chance—not silent coercion")
    add_kpi(s, 9.55, 1.90, 2.74, 1.72, "Usage", "Token capture", accent=CYAN, note="Per-call accounting retained in run state")
    add_card(s, .70, 4.05, 3.73, 1.58, "Provider-agnostic", "OpenAI-compatible client boundary allows model replacement without changing scientific artifacts.", accent=TEAL, body_size=10.2)
    add_card(s, 4.80, 4.05, 3.73, 1.58, "Reasoning separated", "Generated hypotheses and prose never overwrite observed Modelica outputs or hashes.", accent=VIOLET, body_size=10.2)
    add_card(s, 8.90, 4.05, 3.73, 1.58, "Failure visible", "Provider warnings, schema failures, and missing evidence propagate to the user interface.", accent=RED, body_size=10.2)
    add_callout(s, "Model choice is a configuration decision; evidentiary rules are platform invariants.", 1.60, 5.97, 10.15, .61, fill=WHITE, color=VIOLET, border=VIOLET)

    # 11 LLM vs deterministic
    s, n = new()
    add_title(s, n, "METHOD", "Every task is assigned to the least ambiguous mechanism", "This division of labor reduces hallucination surface and makes failures diagnosable.")
    text_box(s, "LLM-SUITABLE", .85, 1.86, 5.4, .30, size=10, color=VIOLET, bold=True)
    text_box(s, "DETERMINISTIC", 7.05, 1.86, 5.4, .30, size=10, color=TEAL, bold=True)
    left = ["Synthesize literature themes", "Propose research gaps", "Draft candidate hypotheses", "Explain results in plain language"]
    right = ["Resolve and rank papers", "Validate schemas and bounds", "Compile experiment cases", "Compute metrics, hashes, and quality gates"]
    for i, item in enumerate(left):
        add_numbered_step(s, i + 1, item, "Useful where judgment and language matter.", .88, 2.38 + i * .93, 5.3, color=VIOLET)
    line(s, 6.62, 1.90, 6.62, 6.22, LINE, 1.2)
    for i, item in enumerate(right):
        add_numbered_step(s, i + 1, item, "Used where the rule can be made explicit and tested.", 7.05, 2.38 + i * .93, 5.3, color=TEAL)
    add_callout(s, "Human judgment spans both columns: selecting questions, approving plans, and interpreting evidence.", 2.03, 6.26, 9.28, .48, fill=AMBER_BG, color=AMBER)

    # 12 typed objects
    s, n = new()
    add_title(s, n, "METHOD", "Typed artifacts are the hand-offs between agents", "Each stage receives a bounded object rather than an unstructured transcript.")
    objects = [
        ("ThesisProfile", "domain · interests · objectives · constraints"),
        ("PaperCard", "identity · methods · findings · limitations"),
        ("Hypothesis", "question · mechanism · contribution · risks"),
        ("ExperimentPlan", "cases · pairs · metrics · protocol"),
        ("ResultBundle", "files · fingerprints · metrics · warnings"),
        ("Claim", "statement · comparison IDs · paper IDs"),
    ]
    for i, (name, fields) in enumerate(objects):
        x = .76 + (i % 3) * 4.17
        y = 1.93 + (i // 3) * 2.06
        rect(s, x, y, 3.72, 1.56, WHITE, [TEAL, VIOLET, AMBER][i % 3], radius=True, line_width=1.2)
        text_box(s, f"{i+1:02d}", x + .23, y + .18, .50, .25, size=9, color=[TEAL, VIOLET, AMBER][i % 3], bold=True)
        text_box(s, name, x + .23, y + .56, 3.20, .32, size=16, color=NAVY, bold=True)
        text_box(s, fields, x + .23, y + 1.02, 3.20, .30, size=9.3, color=MUTED, font=MONO)
    add_callout(s, "Typed state makes a run resumable, testable, and reviewable without replaying the LLM conversation.", 1.40, 6.18, 10.55, .54, fill=SKY, color=TEAL)

    # 13 scientific compiler
    s, n = new()
    add_title(s, n, "METHOD", "The scientific compiler turns an approved idea into executable cases", "It selects only registered models and deterministically clamps or rejects unsafe parameters.")
    stages = [
        ("Approved hypothesis", "mechanism + boundary", VIOLET),
        ("Registry lookup", "known model + ranges", TEAL),
        ("Parameter binding", "clamp / drop / warn", AMBER),
        ("Plan validation", "cases + matched pairs", CYAN),
        ("Execution spec", "sealed hash", GREEN),
    ]
    for i, (a, b, col) in enumerate(stages):
        x = .55 + i * 2.55
        add_arch_node(s, x, 2.10, 2.08, 1.28, a, b, col, inverted=(i in (0, 4)))
        if i < 4:
            line(s, x + 2.08, 2.74, x + 2.47, 2.74, GRAY, 1.4)
    add_card(s, .76, 4.14, 3.64, 1.42, "Bounded inputs", "Ranges, units, defaults, and operating envelopes live with each model.", accent=TEAL, body_size=9.8)
    add_card(s, 4.84, 4.14, 3.64, 1.42, "Reproducible expansion", "A 3 × 3 design becomes 18 explicit cases and nine matched pairs.", accent=VIOLET, body_size=9.8)
    add_card(s, 8.92, 4.14, 3.64, 1.42, "Fail closed", "Unknown models, invalid structures, or unapproved plans do not reach the runtime.", accent=RED, body_size=9.8)
    add_callout(s, "Compilation is the trust boundary between generative intent and physical simulation.", 2.05, 5.96, 9.28, .60, fill=AMBER_BG, color=AMBER)

    # 14 gates
    s, n = new()
    add_title(s, n, "METHOD", "Two human gates preserve scientific agency", "The platform can operate quickly without treating automation as authorization.")
    add_card(s, .78, 1.88, 5.67, 3.36, "Gate 1 · Select hypothesis", "Reviewer sees ranked candidates, the research question, novelty claim, feasibility, supporting papers, risks, model fit, provider warnings, and ranking rationale.", accent=VIOLET, icon="H1", title_size=16, body_size=12)
    add_card(s, 6.88, 1.88, 5.67, 3.36, "Gate 2 · Approve experiment plan", "Reviewer sees the model, parameters, operating ranges, cases, matched comparisons, outputs, metrics, protocol, validation issues, and disclosures before any compute begins.", accent=TEAL, icon="H2", title_size=16, body_size=12)
    line(s, 6.66, 2.13, 6.66, 5.07, LINE, 1.0)
    add_callout(s, "Rejecting a plan creates a visible revision request; the loop is capped at three revisions.", 1.20, 5.68, 10.93, .68, fill=SKY, color=TEAL)

    # 15 section
    s, n = new()
    add_section_slide(s, n, "MODELS", "Modelica is the executable theory layer", "Equation-based models make assumptions, state, and conservation relationships explicit—while the registry prevents ‘any model, any parameter’ execution.", ["OpenModelica", "Model registry", "Credibility tiers", "Pinned libraries"])

    # 16 why modelica
    s, n = new()
    add_title(s, n, "MODELS", "Why Modelica fits this research workflow", "It supplies an inspectable physical model beneath the language-model layer.")
    add_card(s, .72, 1.90, 3.78, 3.50, "Declarative physics", "Components describe equations and connections rather than a fixed procedural solver sequence. That is valuable for multi-domain thermal and fluid systems.", accent=CYAN, icon="∑", body_size=11.5)
    add_card(s, 4.78, 1.90, 3.78, 3.50, "Composable systems", "Rooms, heat exchangers, pumps, chillers, controllers, weather, and sensors can be assembled while retaining their physical interfaces.", accent=TEAL, icon="↔", body_size=11.5)
    add_card(s, 8.84, 1.90, 3.78, 3.50, "Reproducible execution", "OpenModelica compiles each sealed specification inside a pinned image; outputs become files that can be fingerprinted and reanalyzed.", accent=VIOLET, icon="✓", body_size=11.5)
    add_callout(s, "Modelica increases transparency of the model—but does not by itself validate the model against reality.", 1.17, 5.77, 11.0, .67, fill=AMBER_BG, color=AMBER)

    # 17 registry tiers
    s, n = new()
    add_title(s, n, "MODELS", "The model registry carries credibility and operating boundaries", "Models are not interchangeable; each exposes its own inputs, outputs, validation tier, and limitations.", source="Source: src/rcp/models_library/registry.json")
    add_card(s, .72, 1.88, 3.78, 3.72, "DataCenterRoom", "Conceptual · v1.0.0\n\nSingle-zone thermal balance with proportional cooling and constant COP. Fast enough for interactive hypothesis exploration.", accent=AMBER, icon="C", body_size=11.0)
    add_card(s, 4.78, 1.88, 3.78, 3.72, "Non-integrated plant", "Library-validated · Buildings 13.0.0\n\nPinned wrapper around the non-integrated primary-secondary waterside-economizer example. Baseline in the milestone study.", accent=TEAL, icon="N", body_size=10.8)
    add_card(s, 8.84, 1.88, 3.78, 3.72, "Integrated plant", "Library-validated · Buildings 13.0.0\n\nPinned wrapper around the integrated primary-secondary waterside-economizer example. Candidate configuration.", accent=VIOLET, icon="I", body_size=10.8)
    add_pill(s, "EXPLORATORY", 1.40, 5.90, 1.72, fill=AMBER_BG, color=AMBER)
    add_pill(s, "LIBRARY REGRESSION", 5.46, 5.90, 2.18, fill=SKY, color=TEAL)
    add_pill(s, "LIBRARY REGRESSION", 9.52, 5.90, 2.18, fill=LAVENDER, color=VIOLET)

    # 18 conceptual model
    s, n = new()
    add_title(s, n, "MODELS", "DataCenterRoom is a transparent conceptual model", "Its value is speed and interpretability—not facility-level fidelity.", source="Source: DataCenterRoom.mo and model validation checks")
    # equation panel
    rect(s, .72, 1.87, 5.47, 3.82, NAVY, NAVY, radius=True)
    text_box(s, "ROOM ENERGY BALANCE", 1.05, 2.17, 4.8, .26, size=9.5, color=CYAN, bold=True)
    text_box(s, "C · dT/dt  =  QIT  +  UA(Tamb − T)  −  Qcool", 1.05, 2.82, 4.82, .55, size=19, color=WHITE, bold=True, font="DejaVu Sans")
    text_box(s, "Qcool = clamp[kp(T − Tset), 0, Qmax]", 1.05, 3.75, 4.8, .40, size=16, color="C6D6DF", font="DejaVu Sans")
    text_box(s, "Pcool = Qcool / COP", 1.05, 4.53, 4.8, .36, size=16, color="C6D6DF", font="DejaVu Sans")
    add_pill(s, "8 bounded parameters", 1.05, 5.12, 1.85, fill="203442", color=CYAN, border="365363")
    checks = [
        ("0 W", "energy-balance residual"), ("26.818 °C", "analytic equilibrium"),
        ("100 °C", "saturation branch equilibrium"), ("bitwise", "repeatability"),
        ("passed", "unit consistency"), ("directional", "load/capacity sensitivity"),
    ]
    for i, (value, label) in enumerate(checks):
        x = 6.58 + (i % 2) * 3.10
        y = 1.88 + (i // 2) * 1.31
        add_kpi(s, x, y, 2.80, 1.08, value, label, accent=[TEAL, VIOLET][i % 2])
    add_callout(s, "Omitted: spatial hot spots, humidity, airflow network, equipment transients, sensor uncertainty, and calibration data.", 6.58, 5.91, 5.90, .62, fill=AMBER_BG, color=AMBER)

    # 19 benchmark models
    s, n = new()
    add_title(s, n, "MODELS", "The milestone benchmark compares two Buildings library configurations", "Both share the same room load, weather profile, outputs, horizon, and chilled-water setpoint.")
    rect(s, .72, 1.90, 5.64, 3.85, WHITE, TEAL, radius=True, line_width=1.3)
    text_box(s, "NON-INTEGRATED", 1.06, 2.20, 4.9, .28, size=10, color=TEAL, bold=True)
    text_box(s, "Primary–secondary plant with waterside economizer", 1.06, 2.63, 4.86, .62, size=19, color=NAVY, bold=True)
    add_arch_node(s, 1.05, 3.65, 1.18, .82, "Load", "400–600 kW", TEAL)
    add_arch_node(s, 2.68, 3.65, 1.18, .82, "Plant", "baseline", TEAL, inverted=True)
    add_arch_node(s, 4.31, 3.65, 1.18, .82, "Room", "return air", TEAL)
    line(s, 2.23, 4.06, 2.68, 4.06, TEAL, 1.4); line(s, 3.86, 4.06, 4.31, 4.06, TEAL, 1.4)
    text_box(s, "Separate non-integrated economizer arrangement", 1.06, 4.94, 4.8, .33, size=10.5, color=MUTED)
    rect(s, 6.96, 1.90, 5.64, 3.85, WHITE, VIOLET, radius=True, line_width=1.3)
    text_box(s, "INTEGRATED", 7.30, 2.20, 4.9, .28, size=10, color=VIOLET, bold=True)
    text_box(s, "Primary–secondary plant with integrated economizer", 7.30, 2.63, 4.86, .62, size=19, color=NAVY, bold=True)
    add_arch_node(s, 7.29, 3.65, 1.18, .82, "Load", "400–600 kW", VIOLET)
    add_arch_node(s, 8.92, 3.65, 1.18, .82, "Plant", "candidate", VIOLET, inverted=True)
    add_arch_node(s, 10.55, 3.65, 1.18, .82, "Room", "return air", VIOLET)
    line(s, 8.47, 4.06, 8.92, 4.06, VIOLET, 1.4); line(s, 10.10, 4.06, 10.55, 4.06, VIOLET, 1.4)
    text_box(s, "Economizer integrated into the chilled-water path", 7.30, 4.94, 4.8, .33, size=10.5, color=MUTED)
    add_callout(s, "Validation tier: agreement with pinned upstream library behavior—not calibration against a physical data center.", 1.12, 6.08, 11.1, .55, fill=AMBER_BG, color=AMBER)

    # 20 pinned runtime
    s, n = new()
    add_title(s, n, "MODELS", "A simulation is only reproducible if its environment is named", "The manifest records exact solver, libraries, image, models, inputs, code state, and artifacts.", source="Source: data/runs/benchmark-bc0522c9/manifest.json")
    versions = [
        ("OpenModelica", "1.26.3", TEAL), ("Modelica Standard Library", "4.1.0", VIOLET),
        ("Buildings", "13.0.0", CYAN), ("Runtime image", "rcp-openmodelica-buildings", AMBER),
    ]
    for i, (name, value, col) in enumerate(versions):
        x = .72 + (i % 2) * 6.10
        y = 1.88 + (i // 2) * 1.55
        rect(s, x, y, 5.66, 1.22, WHITE, col, radius=True, line_width=1.2)
        text_box(s, name.upper(), x + .25, y + .20, 3.75, .26, size=8.8, color=col, bold=True)
        text_box(s, value, x + .25, y + .61, 5.06, .32, size=15.5, color=NAVY, bold=True, font=MONO)
    add_callout(s, "Reproducibility manifest also records the repository revision and dirty state—because uncommitted code is part of the environment.", .95, 5.21, 11.43, .76, fill=SKY, color=TEAL)
    text_box(s, "Artifacts are exported as a ZIP with SHA-256 fingerprints and byte counts.", 1.49, 6.23, 10.4, .34, size=14, color=NAVY, bold=True, align=PP_ALIGN.CENTER)

    # 21 section
    s, n = new()
    add_section_slide(s, n, "STUDY", "A preregistered 18-case Modelica benchmark", "The study asks whether integrating a primary–secondary waterside economizer improves energy or thermal performance across load and chilled-water setpoint.", ["18 cases", "9 matched pairs", "24 h each", "8 primary metrics"])

    # 22 design matrix
    s, n = new()
    add_title(s, n, "STUDY", "The design is a complete 3 × 3 matched comparison", "Every operating point runs the non-integrated baseline and integrated candidate under identical declared conditions.", source="Source: benchmark_plan() in src/rcp/simulation/batch.py")
    # matrix
    x0, y0, cw, ch = 2.25, 2.02, 2.15, 1.08
    for j, t in enumerate([6, 8, 10]):
        rect(s, x0 + j * cw, 1.55, cw - .08, .42, NAVY, NAVY, radius=True)
        text_box(s, f"{t} °C CHW", x0 + j * cw, 1.58, cw - .08, .28, size=10, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    for i, q in enumerate([400, 500, 600]):
        rect(s, .72, y0 + i * ch, 1.30, ch - .08, SOFT, SOFT, radius=True)
        text_box(s, f"{q} kW", .72, y0 + i * ch, 1.30, ch - .08, size=13, color=NAVY, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
        for j, t in enumerate([6, 8, 10]):
            rect(s, x0 + j * cw, y0 + i * ch, cw - .08, ch - .08, WHITE, LINE, radius=True)
            add_pill(s, "N", x0 + j * cw + .26, y0 + i * ch + .28, .54, fill=SKY, color=TEAL)
            text_box(s, "vs", x0 + j * cw + .90, y0 + i * ch + .29, .28, .25, size=8, color=GRAY, align=PP_ALIGN.CENTER)
            add_pill(s, "I", x0 + j * cw + 1.28, y0 + i * ch + .28, .54, fill=LAVENDER, color=VIOLET)
    add_kpi(s, 9.05, 1.72, 3.10, 1.22, "18", "simulation cases", accent=TEAL)
    add_kpi(s, 9.05, 3.16, 3.10, 1.22, "9", "matched pairs", accent=VIOLET)
    add_kpi(s, 9.05, 4.60, 3.10, 1.22, "1,440", "intervals per case", accent=AMBER)
    add_callout(s, "N = non-integrated baseline · I = integrated candidate", 2.25, 5.55, 6.37, .54, fill=WHITE, color=MUTED, border=LINE)

    # 23 metrics
    s, n = new()
    add_title(s, n, "STUDY", "The analysis protocol defines metrics before results are seen", "Primary metrics, directionality, units, plausibility ranges, and quality rules are part of the approved plan.", source="Protocol: chiller-benchmark-analysis-v2")
    metrics = [
        ("EHVAC", "HVAC energy", "kWh", "lower"), ("PUE", "Power usage effectiveness", "—", "lower"),
        ("Tpeak", "Peak room temperature", "°C", "lower"), ("Exceed.", "Degree-hours above 27 °C", "°C·h", "lower"),
        ("Free", "Free-cooling duration", "h", "context"), ("Partial", "Partial-mechanical duration", "h", "context"),
        ("Full", "Full-mechanical duration", "h", "context"), ("Switches", "Cooling-mode transitions", "count", "lower"),
    ]
    for i, (code, name, unit, direction) in enumerate(metrics):
        x = .68 + (i % 4) * 3.10
        y = 1.84 + (i // 4) * 2.02
        rect(s, x, y, 2.83, 1.62, WHITE, [TEAL, VIOLET, AMBER, CYAN][i % 4], radius=True, line_width=1.0)
        text_box(s, code, x + .22, y + .19, 1.05, .31, size=13, color=[TEAL, VIOLET, AMBER, CYAN][i % 4], bold=True)
        add_pill(s, direction, x + 1.65, y + .16, .90, fill=SOFT, color=MUTED, size=7.5)
        text_box(s, name, x + .22, y + .67, 2.35, .42, size=10.2, color=NAVY, bold=True)
        text_box(s, unit, x + .22, y + 1.25, 2.35, .19, size=8.5, color=GRAY, font=MONO)
    add_callout(s, "Protocol hash  " + short_hash(result["analysis_protocol_sha256"]), 3.34, 5.98, 6.65, .58, fill=NAVY, color=WHITE, border=NAVY)

    # 24 numerical safeguard
    s, n = new()
    add_title(s, n, "STUDY", "A numerical impulse exposed why safeguards matter", "OpenModelica trajectories contain isolated nonphysical mover-power events; raw cumulative energy is preserved, while the approved primary metric bridges screened samples.")
    add_picture_contain(s, ASSETS / "screening_fraction.png", .62, 1.75, 8.25, 4.78, border=WHITE)
    add_card(s, 9.17, 1.92, 3.44, 1.36, "Physical screen", "0 ≤ PHVAC ≤ 2 MW", accent=TEAL, body_size=12)
    add_card(s, 9.17, 3.53, 3.44, 1.36, "Repair rule", "Linear bridge internally; nearest valid value at a boundary.", accent=VIOLET, body_size=10.2)
    add_card(s, 9.17, 5.14, 3.44, 1.10, "Observed", "0.068–0.512% screened", accent=AMBER, body_size=10.5)
    text_box(s, "Raw upstream energy remains available as a diagnostic; it is never overwritten.", 8.95, 6.45, 3.85, .27, size=8.5, color=MUTED, align=PP_ALIGN.CENTER)

    # 25 quality gate
    s, n = new()
    add_title(s, n, "STUDY", "The study passes its preregistered quality gate—with one disclosed warning", "Quality checks test the study artifact before any conclusion is drafted.", source="Source: experiment_results.json quality_report")
    add_kpi(s, .72, 1.90, 2.82, 1.52, "18 / 18", "cases successful", accent=GREEN)
    add_kpi(s, 3.70, 1.90, 2.82, 1.52, "9 / 9", "matched pairs", accent=GREEN)
    add_kpi(s, 6.68, 1.90, 2.82, 1.52, "72 / 72", "comparisons", accent=GREEN)
    add_kpi(s, 9.66, 1.90, 2.82, 1.52, f"{q_pass}+{q_warn}", "passed + warning", accent=AMBER)
    checks = [
        "Primary metrics complete and finite",
        "Raw-series SHA-256 integrity verified",
        "PUE remains inside 1.0–3.0",
        "Cooling-mode time balances to 24 h",
        "IT energy is monotonic with load",
        "Power screening stays below 1% maximum",
    ]
    for i, item in enumerate(checks):
        x = .86 + (i % 2) * 6.05
        y = 3.84 + (i // 2) * .68
        color = AMBER if i == 5 else GREEN
        add_pill(s, "!" if i == 5 else "✓", x, y, .42, fill=(AMBER_BG if i == 5 else GREEN_BG), color=color)
        text_box(s, item, x + .58, y + .04, 5.10, .28, size=11.3, color=NAVY, bold=True)
    add_callout(s, "Quality-valid means the declared analysis is internally defensible—not that the physical model is calibrated.", 1.17, 6.14, 11.02, .54, fill=AMBER_BG, color=AMBER)

    # 26 trajectories
    s, n = new()
    add_title(s, n, "STUDY", "Metrics remain connected to the stored trajectories", "A reviewer can move from a result summary back to the screened power and room-temperature time series.")
    add_picture_contain(s, ASSETS / "representative_trajectories.png", .70, 1.71, 8.55, 4.95, border=WHITE)
    add_card(s, 9.54, 1.94, 3.05, 1.28, "Representative pair", "500 kW · 6 °C · 24 h", accent=TEAL, body_size=11)
    add_card(s, 9.54, 3.50, 3.05, 1.28, "Baseline", "Non-integrated plant", accent=GRAY, body_size=11)
    add_card(s, 9.54, 5.06, 3.05, 1.28, "Candidate", "Integrated plant", accent=VIOLET, body_size=11)

    # 27 section
    s, n = new()
    add_section_slide(s, n, "RESULTS", "The integrated configuration is not an energy winner", "Across all nine operating points it uses more screened HVAC energy. At 6 °C it also maintains a cooler peak room temperature—revealing a trade-off worth investigating.", ["+10.3% mean energy", "0 / 9 energy wins", "cooler at 6 °C", "0 thermal exceedance"])

    # 28 energy
    s, n = new()
    add_title(s, n, "RESULTS", "Integrated HVAC energy increases in every matched pair", "The increase ranges from +2.9% to +18.4%; mean change is +10.3%.", source="Source: benchmark revision " + short_hash(result["analysis_revision_id"]))
    add_picture_contain(s, ASSETS / "energy_delta_heatmap.png", .66, 1.75, 8.10, 4.87, border=WHITE)
    add_kpi(s, 9.15, 1.95, 3.18, 1.36, f"+{np.mean(e_deltas):.1f}%", "mean HVAC energy", accent=RED)
    add_kpi(s, 9.15, 3.55, 3.18, 1.36, "0 / 9", "candidate energy wins", accent=RED)
    add_kpi(s, 9.15, 5.15, 3.18, 1.36, f"+{min(e_deltas):.1f}–{max(e_deltas):.1f}%", "observed range", accent=AMBER)

    # 29 thermal
    s, n = new()
    add_title(s, n, "RESULTS", "The thermal benefit appears only at the lowest setpoint", "At 6 °C, integration lowers peak room temperature by 0.243–0.869 °C; at 8–10 °C the effect is negligible or slightly adverse.")
    add_picture_contain(s, ASSETS / "temperature_delta_heatmap.png", .66, 1.75, 8.10, 4.87, border=WHITE)
    add_kpi(s, 9.15, 1.95, 3.18, 1.36, f"{min(t6_abs):.3f} °C", "largest peak reduction", accent=GREEN)
    add_kpi(s, 9.15, 3.55, 3.18, 1.36, "0 °C·h", "exceedance above 27 °C", accent=GREEN)
    add_kpi(s, 9.15, 5.15, 3.18, 1.36, "+0.105 °C", "largest slight worsening", accent=AMBER)

    # 30 mode allocation
    s, n = new()
    add_title(s, n, "RESULTS", "Integration changes operating mode—not simply efficiency", "At 500 kW and 6 °C, full-mechanical hours disappear, but partial-mechanical operation expands to 16.8 hours.")
    add_picture_contain(s, ASSETS / "mode_allocation.png", .70, 1.80, 8.16, 4.58, border=WHITE)
    add_card(s, 9.20, 1.98, 3.16, 1.28, "Baseline", "17.1 h free + 6.9 h full", accent=TEAL, body_size=10.5)
    add_card(s, 9.20, 3.52, 3.16, 1.28, "Integrated", "7.2 h free + 16.8 h partial", accent=VIOLET, body_size=10.5)
    add_card(s, 9.20, 5.06, 3.16, 1.28, "Both", "4 mode switches", accent=AMBER, body_size=10.5)

    # 31 trade-off
    s, n = new()
    add_title(s, n, "RESULTS", "The correct conclusion is conditional—not ‘integrated is better’", "The data suggest an energy–thermal-margin trade-off at 6 °C and no energy advantage elsewhere.")
    add_picture_contain(s, ASSETS / "tradeoff_map.png", .68, 1.76, 8.18, 4.82, border=WHITE)
    add_callout(s, "Supported", 9.25, 1.96, 2.94, .52, fill=GREEN_BG, color=GREEN)
    text_box(s, "Integration can reduce peak temperature at 6 °C, with higher HVAC energy.", 9.23, 2.65, 3.00, .78, size=12, color=NAVY, bold=True)
    add_callout(s, "Not supported", 9.25, 3.72, 2.94, .52, fill=RED_BG, color=RED)
    text_box(s, "Integration minimizes energy across the evaluated domain.", 9.23, 4.41, 3.00, .68, size=12, color=NAVY, bold=True)
    add_callout(s, "Next question", 9.25, 5.38, 2.94, .52, fill=AMBER_BG, color=AMBER)
    text_box(s, "What control objective values thermal margin enough to justify the cost?", 9.23, 6.04, 3.00, .57, size=10.5, color=NAVY, bold=True)

    # 32 provenance chain
    s, n = new()
    add_title(s, n, "RESULTS", "Every conclusion can be traced back to a sealed chain", "The same chain supports review, reanalysis, and export without trusting the narrative layer.")
    chain = [
        ("Approved plan", short_hash(result["experiment_plan_sha256"]), VIOLET),
        ("Analysis protocol", short_hash(result["analysis_protocol_sha256"]), TEAL),
        ("Execution specs", "18 case hashes", CYAN),
        ("Raw results", short_hash(result["raw_dataset_sha256"]), AMBER),
        ("Analysis revision", short_hash(result["analysis_revision_id"]), GREEN),
        ("Claim", "comparison + case + paper IDs", RED),
    ]
    for i, (title, body, col) in enumerate(chain):
        x = .58 + i * 2.08
        add_arch_node(s, x, 2.25, 1.73, 1.40, title, body, col, inverted=(i in (0, 5)))
        if i < len(chain) - 1:
            line(s, x + 1.73, 2.95, x + 2.02, 2.95, GRAY, 1.3)
    add_card(s, .83, 4.55, 3.70, 1.25, "Tamper evidence", "Raw files are checked against recorded SHA-256 fingerprints before analysis.", accent=AMBER, body_size=9.8)
    add_card(s, 4.82, 4.55, 3.70, 1.25, "Append-only analysis", "A protocol change creates a new revision; the previous result is retained.", accent=VIOLET, body_size=9.8)
    add_card(s, 8.81, 4.55, 3.70, 1.25, "Claim links", "Draft statements cite comparison, case, and supporting-paper identifiers.", accent=TEAL, body_size=9.8)
    add_callout(s, "The report is a view over evidence—not the evidence itself.", 2.57, 6.12, 8.20, .52, fill=NAVY, color=WHITE, border=NAVY)

    # 33 analysis revision
    s, n = new()
    add_title(s, n, "RESULTS", "Reanalysis is versioned instead of silently replacing history", "The benchmark currently has two stored analysis revisions; the newest records that the protocol changed.")
    rect(s, .88, 2.08, 4.94, 2.62, WHITE, GRAY, radius=True, line_width=1.2)
    add_pill(s, "REVISION 01", 1.22, 2.39, 1.28, fill=SOFT, color=MUTED)
    text_box(s, "f906…ec70f", 1.22, 3.04, 3.85, .40, size=18, color=NAVY, bold=True, font=MONO)
    text_box(s, "Retained as historical analysis", 1.22, 3.72, 3.85, .28, size=10.5, color=MUTED)
    line(s, 5.82, 3.39, 7.20, 3.39, VIOLET, 2.0)
    text_box(s, "protocol change", 5.91, 2.90, 1.20, .26, size=8.5, color=VIOLET, bold=True, align=PP_ALIGN.CENTER)
    rect(s, 7.20, 2.08, 5.14, 2.62, WHITE, GREEN, radius=True, line_width=1.4)
    add_pill(s, "CURRENT", 7.55, 2.39, 1.14, fill=GREEN_BG, color=GREEN)
    text_box(s, short_hash(result["analysis_revision_id"]), 7.55, 3.04, 4.15, .40, size=18, color=NAVY, bold=True, font=MONO)
    text_box(s, "Metrics recomputed from stored raw series", 7.55, 3.72, 4.15, .28, size=10.5, color=MUTED)
    add_callout(s, "Result: methodological improvement without erasing the record that supported earlier outputs.", 1.30, 5.42, 10.70, .78, fill=LAVENDER, color=VIOLET)

    # 34 product section / UI
    s, n = new()
    add_title(s, n, "PRODUCT", "The interface is designed around reviewable research state", "Light and dark themes, keyboard-visible controls, responsive layouts, URL-addressable views, and explicit lifecycle actions are now implemented.")
    add_picture_crop(s, UI / "dashboard_light.png", .65, 1.80, 5.94, 2.70, border=LINE, radius=True)
    add_picture_crop(s, UI / "run_detail_light.png", 6.74, 1.80, 5.94, 2.70, border=LINE, radius=True)
    text_box(s, "RUN PORTFOLIO", .68, 4.66, 2.2, .24, size=8.8, color=TEAL, bold=True)
    text_box(s, "RUN COCKPIT", 6.78, 4.66, 2.2, .24, size=8.8, color=TEAL, bold=True)
    add_card(s, .65, 5.10, 3.78, 1.18, "Status at a glance", "Active, attention, completed, and failed runs remain visible.", accent=TEAL, body_size=9.2)
    add_card(s, 4.78, 5.10, 3.78, 1.18, "Lifecycle navigation", "Stages, gates, tabs, claims, and artifacts are one click away.", accent=VIOLET, body_size=9.2)
    add_card(s, 8.91, 5.10, 3.78, 1.18, "Safe operations", "Archive and retry update the same view after the backend succeeds.", accent=AMBER, body_size=9.2)

    # 35 UI research + models
    s, n = new()
    add_title(s, n, "PRODUCT", "Researchers can move from profile to literature to simulation", "The UI exposes the same boundaries as the scientific workflow rather than hiding them behind a chat box.")
    add_picture_crop(s, UI / "runs_new_light.png", .62, 1.75, 3.92, 3.65, border=LINE, radius=True)
    add_picture_crop(s, UI / "knowledge_light.png", 4.71, 1.75, 3.92, 3.65, border=LINE, radius=True)
    add_picture_crop(s, UI / "models_light.png", 8.80, 1.75, 3.92, 3.65, border=LINE, radius=True)
    for x, title, body, col in [
        (.62, "01 · Frame", "Research profile + constraints", TEAL),
        (4.71, "02 · Ground", "Credibility-aware PaperCards", VIOLET),
        (8.80, "03 · Explore", "Bounded model quick simulation", AMBER),
    ]:
        text_box(s, title, x + .08, 5.62, 3.74, .28, size=10.5, color=col, bold=True)
        text_box(s, body, x + .08, 6.04, 3.74, .30, size=9.5, color=MUTED)

    # 36 remote access / deployment
    s, n = new()
    add_title(
        s, n, "PRODUCT",
        "Reviewers reach the platform over an authenticated link",
        "One supervised process on loopback, an outbound TLS tunnel, and HTTP Basic auth covering the API, the SPA, and the live run stream alike.",
        source="Source: docs/DEPLOYMENT.md · deploy/rcp.service · src/rcp/api/auth.py",
    )
    hops = [
        ("Reviewer\nbrowser", "nothing to install", TEAL, False),
        ("Tailscale\nFunnel", "public TLS · 443", CYAN, False),
        ("Basic auth\ngate", "ASGI middleware", VIOLET, True),
        ("Supervised\nrcp serve", "127.0.0.1 · systemd", TEAL, False),
        ("Run\nmanager", "one worker · Docker", CYAN, False),
    ]
    for i, (label, sub, col, inverted) in enumerate(hops):
        x = .63 + i * 2.49
        add_arch_node(s, x, 1.86, 2.05, 1.10, label, sub, col, inverted=inverted)
        if i < len(hops) - 1:
            line(s, x + 2.06, 2.41, x + 2.40, 2.41, col, 1.6)
    add_card(s, .70, 3.24, 3.85, 1.58, "Fail closed by default",
             "`rcp serve` will not start without a password, will not accept one under 16 characters, and will not disable auth on a non-loopback host.",
             accent=TEAL, body_size=10.2)
    add_card(s, 4.74, 3.24, 3.85, 1.58, "Nothing streamed was broken",
             "A pass-through gate, not a response wrapper: run events keep flowing (with a 15 s keepalive for proxy idle timeouts) and PDF range requests still return 206.",
             accent=CYAN, body_size=10.2)
    add_card(s, 8.78, 3.24, 3.85, 1.58, "Supervised, single worker",
             "A systemd unit with a 120 s stop timeout for the 1200 s simulation call. Live run state is in-process, so a worker count is structurally refused.",
             accent=VIOLET, body_size=10.2)
    add_card(s, .70, 5.00, 5.86, 1.42, "What it protects",
             "Anonymous access to the API, the interface, the event stream, and the schema — the interactive docs are withdrawn whenever auth is on.",
             accent=GREEN, body_size=10.2)
    add_card(s, 6.87, 5.00, 5.86, 1.42, "What it is not",
             "One shared credential identifies nobody, rate-limits nothing, and caps no spend. The Funnel hostname is published to Certificate Transparency logs.",
             accent=RED, body_size=10.2)
    add_callout(s, "The credential is transport protection, not evidence of who did what—so exposure stays temporary and `reviewer_id` stays self-declared.", .70, 6.58, 12.03, .48, fill=AMBER_BG, color=AMBER)

    # 37 evaluation
    s, n = new()
    add_title(s, n, "PRODUCT", "Evaluation separates software correctness from scientific validity", "Passing tests proves the platform behaves as declared; it does not prove a model represents a facility.", source="Source: docs/EVALUATION.md")
    add_card(s, .69, 1.90, 3.75, 3.67, "Automated verification", "Backend tests\nFrontend interaction tests\nProduction build\nEnvironment doctor\nModel validation checks\nRaw integrity + study quality", accent=TEAL, icon="A", body_size=11.4)
    add_card(s, 4.79, 1.90, 3.75, 3.67, "Numerical regression", "Pinned upstream trajectories\nNormalized RMSE threshold ≤ 0.5%\nBenchmark repeatability\nMetric completeness\nPhysical plausibility screens", accent=VIOLET, icon="N", body_size=11.4)
    add_card(s, 8.89, 1.90, 3.75, 3.67, "Manual blind review", "Traceability\nMissing-evidence visibility\nPreregistration\nReproducibility\nCalibration disclosure\nVerification time", accent=AMBER, icon="H", body_size=11.4)
    add_callout(s, "Manual review uses at least two reviewers and never collapses into a single ‘scientific validity score.’", 1.03, 5.94, 11.28, .64, fill=AMBER_BG, color=AMBER)

    # 38 readiness
    s, n = new()
    add_title(s, n, "PRODUCT", "Current state: a tested research prototype with a credible benchmark", "The platform is ready for guided research use and PI scrutiny—not unsupervised scientific deployment.")
    add_kpi(s, .72, 1.91, 2.77, 1.42, "174", "backend tests passed", accent=GREEN)
    add_kpi(s, 3.70, 1.91, 2.77, 1.42, "60", "frontend tests passed", accent=GREEN)
    add_kpi(s, 6.68, 1.91, 2.77, 1.42, "7 / 7", "conceptual model checks", accent=GREEN)
    add_kpi(s, 9.66, 1.91, 2.77, 1.42, "valid", "18-case study quality", accent=GREEN)
    add_card(s, .72, 3.77, 3.77, 1.68, "Strong today", "Auditable workflow, bounded registry, pinned runtime, evidence hashes, revisioned analysis, coherent UI, and a supervised authenticated deployment.", accent=TEAL, body_size=10.7)
    add_card(s, 4.78, 3.77, 3.77, 1.68, "Needs research work", "Facility calibration, uncertainty quantification, broader scenarios, and independent replication.", accent=AMBER, body_size=10.7)
    add_card(s, 8.84, 3.77, 3.77, 1.68, "Needs product work", "Per-reviewer identity, rate limiting and spend caps, multi-user provenance, long-running job infrastructure, and observability.", accent=VIOLET, body_size=10.7)
    add_callout(s, "Readiness claim: strong prototype for supervised, reproducible computational studies.", 1.47, 5.91, 10.39, .68, fill=SKY, color=TEAL)

    # 39 limitations
    s, n = new()
    add_title(s, n, "NEXT", "The largest risks are scientific, not cosmetic", "Each risk has a concrete mitigation path; none should be hidden by a polished interface.")
    risks = [
        ("Calibration gap", "Library regression is not facility validation.", "Acquire measured plant data; calibrate and hold out validation periods.", RED),
        ("Scenario narrowness", "One dry-cold weather profile and a 3 × 3 operating matrix.", "Add climates, seasons, load profiles, faults, and control variants.", AMBER),
        ("LLM dependence", "Hypothesis quality varies with model and retrieval coverage.", "Benchmark prompts/models; capture uncertainty; retain human selection.", VIOLET),
        ("Numerical events", "Isolated mover-power impulses require a declared screen.", "Investigate upstream dynamics and compare alternate solvers/tolerances.", TEAL),
    ]
    for i, (risk, evidence, mitigation, col) in enumerate(risks):
        y = 1.79 + i * 1.16
        rect(s, .70, y, 12.0, .94, WHITE, LINE, radius=True)
        rect(s, .70, y, .09, .94, col, col)
        text_box(s, risk, .98, y + .18, 2.0, .28, size=12.5, color=NAVY, bold=True)
        text_box(s, evidence, 3.08, y + .15, 3.92, .50, size=9.6, color=MUTED)
        add_pill(s, "MITIGATION", 7.22, y + .17, 1.12, fill=SOFT, color=col, size=7.3)
        text_box(s, mitigation, 8.54, y + .15, 3.84, .50, size=9.6, color=INK, bold=True)
    add_callout(s, "The platform makes these limitations easier to see; resolving them remains research work.", 1.42, 6.39, 10.47, .38, fill=NAVY, color=WHITE, border=NAVY)

    # 40 roadmap
    s, n = new()
    add_title(s, n, "NEXT", "The next phase should deepen evidence before broadening automation", "A staged roadmap keeps scientific credibility ahead of product surface area.")
    phases = [
        ("0–3 months", "VALIDATE", "Replicate benchmark\nInvestigate power impulses\nAdd uncertainty bands\nDefine calibration dataset", TEAL),
        ("3–6 months", "GENERALIZE", "New weather profiles\nDynamic load traces\nControl variants\nCross-solver comparison", VIOLET),
        ("6–12 months", "TRANSLATE", "Facility calibration\nProspective case study\nIndependent reviewer study\nOperational deployment plan", AMBER),
    ]
    for i, (time, phase, body, col) in enumerate(phases):
        x = .70 + i * 4.15
        rect(s, x, 1.88, 3.77, 3.85, WHITE, col, radius=True, line_width=1.3)
        add_pill(s, time, x + .28, 2.16, 1.30, fill=SOFT, color=col)
        text_box(s, phase, x + .28, 2.83, 3.10, .35, size=18, color=NAVY, bold=True)
        line(s, x + .28, 3.35, x + 3.39, 3.35, LINE, .9)
        text_box(s, body, x + .28, 3.69, 3.05, 1.58, size=12.2, color=MUTED)
    add_callout(s, "Decision rule: do not add a new autonomous step until its inputs, outputs, failure modes, and review point are explicit.", 1.05, 6.14, 11.23, .59, fill=SKY, color=TEAL)

    # 41 PI decisions / closing
    s, n = new()
    add_bg(s, DARK_BG)
    rect(s, 0, 0, W, H, DARK_BG, DARK_BG)
    text_box(s, "PI DISCUSSION", .72, .60, 3.0, .25, size=9.5, color=CYAN, bold=True)
    text_box(s, "Three decisions unlock the next research phase", .72, 1.15, 10.9, .75, size=32, color=WHITE, bold=True)
    decisions = [
        ("01", "Scientific target", "Optimize energy only—or formalize a weighted energy / thermal-margin objective?"),
        ("02", "Validation access", "Which facility data, collaborator, or measured benchmark can anchor calibration?"),
        ("03", "Evaluation design", "Which users and reviewers should test traceability and verification-time gains?"),
    ]
    for i, (code, title, body) in enumerate(decisions):
        x = .72 + i * 4.17
        rect(s, x, 2.43, 3.74, 2.60, "172735", "345061", radius=True, line_width=1.0)
        text_box(s, code, x + .25, 2.72, .55, .30, size=10, color=CYAN, bold=True)
        text_box(s, title, x + .25, 3.18, 3.10, .35, size=17, color=WHITE, bold=True)
        text_box(s, body, x + .25, 3.78, 3.10, .82, size=11.3, color="BED0DA")
    line(s, .72, 5.62, 12.54, 5.62, "395264", 1.0)
    text_box(s, "Take-away", .72, 5.98, 1.15, .25, size=9, color=CYAN, bold=True)
    text_box(s, "RCP can make simulation research faster and more reviewable—provided the model, protocol, and human judgment remain first-class evidence.", 2.00, 5.88, 10.0, .74, size=16.5, color=WHITE, bold=True)
    text_box(s, f"RCP.2026/11  ·  {DECK_DATE}", .72, 6.96, 3.3, .20, size=7.5, color="78909E", bold=True)
    text_box(s, f"{n:02d}", 12.15, 6.95, .6, .22, size=8, color="78909E", bold=True, align=PP_ALIGN.RIGHT)

    assert slide_no == 41, slide_no
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return prs


def validate_deck(path: Path, expected_slides: int = 41):
    prs = Presentation(path)
    assert len(prs.slides) == expected_slides, len(prs.slides)
    assert prs.slide_width == Inches(W)
    assert prs.slide_height == Inches(H)
    empty = []
    for idx, slide in enumerate(prs.slides, 1):
        strings = [shape.text.strip() for shape in slide.shapes if hasattr(shape, "text_frame") and shape.text.strip()]
        if not strings:
            empty.append(idx)
    assert not empty, f"Slides without text: {empty}"
    return len(prs.slides), path.stat().st_size


def main():
    result, manifest = load_benchmark()
    generate_charts(result)
    build_deck(result, manifest)
    count, size = validate_deck(OUT)
    print(f"Created {OUT.relative_to(ROOT)} · {count} slides · {size / 1024 / 1024:.2f} MiB")


if __name__ == "__main__":
    main()
