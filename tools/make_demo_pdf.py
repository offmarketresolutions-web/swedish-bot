"""Generate a demo IVT 490 manual PDF (text, so pdfplumber + the token estimate
work) for end-to-end grounded-answer demos. Real client manuals replace this.

Usage: uv run python tools/make_demo_pdf.py [out.pdf]
"""
import sys

from fpdf import FPDF

SECTIONS = [
    ("Alarm E11 - Low airflow", "Cause: clogged extract-air filter or blocked duct. "
     "Safe customer action: read the alarm code on the display and check the filter is "
     "clean. Do NOT open electrical panels. If airflow does not return after a clean "
     "filter, book a Nordland technician."),
    ("Alarm E22 - High condenser temperature", "Cause: reduced airflow or high ambient "
     "temperature. Safe action: ensure vents are unobstructed. Refrigerant work is "
     "required if it persists - this must be done by a qualified technician."),
    ("Alarm E32 - Sensor fault", "A temperature sensor reads out of range. This requires "
     "a service visit; no safe customer-side fix."),
    ("Hot water production", "If hot water drops, first check the extract-air filter and "
     "the set temperature on the display. The exhaust-air heat pump recovers energy from "
     "ventilation air; a blocked filter reduces both heating and hot water."),
    ("Electric backup heater", "The IVT 490 has an electric backup heater. Do not attempt "
     "to service heating elements or wiring - this is licensed electrical work."),
]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "data/uploads/ivt490_demo_manual.pdf"
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 10, "IVT 490 Exhaust-Air Heat Pump - Service Manual (demo)",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    # Repeat the content to exceed the context-cache token floor comfortably.
    for _ in range(40):
        for title, body in SECTIONS:
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 6, body, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
    pdf.output(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
