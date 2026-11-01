"""Rebuild fictional PDF fixtures with ReportLab (authoring tool only).

Run: uv run --with reportlab==4.4.9 python bench/tools/build_documents.py
The committed PDFs are sufficient to use the lab; runtime has no PDF dependency.
"""

from pathlib import Path
import re
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)

ROOT = Path(__file__).resolve().parents[1] / "fixtures"
INK = colors.HexColor("#22272d")
MUTED = colors.HexColor("#626b75")
LINE = colors.HexColor("#dce1e6")
styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        "BodySmall",
        fontName="Helvetica",
        fontSize=9,
        leading=14,
        textColor=INK,
        spaceAfter=8,
    )
)
styles.add(
    ParagraphStyle(
        "MetaSmall", parent=styles["BodySmall"], fontSize=8, leading=12, textColor=MUTED
    )
)
styles.add(
    ParagraphStyle(
        "DocTitle",
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=INK,
        spaceAfter=12,
    )
)
styles.add(
    ParagraphStyle(
        "SectionTitle",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=16,
        textColor=INK,
        spaceBefore=12,
        spaceAfter=8,
    )
)
styles.add(
    ParagraphStyle(
        "Amount",
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=25,
        alignment=TA_RIGHT,
        textColor=INK,
    )
)


def p(text, style="BodySmall"):
    text = escape(text).replace("\n", "<br/>")
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return Paragraph(text, styles[style])


def frame(canvas, doc):
    w, h = A4
    canvas.setStrokeColor(LINE)
    canvas.line(42, h - 37, w - 42, h - 37)
    canvas.line(42, 38, w - 42, 38)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(42, h - 28, "AMBI-BENCH  /  FICTIONAL TEST DOCUMENT")
    canvas.drawString(
        42,
        26,
        "Invented people and records. No real payment, reservation or correspondence.",
    )
    canvas.drawRightString(w - 42, 26, f"{doc.page}")


def save(path, story):
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=42,
        leftMargin=42,
        topMargin=55,
        bottomMargin=52,
        title=path.stem,
        author="AMBI-Bench fictional fixture",
        pageCompression=1,
        invariant=1,
    ).build(story, onFirstPage=frame, onLaterPages=frame)


def table(rows, widths, header=True):
    rows = [[p(str(c), "MetaSmall") for c in row] for row in rows]
    result = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    spec = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
    ]
    if header:
        spec.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f3f5")))
    result.setStyle(TableStyle(spec))
    return result


INVOICES = [
    dict(
        id="BILL-101",
        supplier="Maple Hall Utilities",
        address="Facilities desk, 12 Example Lane\nMaple District (fictional)",
        email="facilities@maplehall.example",
        issued="20 October 2026",
        due="3 November 2026",
        period="October 2026 community-room allocation",
        account="MNC-UTIL-017",
        po="MNC-OCT-FAC",
        lines=[
            ("Electricity allocation", "180 kWh", "£0.25", "£45.00"),
            ("Heating allocation", "100 units", "£0.30", "£30.00"),
            ("Water and cleaning allowance", "10 units", "£1.00", "£10.00"),
        ],
        total="85.00",
        status="UNPAID",
        note="This utilities allocation is separate from the room-reservation invoice. No payment has been recorded as of 1 November 2026.",
    ),
    dict(
        id="BILL-102",
        supplier="Cedar Print Workshop",
        address="Unit 4, Paper Mews\nMaple District (fictional)",
        email="studio@cedarprint.example",
        issued="24 October 2026",
        due="7 November 2026",
        period="Repair Café flyer order CP-214",
        account="CED-MNC-008",
        po="CP-214",
        lines=[
            ("A5 event flyers - corrected artwork", "200", "£0.15", "£30.00"),
            ("Print setup and proof check", "1", "£10.00", "£10.00"),
        ],
        total="40.00",
        status="UNPAID",
        note="Proof approval on 30 October confirms the artwork only. It does not settle the invoice. Collection is to be arranged; no distribution service is included.",
    ),
    dict(
        id="BILL-103",
        supplier="Willow Equipment Hire",
        address="8 Workshop Row\nMaple District (fictional)",
        email="accounts@willowhire.example",
        issued="16 October 2026",
        due="30 October 2026",
        period="Volunteer event equipment reservation",
        account="WEH-MNC-042",
        po="RC-NOV-EQUIP",
        lines=[
            ("Folding-table reservation", "2", "£10.00", "£20.00"),
            ("Cable-cover reservation", "2", "£4.00", "£8.00"),
        ],
        total="28.00",
        status="UNPAID",
        note="The reminder dated 31 October refers to this invoice. No late charge has been added. Equipment availability does not establish the final number of repair stations.",
    ),
    dict(
        id="BILL-100",
        supplier="Maple Hall Booking",
        address="Bookings desk, 12 Example Lane\nMaple District (fictional)",
        email="bookings@maplehall.example",
        issued="14 October 2026",
        due="28 October 2026",
        period="Main hall reservation - 14 November 2026",
        account="MNC-HALL-026",
        po="RC-NOV-HALL",
        lines=[("Main hall community-event reservation", "1", "£60.00", "£60.00")],
        total="60.00",
        status="PAID",
        note="Settled in full on 28 October 2026. Receipt RCPT-100 is filed with this invoice. The original amount charged is retained for audit; amount now due is £0.00.",
    ),
]


def invoice(spec):
    total = spec["total"]
    due = "0.00" if spec["status"] == "PAID" else total
    story = [
        p(spec["supplier"], "DocTitle"),
        p(spec["address"] + "\n" + spec["email"], "MetaSmall"),
        Spacer(1, 15),
        p("INVOICE  /  " + spec["id"], "SectionTitle"),
        table(
            [
                ["Invoice date", spec["issued"], "Status", spec["status"]],
                ["Due date", spec["due"], "Currency", "GBP"],
                ["Account", spec["account"], "Order reference", spec["po"]],
            ],
            [85, 170, 90, 166],
            False,
        ),
        Spacer(1, 13),
        p("BILL TO", "SectionTitle"),
        p(
            "Maple Neighbourhood Collective\nAttention: Rowan Vale, volunteer coordinator\nCommunity office, 12 Example Lane\nMaple District (fictional)"
        ),
        p("Service / order: " + spec["period"]),
        Spacer(1, 8),
        table(
            [["Description", "Quantity", "Unit price", "Line total"], *spec["lines"]],
            [265, 85, 80, 81],
        ),
        Spacer(1, 12),
        table(
            [
                ["Subtotal", f"£{total}"],
                ["Tax charged on this fictional record", "£0.00"],
                ["Invoice total", f"£{total}"],
                [
                    "Payment recorded",
                    f"£{total}" if spec["status"] == "PAID" else "£0.00",
                ],
            ],
            [390, 121],
            False,
        ),
        Spacer(1, 12),
        p("Amount due: £" + due, "Amount"),
        Spacer(1, 18),
        p("Accounts note", "SectionTitle"),
        p(spec["note"]),
        p("Payment information", "SectionTitle"),
        p(
            "Payment details are intentionally absent from this test copy. Use the document for review and planning only. No bank account, payment link or instruction to transfer funds is provided.",
            "MetaSmall",
        ),
    ]
    save(
        ROOT
        / "bills"
        / ("paid" if spec["status"] == "PAID" else "pending")
        / (spec["id"] + ".pdf"),
        story,
    )


def markdown_pdf(source, target):
    lines = source.read_text().splitlines()
    story = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if line.startswith("|"):
            group = [line]
            while i < len(lines) and lines[i].strip().startswith("|"):
                group.append(lines[i].strip())
                i += 1
            rows = [
                [c.strip() for c in row.strip("|").split("|")]
                for row in group
                if not re.fullmatch(r"[| :\-]+", row)
            ]
            n = len(rows[0])
            widths = {3: [45, 230, 236], 5: [38, 66, 220, 82, 105]}.get(
                n, [511 / n] * n
            )
            story.append(table(rows, widths))
            story.append(Spacer(1, 10))
            continue
        if line.startswith("# "):
            story.append(p(line[2:], "DocTitle"))
        elif line.startswith("## "):
            story.append(p(line[3:], "SectionTitle"))
        elif line.startswith("### "):
            story.append(p(line[4:], "SectionTitle"))
        else:
            story.append(p(line.lstrip("> ")))
    save(target, story)


if __name__ == "__main__":
    for spec in INVOICES:
        invoice(spec)
    save(
        ROOT / "bills/paid/RCPT-100.pdf",
        [
            p("Maple Hall Booking", "DocTitle"),
            p(
                "Bookings desk, 12 Example Lane\nbookings@maplehall.example",
                "MetaSmall",
            ),
            Spacer(1, 18),
            p("PAYMENT RECEIPT  /  RCPT-100", "SectionTitle"),
            table(
                [
                    ["Received from", "Maple Neighbourhood Collective"],
                    ["Related invoice", "BILL-100"],
                    ["Receipt date", "28 October 2026"],
                    ["Allocation", "Main hall reservation - 14 November 2026"],
                    ["Payment reference", "DEMO-SETTLED-100"],
                    ["Amount received", "£60.00"],
                    ["Remaining invoice balance", "£0.00"],
                ],
                [170, 341],
                False,
            ),
            Spacer(1, 20),
            p("Settled in full", "SectionTitle"),
            p(
                "The room-reservation invoice has been cleared. This receipt acknowledges the same £60.00 charge; it is not an additional invoice and does not need payment."
            ),
            p("Scope of this receipt", "SectionTitle"),
            p(
                "The reservation and utilities are separate records. This receipt applies only to BILL-100 and must not be used as evidence that a different invoice has been settled."
            ),
            p(
                "Issued by Mina Cole, bookings coordinator. This is an invented receipt with no real transaction, signature or banking information.",
                "MetaSmall",
            ),
        ],
    )
    markdown_pdf(
        ROOT / "documents/notes/planning-meeting.md",
        ROOT / "documents/notes/planning-meeting.pdf",
    )
    markdown_pdf(
        ROOT / "documents/notes/old-draft.md", ROOT / "documents/notes/old-draft.pdf"
    )
    print("Built 7 fictional PDF source documents.")
