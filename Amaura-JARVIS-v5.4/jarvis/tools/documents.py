"""
Document Tools — PPT, PDF, and Markdown document generation.
Gives Jarvis the ability to create presentations and documents.
"""

import re
from datetime import datetime
from pathlib import Path

# ── Tool Definitions ─────────────────────────────────────────────────────────

DOCUMENT_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_presentation",
            "description": "Create a PowerPoint (.pptx) presentation with slides. Each slide has a title and bullet points.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Presentation title."},
                    "slides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "Slide title."},
                                "bullets": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Bullet points.",
                                },
                            },
                        },
                        "description": "List of slides, each with a title and bullet points.",
                    },
                    "output_path": {"type": "string", "description": "Output file path (default: ~/Desktop/)."},
                },
                "required": ["title", "slides"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_word_document",
            "description": "Create a professional Microsoft Word (.docx) document with styled headings, paragraphs, bullet lists, and tables.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Document title."},
                    "content": {"type": "string", "description": "Document content in Markdown or text format."},
                    "output_path": {"type": "string", "description": "Output file path (default: ~/Desktop/<title>.docx)."},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_document",
            "description": "Create a Markdown document and save it to disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Document title."},
                    "content": {"type": "string", "description": "Document content in Markdown format."},
                    "output_path": {"type": "string", "description": "Output file path (default: ~/Desktop/)."},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_spreadsheet",
            "description": "Create a CSV spreadsheet from structured data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Spreadsheet title (used for filename)."},
                    "headers": {"type": "array", "items": {"type": "string"}, "description": "Column headers."},
                    "rows": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                        "description": "Data rows.",
                    },
                    "output_path": {"type": "string", "description": "Output file path (default: ~/Desktop/)."},
                },
                "required": ["title", "headers", "rows"],
            },
        },
    },
]


# ── Tool Implementations ─────────────────────────────────────────────────────


def tool_create_presentation(title: str, slides: list[dict], output_path: str = "") -> str:
    """Create a PowerPoint presentation using python-pptx."""
    try:
        from pptx import Presentation
        from pptx.util import Inches
    except ImportError:
        return "❌ python-pptx not installed. Run: pip install python-pptx"

    if not output_path:
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:50]
        output_path = str(Path.home() / "Desktop" / f"{safe_title}.pptx")

    p = Path(output_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # ── Title Slide ──────────────────────────────────────────────────
    slide_layout = prs.slide_layouts[0]  # Title Slide
    slide = prs.slides.add_slide(slide_layout)
    slide.shapes.title.text = title
    if slide.placeholders[1]:
        slide.placeholders[1].text = f"Generated by J.A.R.V.I.S. • {datetime.now().strftime('%B %d, %Y')}"

    # ── Content Slides ───────────────────────────────────────────────
    for slide_data in slides:
        slide_layout = prs.slide_layouts[1]  # Title and Content
        slide = prs.slides.add_slide(slide_layout)

        # Title
        slide.shapes.title.text = slide_data.get("title", "")

        # Bullets
        bullets = slide_data.get("bullets", [])
        if bullets and len(slide.placeholders) > 1:
            tf = slide.placeholders[1].text_frame
            tf.clear()
            for i, bullet in enumerate(bullets):
                if i == 0:
                    tf.text = bullet
                else:
                    p_new = tf.add_paragraph()
                    p_new.text = bullet
                    p_new.level = 0

    prs.save(str(p))
    num_slides = len(slides) + 1  # +1 for title slide
    return f'✅ Presentation created: {p}\n   {num_slides} slides, titled "{title}"'


def tool_create_word_document(title: str, content: str, output_path: str = "") -> str:
    """Create a Microsoft Word (.docx) document using python-docx."""
    try:
        import docx
        from docx.shared import Inches, Pt, RGBColor
    except ImportError:
        return "❌ python-docx not installed. Run: pip install python-docx"

    if not output_path:
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:50]
        output_path = str(Path.home() / "Desktop" / f"{safe_title}.docx")
    elif not output_path.endswith(".docx"):
        output_path += ".docx"

    p = Path(output_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    doc = docx.Document()

    # Title
    doc.add_heading(title, level=0)
    subtitle = doc.add_paragraph()
    sub_run = subtitle.add_run(f"Generated by J.A.R.V.I.S. • {datetime.now().strftime('%B %d, %Y')}")
    sub_run.italic = True
    sub_run.font.color.rgb = RGBColor(128, 128, 128)

    # Process markdown content lines
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=3)
        elif stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
        elif stripped.startswith("# "):
            doc.add_heading(stripped[2:], level=1)
        elif stripped.startswith(("- ", "* ", "• ")):
            doc.add_paragraph(stripped[2:], style="List Bullet")
        elif re.match(r"^\d+\.\s+", stripped):
            bullet_text = re.sub(r"^\d+\.\s+", "", stripped)
            doc.add_paragraph(bullet_text, style="List Number")
        elif stripped.startswith("|") and stripped.endswith("|"):
            # Table detection
            table_lines = [stripped]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            # Parse table
            parsed_rows = []
            for tl in table_lines:
                if re.match(r"^\|[\s\-:|]+\|$", tl):
                    continue  # delimiter line
                cols = [c.strip() for c in tl.strip("|").split("|")]
                parsed_rows.append(cols)
            if parsed_rows:
                num_cols = max(len(r) for r in parsed_rows)
                t = doc.add_table(rows=len(parsed_rows), cols=num_cols)
                t.style = "Table Grid"
                for r_idx, row_data in enumerate(parsed_rows):
                    for c_idx, val in enumerate(row_data):
                        if c_idx < num_cols:
                            cell = t.cell(r_idx, c_idx)
                            cell.text = val
                            if r_idx == 0:
                                for p_elem in cell.paragraphs:
                                    for r_elem in p_elem.runs:
                                        r_elem.bold = True
            continue
        else:
            doc.add_paragraph(stripped)
        i += 1

    doc.save(str(p))
    word_count = len(content.split())
    return f'✅ Word document created: {p}\n   {word_count} words, titled "{title}"'


def tool_create_document(title: str, content: str, output_path: str = "") -> str:
    """Create a document (delegates to Word .docx if requested, otherwise Markdown)."""
    if output_path and output_path.lower().endswith(".docx"):
        return tool_create_word_document(title, content, output_path)

    if not output_path:
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:50]
        output_path = str(Path.home() / "Desktop" / f"{safe_title}.md")

    p = Path(output_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    doc_content = f"# {title}\n\n"
    doc_content += f"*Generated by J.A.R.V.I.S. on {datetime.now().strftime('%B %d, %Y at %H:%M')}*\n\n"
    doc_content += "---\n\n"
    doc_content += content

    with open(p, "w", encoding="utf-8") as f:
        f.write(doc_content)

    word_count = len(content.split())
    return f'✅ Document created: {p}\n   {word_count} words, titled "{title}"'


def tool_create_spreadsheet(title: str, headers: list[str], rows: list[list], output_path: str = "") -> str:
    """Create a spreadsheet (Excel .xlsx or CSV .csv)."""
    if not output_path:
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:50]
        output_path = str(Path.home() / "Desktop" / f"{safe_title}.xlsx")

    p = Path(output_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    if p.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl
            from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
            from openpyxl.utils import get_column_letter

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = title[:30] if title else "Sheet1"

            # Header style
            ws.append(headers)
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
            thin_border = Border(
                left=Side(style="thin", color="D9D9D9"),
                right=Side(style="thin", color="D9D9D9"),
                top=Side(style="thin", color="D9D9D9"),
                bottom=Side(style="thin", color="D9D9D9"),
            )

            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_num)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Data rows
            for row in rows:
                ws.append(row)

            # Borders & column auto-fit
            for row in ws.iter_rows(min_row=1, max_row=len(rows) + 1, min_col=1, max_col=len(headers)):
                for cell in row:
                    cell.border = thin_border

            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

            wb.save(str(p))
            return f"✅ Excel spreadsheet created: {p}\n   {len(rows)} rows × {len(headers)} columns"
        except ImportError:
            # Fall back to CSV
            p = p.with_suffix(".csv")

    import csv

    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    return f"✅ Spreadsheet created: {p}\n   {len(rows)} rows × {len(headers)} columns"


# ── Dispatch ─────────────────────────────────────────────────────────────────

DOCUMENT_DISPATCH = {
    "create_presentation": lambda **kw: tool_create_presentation(
        kw.get("title", "Untitled"), kw.get("slides", []), kw.get("output_path", "")
    ),
    "create_document": lambda **kw: tool_create_document(
        kw.get("title", "Untitled"), kw.get("content", ""), kw.get("output_path", "")
    ),
    "create_word_document": lambda **kw: tool_create_word_document(
        kw.get("title", "Untitled"), kw.get("content", ""), kw.get("output_path", "")
    ),
    "create_spreadsheet": lambda **kw: tool_create_spreadsheet(
        kw.get("title", "Untitled"), kw.get("headers", []), kw.get("rows", []), kw.get("output_path", "")
    ),
}
