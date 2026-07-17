"""v3: Render IRIS_design_report.md -> HTML and PDF.

The markdown content is authored by hand (kept in report/IRIS_design_report.md);
this script only converts formats. Any programmatic rebuild logic from earlier
revisions is intentionally removed to avoid clobbering the v3 report.
"""
from pathlib import Path
import markdown
from weasyprint import HTML

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / 'report'
MD_PATH = REPORT_DIR / 'IRIS_design_report.md'
HTML_PATH = REPORT_DIR / 'IRIS_design_report.html'
PDF_PATH = REPORT_DIR / 'IRIS_design_report.pdf'


CSS = """
body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #1f2937; margin: 40px; line-height: 1.55; }
h1 { color: #0f172a; border-bottom: 3px solid #0ea5e9; padding-bottom: 6px; }
h2 { color: #0f172a; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; margin-top: 32px; }
h3 { color: #1e293b; margin-top: 24px; }
img { max-width: 100%; height: auto; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 90%; }
th, td { border: 1px solid #cbd5e1; padding: 6px 10px; }
th { background: #f1f5f9; }
tr:nth-child(even) td { background: #f9fafb; }
code { background: #f1f5f9; padding: 1px 4px; border-radius: 3px; }
"""


def main():
    md_source = MD_PATH.read_text()
    body = markdown.markdown(md_source, extensions=['tables', 'fenced_code'])
    html_full = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    HTML_PATH.write_text(html_full)
    HTML(string=html_full, base_url=str(REPORT_DIR)).write_pdf(str(PDF_PATH))
    print(MD_PATH)
    print(HTML_PATH)
    print(PDF_PATH)


if __name__ == '__main__':
    main()
