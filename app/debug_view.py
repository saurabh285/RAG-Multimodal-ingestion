from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_env = Environment(loader=FileSystemLoader("templates"))


def render_debug_html(
    document_id: int, filename: str, chunks: list, out_dir: str = "data/debug"
) -> str:
    template = _env.get_template("debug.html")
    html = template.render(document_id=document_id, filename=filename, chunks=chunks)

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(out_dir) / f"{document_id}.html"
    out_path.write_text(html)
    return str(out_path)
