# export_utils.py
from pathlib import Path
import subprocess, shutil, tempfile

GITHUB_CSS = "https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown.css"

def write_file(path: Path, data: str):
    path.write_text(data, encoding="utf-8")
    print(f"✅ Saved → {path}")

def md_to_html(md: str) -> str:
    try:
        import markdown  # pip install markdown
    except ImportError:
        raise RuntimeError("Install the 'markdown' package: pip install markdown")
    body = markdown.markdown(md, extensions=["fenced_code", "tables"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CNC Process Plan</title>
  <link rel="stylesheet" href="{GITHUB_CSS}">
  <style>
    body {{ box-sizing:border-box; }}
    .markdown-body {{ max-width: 900px; margin:auto; padding:2rem; }}
  </style>
</head>
<body class="markdown-body">
{body}
</body>
</html>"""

def ask_path(default_name="process_plan", ext="txt") -> Path | None:
    try:
        import prompt_toolkit # nice file prompt
    except ImportError:
        # fallback to plain input
        target = input(f"Save as {default_name}.{ext} (enter path or leave blank to skip): ").strip()
    else:
        from prompt_toolkit.shortcuts import prompt
        target = prompt(f"Save as {default_name}.{ext}: ").strip()
    return Path(target) if target else None

def export_plan(plan_md: str):
    # 1. TXT (plain) ----------------------------------------------------------
    txt_path = ask_path(ext="txt")
    if txt_path:
        write_file(txt_path, plan_md)

    # 2. Markdown -------------------------------------------------------------
    md_path = ask_path(ext="md")
    if md_path:
        write_file(md_path, plan_md)

    # 3. HTML GitHub-style ----------------------------------------------------
    html_path = ask_path(ext="html")
    if html_path:
        write_file(html_path, md_to_html(plan_md))

    # 4. PDF via Pandoc (optional) -------------------------------------------
    pdf_path = ask_path(ext="pdf")
    if pdf_path:
        cmd = ["pandoc", "-", "-o", str(pdf_path)]
        try:
            subprocess.run(cmd, input=plan_md.encode(), check=True)
            print("✅ PDF generated with Pandoc")
        except FileNotFoundError:
            print("⚠️  Pandoc is not installed – skipped PDF export")
        except subprocess.CalledProcessError as e:
            print("❌ Pandoc error:", e)
