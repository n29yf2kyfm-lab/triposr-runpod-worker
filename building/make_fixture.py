"""Generate the schedule-parser fixture.

A REAL client drawing would be the obvious fixture and is exactly what must
not go in a public repository — it carries an address and an architect's
work. This reproduces the structural pathologies that broke the parser,
using invented rooms in an invented building:

  * the level name wraps ("1. Ground" on one line, "Floor" on the next)
  * the number and its unit are separate words with a gap
  * a room name wraps mid-word, the way a narrow column forces it to
  * the same name appears on more than one level, and twice on one level
  * a second, smaller table sits on the page to be ignored

NOT reproducible here: on the real sheet the grid detector returned None for
the area cell on 8 of 20 rows, which is why the areas are recovered from
their coordinates instead. Synthesising that needs the exact cell geometry a
particular CAD exporter produces. The recovery is verified against the real
drawing — 12 of 20 rows from extract() alone, 20 of 20 with it — and this
fixture covers everything else.
  * plan labels sit OUTSIDE the table, to be ignored

Run: python building/make_fixture.py
"""
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas

ROWS = [
    ("Hallway",           "1. Ground", "Floor", 9),
    ("Living Room 1",     "1. Ground", "Floor", 19),
    ("Kitchen/Dini",      "1. Ground", "Floor", 34),   # name wraps mid-word
    ("Utility",           "1. Ground", "Floor", 2),
    ("Bedroom 3",         "2. First",  "Floor", 15),
    ("Bedroom4",          "2. First",  "Floor", 15),   # no space, as printed
    ("Ensuite",           "2. First",  "Floor", 3),
    ("Ensuite",           "2. First",  "Floor", 3),    # twice on one level
    ("Hallway",           "2. First",  "Floor", 14),   # same name, other level
    ("Cinema",            "3. Loft Floor", None, 22),  # level on one line
    ("Hallway",           "3. Loft Floor", None, 11),
]

W, H = landscape(A3)
c = canvas.Canvas("fixtures_schedule.pdf", pagesize=(W, H))

# --- plan labels OUTSIDE the table. The first parser scraped these into the
# --- schedule and produced rooms called "13 m2 Bathroom".
c.setFont("Helvetica", 9)
for x, y, t in [(90, H - 160, "Bathroom"), (90, H - 175, "6 m2"),
                (90, H - 190, "63.0 SF"), (240, H - 160, "1 : 100"),
                (240, H - 175, "Master Bedroom"), (240, H - 190, "15 m2")]:
    c.drawString(x, y, t)

# --- the schedule -----------------------------------------------------------
X0, X1 = 620.0, 1000.0
COL = (630.0, 800.0, 930.0)          # name | level | area
TOP = H - 90.0
RH = 34.0

c.setFont("Helvetica-Bold", 10)
c.drawString(COL[0], TOP + 10, "House Type 9 Room Schedule")
y = TOP - 6
c.setFont("Helvetica", 9)
for lab, x in zip(("Name", "Level", "Area"), COL):
    c.drawString(x, y, lab)

c.setLineWidth(0.5)
c.line(X0, y - 6, X1, y - 6)
top_rule = y - 6

for i, (name, lvl1, lvl2, area) in enumerate(ROWS):
    ry = top_rule - i * RH
    c.setFont("Helvetica", 9)
    c.drawString(COL[0], ry - 12, name)
    if lvl2:
        c.drawString(COL[0], ry - 23, "ng/Lounge" if name == "Kitchen/Dini" else "")
    c.drawString(COL[1], ry - 12, lvl1)
    if lvl2:
        c.drawString(COL[1], ry - 23, lvl2)
    # number and unit as SEPARATE words with a real gap, as the CAD export does
    c.drawString(COL[2], ry - 12, str(area))
    c.drawString(COL[2] + 26, ry - 12, "m2")
    c.line(X0, ry - RH, X1, ry - RH)

bottom = top_rule - len(ROWS) * RH
c.line(X0, top_rule, X1, top_rule)
c.line(X0, bottom, X1, bottom)
# column rules — without these pdfplumber sees one column, not three
for x in (X0, COL[1] - 10, COL[2] - 10, X1):
    c.line(x, top_rule, x, bottom)

# --- a smaller title block table, to be ignored -----------------------------
ty = 120
c.rect(700, ty, 380, 60)
c.line(700, ty + 30, 1080, ty + 30)
c.line(880, ty, 880, ty + 60)
c.setFont("Helvetica", 8)
c.drawString(706, ty + 40, "Scale (@A3)")
c.drawString(886, ty + 40, "1 : 100")
c.drawString(706, ty + 10, "Date")
c.drawString(886, ty + 10, "15.06.2025")

c.showPage()
c.save()
print("wrote fixtures_schedule.pdf")
