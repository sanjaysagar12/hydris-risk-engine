"""ReportDocument -> PDF bytes (ReportLab platypus, A4, DejaVu Sans so en dashes and symbols render on every platform)."""
from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from hydris_report.models import FactoryReport, ReportDocument, RiskBlock

FONT_DIR = Path(__file__).parent / "assets" / "fonts"
REG, BOLD = "DejaVuSans", "DejaVuSans-Bold"
MARGIN = 18 * mm
CONTENT_W = A4[0] - 2 * MARGIN

# status -> (background, text). Colour is only a secondary cue: the status word is always printed.
STATUS_COLORS = {
    "present": ("#b42318", "#ffffff"), "watch": ("#fdb022", "#1d2939"), "not_present": ("#067647", "#ffffff"),
    "not_applicable": ("#667085", "#ffffff"), "no_data": ("#eaecf0", "#1d2939"), "error": ("#6941c6", "#ffffff"),
}
INK, MUTED, RULE, PANEL = "#1d2939", "#667085", "#d0d5dd", "#f9fafb"


def _fonts() -> None:
    if REG in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont(REG, str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(BOLD, str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(REG, normal=REG, bold=BOLD, italic=REG, boldItalic=BOLD)


def _styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName=REG, textColor=colors.HexColor(INK))
    return {
        "body": ParagraphStyle("body", fontSize=8.6, leading=12, spaceAfter=3, **base),
        "small": ParagraphStyle("small", fontSize=7.4, leading=10, textColor=colors.HexColor(MUTED), fontName=REG, spaceAfter=2),
        "label": ParagraphStyle("label", fontName=BOLD, fontSize=7.2, leading=10, textColor=colors.HexColor(MUTED), spaceBefore=4,
                                spaceAfter=1, keepWithNext=1),
        "title": ParagraphStyle("title", fontName=BOLD, fontSize=26, leading=31, textColor=colors.HexColor(INK), spaceAfter=6),
        "subtitle": ParagraphStyle("subtitle", fontName=REG, fontSize=13, leading=18, textColor=colors.HexColor(MUTED), spaceAfter=14),
        "h1": ParagraphStyle("h1", fontName=BOLD, fontSize=17, leading=21, textColor=colors.HexColor(INK), spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=12, leading=15, textColor=colors.HexColor("#175cd3"), spaceBefore=10,
                             spaceAfter=4),
        "risk": ParagraphStyle("risk", fontName=BOLD, fontSize=10.5, leading=15, textColor=colors.HexColor(INK), spaceBefore=6),
        "cell": ParagraphStyle("cell", fontName=REG, fontSize=7.4, leading=9.4, textColor=colors.HexColor(INK)),
        "cellc": ParagraphStyle("cellc", fontName=REG, fontSize=7.4, leading=14, alignment=1, textColor=colors.HexColor(INK)),
        "cellb": ParagraphStyle("cellb", fontName=BOLD, fontSize=7.4, leading=9.4, textColor=colors.HexColor(INK)),
        "bullet": ParagraphStyle("bullet", fontName=REG, fontSize=8, leading=11, leftIndent=9, bulletIndent=0,
                                 textColor=colors.HexColor(INK), spaceAfter=1.5),
        "toc": ParagraphStyle("toc", fontName=REG, fontSize=10, leading=15, textColor=colors.HexColor(INK)),
    }


def esc(text: object) -> str:
    return escape(str(text))


def pill(word: str, status: str, size: float = 8) -> str:
    bg, fg = STATUS_COLORS[status]
    return f'<font name="{BOLD}" size="{size}" backColor="{bg}" color="{fg}">&nbsp;{esc(word)}&nbsp;</font>'


def tag(text: str) -> str:
    return f'<font size="6.8" backColor="#eaecf0" color="#344054">&nbsp;{esc(text)}&nbsp;</font>'


class Heading(Paragraph):
    """A heading that can feed the table of contents and the running header."""

    def __init__(self, text: str, style: ParagraphStyle, toc: bool = False, section: str | None = None):
        super().__init__(esc(text), style)
        self.plain, self.toc, self.section = text, toc, section


class _NumberedCanvas(rl_canvas.Canvas):
    """Draws the running header and 'Page x of y' footer once the page count is known."""

    def __init__(self, *args, owner: _Doc, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner, self._states = owner, []

    def showPage(self) -> None:
        self._states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._states)
        for state in self._states:
            self.__dict__.update(state)
            self._decorate(self._pageNumber, total)
            super().showPage()
        super().save()

    def _decorate(self, page: int, total: int) -> None:
        if page == 1:  # cover
            return
        w, h = self._pagesize
        d = self._owner.report
        self.setStrokeColor(colors.HexColor(RULE))
        self.setLineWidth(0.5)
        self.line(MARGIN, h - 12 * mm, w - MARGIN, h - 12 * mm)
        self.line(MARGIN, 13 * mm, w - MARGIN, 13 * mm)
        self.setFillColor(colors.HexColor(MUTED))
        self.setFont(REG, 7.5)
        section = self._owner.page_section.get(page, "")
        self.drawString(MARGIN, h - 10 * mm, d.title + (f"  ·  {section}" if section else ""))
        self.drawRightString(w - MARGIN, 8.6 * mm, f"Page {page} of {total}")
        self.setFont(REG, 6.8)
        self.drawString(MARGIN, 8.6 * mm, f"Generated {d.generated_at.day} {d.generated_at:%B %Y}  ·  {d.disclaimer}")


class _Doc(BaseDocTemplate):
    def __init__(self, buf: io.BytesIO, report: ReportDocument):
        super().__init__(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=17 * mm, bottomMargin=19 * mm,
                         title=f"{report.title}: {report.subtitle}", author="Hydris", subject=report.subtitle, invariant=1)
        self.report, self.page_section, self._section = report, {}, ""
        pw, ph = A4
        lw, lh = landscape(A4)
        self.addPageTemplates([
            PageTemplate(id="portrait", pagesize=A4, frames=[Frame(MARGIN, 19 * mm, pw - 2 * MARGIN, ph - 36 * mm, id="p",
                                                                    leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]),
            PageTemplate(id="landscape", pagesize=landscape(A4), frames=[Frame(MARGIN, 19 * mm, lw - 2 * MARGIN, lh - 36 * mm,
                                                                               id="l", leftPadding=0, rightPadding=0, topPadding=0,
                                                                               bottomPadding=0)]),
        ])

    def afterFlowable(self, flowable) -> None:
        if isinstance(flowable, Heading):
            if flowable.toc:
                self.notify("TOCEntry", (0, flowable.plain, self.page))
            if flowable.section is not None:
                self._section = flowable.section

    def afterPage(self) -> None:
        self.page_section[self.page] = self._section


# ---- building blocks ---------------------------------------------------------------------------------------------
def _grid(rows: list[tuple[str, str]], st: dict, widths: list[float], per_row: int = 2) -> Table | None:
    """Label/value pairs laid out `per_row` pairs per row; None when there is nothing to show."""
    rows = [(k, v) for k, v in rows if v not in (None, "")]
    if not rows:
        return None
    data = []
    for i in range(0, len(rows), per_row):
        line: list[Paragraph] = []
        for k, v in rows[i:i + per_row]:
            line += [Paragraph(esc(k), st["small"]), Paragraph(esc(v), st["cell"])]
        line += [Paragraph("", st["cell"])] * (2 * per_row - len(line))
        data.append(line)
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#eaecf0")),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _callout(text: str, st: dict, bg: str, border: str, width: float = CONTENT_W) -> Table:
    t = Table([[Paragraph(esc(text), st["body"])]], colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)), ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(border)),
                           ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _image(png: bytes, width: float) -> Image:
    reader = ImageReader(io.BytesIO(png))  # one reader per chart: the pixels are decoded once, not once per layout pass
    w, h = reader.getSize()
    img = Image(io.BytesIO(png), width=width, height=width * h / w)
    img._img = reader  # draw() prefers this shared reader, so every layout pass reuses the decoded pixels
    return img


def _bullets(items: list[str], st: dict) -> list[Paragraph]:
    return [Paragraph(esc(t), st["bullet"], bulletText="•") for t in items]


def risk_block(b: RiskBlock, st: dict, chart_png: bytes | None = None, lead: list | None = None) -> list:
    """One risk as flowables. Only title + why + position are kept together; charts and tables may split across pages.
    Compact blocks (not present, no data, error) leave out the outlook, chart and values table. Empty parts are omitted."""
    tags = [tag(b.scale), tag(f"Aqueduct {b.vintage}")]
    if b.kind == "impact":
        tags.append(tag("Downstream impact"))
    out: list = [*(lead or []), Paragraph(f"{esc(b.risk_name)} &nbsp;{pill(b.status_word, b.status.value)} &nbsp;{' '.join(tags)}", st["risk"]),
                 Paragraph(esc(b.headline), st["small"])]

    def part(label: str, text: str | None) -> None:
        if text:
            out.extend([Paragraph(label.upper(), st["label"]), Paragraph(esc(text), st["body"])])

    part("Why this status", b.why)
    part("Where it sits against the thresholds", b.threshold_position)
    head, out = out, []
    part("What would change the status", b.what_would_change)
    if b.extra_notes:
        out.append(Paragraph("NOTES", st["label"]))
        out.extend(_bullets(b.extra_notes, st))
    full = b.detail == "full"
    if full and (b.outlook_sentence or b.outlook_table):
        out.append(Paragraph("OUTLOOK", st["label"]))
        if b.outlook_sentence:
            out.append(Paragraph(esc(b.outlook_sentence), st["body"]))
        if b.outlook_table:
            data = [[Paragraph(h, st["cellb"]) for h in ("Scenario", "Today", "2030", "2050", "2080")]]
            data += [[Paragraph(esc(r["scenario"]), st["cell"])] + [Paragraph(esc(r.get(k, "")), st["cell"])
                                                                   for k in ("today", "2030", "2050", "2080")]
                     for r in b.outlook_table]
            t = Table(data, colWidths=[62 * mm] + [22 * mm] * 4, hAlign="LEFT")
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f7")), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(RULE)),
                                   ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
            out.append(t)
    if full and (chart_png or b.monthly_chart_png):
        out.append(Paragraph("OVERALL BREAKDOWN" if chart_png else "SEASONAL PATTERN", st["label"]))
        out.append(_image(chart_png or b.monthly_chart_png, 130 * mm))
    v = b.values
    values = None if not full else _grid([  # basin ids, source and vintage are in the header, tags and appendix
        ("Value", v.raw_display or ""), ("Raw value", f"{v.raw:.6g}" if v.raw is not None else ""), ("Unit", v.unit or ""),
        ("Score (0-5)", f"{v.score:.2f}" if v.score is not None else ""), ("Category", str(v.category) if v.category is not None else ""),
        ("Aqueduct label", v.label or ""),
    ], st, [15 * mm, 38 * mm, 18 * mm, 28 * mm, 22 * mm, 38 * mm], per_row=3)
    if values is not None:
        out.extend([Paragraph("VALUES", st["label"]), values])
    if b.caveats:
        out.append(Paragraph("CAVEATS", st["label"]))
        out.extend(_bullets(b.caveats, st))
    out.append(Spacer(1, 2.5 * mm))
    return [KeepTogether(head), *out]


def _status_cell_style(rows: list[str], col: int, first_row: int) -> list[tuple]:
    cmds = []
    for i, status in enumerate(rows, start=first_row):
        bg, fg = STATUS_COLORS[status]
        cmds += [("BACKGROUND", (col, i), (col, i), colors.HexColor(bg)), ("TEXTCOLOR", (col, i), (col, i), colors.HexColor(fg))]
    return cmds


def _status_para(word: str, status: str, st: dict, style: ParagraphStyle | None = None) -> Paragraph:
    return Paragraph(f'<font name="{BOLD}" color="{STATUS_COLORS[status][1]}">{esc(word)}</font>', style or st["cell"])


def _factory_story(fr: FactoryReport, st: dict) -> list:
    h = fr.context_header
    story: list = [PageBreak(), Heading(h["name"], st["h1"], toc=True, section=h["name"])]
    coords = f"{h['lat']:.4f}, {h['lon']:.4f}"
    place = ", ".join(x for x in (h.get("state"), h.get("country")) if x)
    match = h["match_method"] + (f" ({h['snap_distance_km']:.1f} km)" if h.get("snap_distance_km") is not None else "")
    story.append(_grid([("Site ID", h["site_id"]), ("Coordinates", coords), ("Sub-basin (pfaf_id)", str(h.get("pfaf_id", ""))),
                        ("String ID", h.get("string_id", "")), ("State / country", place), ("Match method", match)],
                       st, [26 * mm, 52 * mm, 30 * mm, 66 * mm]))
    if h.get("match_warning"):
        story += [Spacer(1, 2 * mm), _callout("Warning: " + h["match_warning"], st, "#fef0c7", "#fdb022")]
    if fr.location_caveats:
        story += [Spacer(1, 1.5 * mm), *_bullets(fr.location_caveats, st)]

    story.append(Paragraph("At a glance", st["h2"]))
    order = [("present", "Present"), ("watch", "Watch"), ("not_present", "Not present"), ("no_data", "No data"), ("error", "Error")]
    head = [_status_para(word, key, st, st["cellc"]) for key, word in order]
    nums = [Paragraph(f'<font name="{BOLD}" size="13">{fr.counts.get(key, 0)}</font>', st["cellc"]) for key, _ in order]
    t = Table([head, nums], colWidths=[CONTENT_W / 5] * 5)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(RULE)), ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor(RULE)),
                           ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           *[("BACKGROUND", (i, 0), (i, 0), colors.HexColor(STATUS_COLORS[k][0])) for i, (k, _) in enumerate(order)]]))
    story += [t, Paragraph("Risk counts exclude the overall textile score and the downstream-impact indicator.", st["small"]),
              Spacer(1, 1.5 * mm), Paragraph(esc(fr.at_a_glance), st["body"])]

    story.append(Paragraph("Risk summary", st["h2"]))
    cols = [36 * mm, 24 * mm, 19 * mm, 22 * mm, 31 * mm, 42 * mm]
    data = [[Paragraph(x, st["cellb"]) for x in ("Risk", "Group", "Scale", "Status", "Value", "Aqueduct label")]]
    for r in fr.summary_rows:
        data.append([Paragraph(esc(r["risk"]), st["cell"]), Paragraph(esc(r["group"]), st["cell"]), Paragraph(esc(r["scale"]), st["cell"]),
                     _status_para(r["status_word"], r["status"], st), Paragraph(esc(r["value"]), st["cell"]),
                     Paragraph(esc(r["label"]), st["cell"])])
    t = Table(data, colWidths=cols, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f7")), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(RULE)),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                           *_status_cell_style([r["status"] for r in fr.summary_rows], 3, 1)]))
    story.append(t)

    story += risk_block(fr.overall, st, chart_png=fr.overall_chart_png, lead=[Paragraph("Overall textile risk", st["h2"])])
    sections = [("Risks present", fr.present, None), ("Risks on watch", fr.watch, None),
                ("Risks not present", fr.not_present, fr.not_present_framing), ("No data or errors", fr.no_data, None),
                ("Downstream impact", fr.impact, fr.impact_intro)]
    for title, blocks, intro in sections:
        if not blocks:
            continue  # no empty headings
        lead = [Paragraph(f"{esc(title)} ({len(blocks)})", st["h2"])]  # kept on the page with the section's first block
        if intro:
            lead.append(_callout(intro, st, "#eff8ff", "#b2ddff"))
            lead.append(Spacer(1, 2 * mm))
        story += risk_block(blocks[0], st, lead=lead)
        for b in blocks[1:]:
            story += risk_block(b, st)
    return story


def _portfolio_story(doc: ReportDocument, st: dict) -> list:
    p = doc.portfolio
    story: list = [PageBreak(), Heading("Portfolio summary", st["h1"], toc=True, section="Portfolio summary")]
    k = p.kpis
    cells = [("Factories", str(k["factories"])), ("With at least 1 Present risk", str(k["with_present"])),
             ("Most common local risk", f"{k['most_common_local']} ({k['most_common_local_sites']} sites)" if k["most_common_local"] else "None"),
             ("Unmatched factories", str(k["unmatched"]))]
    t = Table([[Paragraph(f'<font name="{BOLD}" size="12">{esc(v)}</font>', st["body"]) for _, v in cells],
               [Paragraph(esc(lbl), st["small"]) for lbl, _ in cells]], colWidths=[CONTENT_W / 4] * 4)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(RULE)), ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor(RULE)),
                           ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PANEL)), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, Spacer(1, 3 * mm), Paragraph(esc(p.paragraph), st["body"]),
              Paragraph("Local risks are sub-basin or aquifer scale; the overall score and downstream impact are not counted.", st["small"]),
              NextPageTemplate("landscape"), PageBreak(), Paragraph("Status matrix", st["h2"])]

    risk_cols = [c for c in p.columns if c["kind"] != "impact"]
    impact_cols = [c for c in p.columns if c["kind"] == "impact"]
    cols = risk_cols + impact_cols
    lw = landscape(A4)[0] - 2 * MARGIN
    name_w, overall_w = 44 * mm, 22 * mm
    cw = (lw - name_w - overall_w) / len(cols)
    head1 = [Paragraph("Factory", st["cellb"])] + [Paragraph("Risks", st["cellb"])] + [""] * (len(risk_cols) - 1)
    if impact_cols:
        head1 += [Paragraph("Downstream impact", st["cellb"])] + [""] * (len(impact_cols) - 1)
    head1 += [Paragraph("Overall", st["cellb"])]
    head2 = [""] + [Paragraph(esc(c["short_name"]).capitalize(), st["cellb"]) for c in cols] + [Paragraph("Textile score (0-5)", st["cellb"])]
    data, status_cmds = [head1, head2], []
    for i, row in enumerate(p.matrix, start=2):
        line = [Paragraph(esc(f"{row['site_name']} ({row['site_id']})"), st["cell"])]
        for j, c in enumerate(cols, start=1):
            cell = row["cells"][c["risk_id"]]
            line.append(_status_para(cell["word"], cell["status"], st))
            bg, _ = STATUS_COLORS[cell["status"]]
            status_cmds.append(("BACKGROUND", (j, i), (j, i), colors.HexColor(bg)))
        score = f"{row['overall_score']:.2f}" if row["overall_score"] is not None else "No data"
        line.append(Paragraph(esc(f"{score} {row['overall_label']}".strip()), st["cell"]))
        data.append(line)
    n_r, n_i = len(risk_cols), len(impact_cols)
    spans = [("SPAN", (1, 0), (n_r, 0))]
    if impact_cols:
        spans.append(("SPAN", (n_r + 1, 0), (n_r + n_i, 0)))
    t = Table(data, colWidths=[name_w] + [cw] * len(cols) + [overall_w], repeatRows=2)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#f2f4f7")), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor(RULE)),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                           *spans, *status_cmds]))
    story += [t, NextPageTemplate("portrait")]
    return story


def _appendix_story(doc: ReportDocument, st: dict) -> list:
    story: list = [PageBreak(), Heading("Methodology and limitations", st["h1"], toc=True, section="Methodology and limitations"),
                   Paragraph(esc(doc.methodology_intro), st["body"])]
    story += [Paragraph(esc(n), st["body"]) for n in doc.methodology_notes]
    data = [[Paragraph(x, st["cellb"]) for x in ("Risk", "What it measures", "Unit", "Scale", "Aqueduct", "Watch line", "Present line")]]
    for m in doc.methodology:
        data.append([Paragraph(esc(m["risk"]) + (" (impact)" if m["kind"] == "impact" else ""), st["cell"]),
                     Paragraph(esc(m["what_it_measures"]), st["cell"]), Paragraph(esc(m["unit"]), st["cell"]),
                     Paragraph(esc(m["scale"]), st["cell"]), Paragraph(esc(m["vintage"]), st["cell"]),
                     Paragraph(esc(m["watch_line"]), st["cell"]), Paragraph(esc(m["present_line"]), st["cell"])])
    t = Table(data, colWidths=[32 * mm, 56 * mm, 20 * mm, 16 * mm, 12 * mm, 19 * mm, 19 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f7")), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(RULE)),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
    story += [Spacer(1, 2 * mm), t]
    words = {"present": "Present", "watch": "Watch", "not_present": "Not present", "no_data": "No data", "error": "Error", "impact": "Downstream impact"}
    defs = [Paragraph(f"{pill(words[d['status']], d['status'] if d['status'] != 'impact' else 'no_data')} &nbsp;{esc(d['text'])}", st["body"])
            for d in doc.status_definitions]
    story.append(Paragraph("All values", st["h2"]))
    for fr in doc.factories:
        h = fr.context_header
        data = [[Paragraph(x, st["cellb"]) for x in ("Risk", "Value", "Raw", "Unit", "Score", "Cat.", "Aqueduct label", "Scale", "Ver.")]]
        for r in fr.summary_rows:
            data.append([Paragraph(esc(r[k]), st["cell"]) for k in ("risk", "value", "raw", "unit", "score", "category", "label", "scale", "vintage")])
        t = Table(data, colWidths=[31 * mm, 24 * mm, 15 * mm, 18 * mm, 10 * mm, 8 * mm, 34 * mm, 14 * mm, 10 * mm], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f7")), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(RULE)),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
        story += [Paragraph(f"{esc(h['name'])} ({esc(h['site_id'])})", st["risk"]), t, Spacer(1, 3 * mm)]
    story += [KeepTogether([Paragraph("Status definitions", st["h2"]), defs[0]]), *defs[1:]]
    bullets = _bullets(doc.limitations, st)
    story += [KeepTogether([Paragraph("Limitations", st["h2"]), bullets[0]]), *bullets[1:]]
    story.append(KeepTogether([
        Paragraph("Data and citation", st["h2"]),
        Paragraph(f'{esc(doc.citation)} (<a href="{esc(doc.citation_url)}" color="#175cd3">{esc(doc.citation_url)}</a>). '
                  f"{esc(doc.data_license)}", st["body"])]))
    return story


def _cover_story(doc: ReportDocument, st: dict) -> list:
    names = [f.context_header["name"] for f in doc.factories]
    shown = ", ".join(names[:12]) + (f" and {len(names) - 12} more" if len(names) > 12 else "")
    rows = [("Report type", doc.subtitle.split(":")[0]), ("Factory" if doc.report_type == "factory" else "Factories", shown),
            ("Generated", f"{doc.generated_at.day} {doc.generated_at:%B %Y}"), ("Hydris version", doc.hydris_version), ("Dataset", doc.dataset_version)]
    data = [[Paragraph(esc(k), st["small"]), Paragraph(esc(v), st["body"])] for k, v in rows]
    t = Table(data, colWidths=[34 * mm, CONTENT_W - 34 * mm], hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(RULE))]))
    return [Spacer(1, 45 * mm), Paragraph(esc(doc.title), st["title"]), Paragraph(esc(doc.subtitle), st["subtitle"]), t,
            Spacer(1, 12 * mm), _callout(doc.disclaimer, st, "#f2f4f7", RULE)]


def render_pdf(doc: ReportDocument) -> bytes:
    _fonts()
    st = _styles()
    buf = io.BytesIO()
    pdf = _Doc(buf, doc)
    story = _cover_story(doc, st)
    if doc.report_type == "portfolio":
        toc = TableOfContents(dotsMinLevel=0)
        toc.levelStyles = [st["toc"]]
        story += [PageBreak(), Paragraph("Contents", st["h1"]), toc]
        story += _portfolio_story(doc, st)
    for fr in doc.factories:
        story += _factory_story(fr, st)
    story += _appendix_story(doc, st)
    maker = lambda *a, **k: _NumberedCanvas(*a, owner=pdf, **k)  # noqa: E731
    if doc.report_type == "portfolio":
        pdf.multiBuild(story, canvasmaker=maker)
    else:
        pdf.build(story, canvasmaker=maker)
    return buf.getvalue()
