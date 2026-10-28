"""Импорт ноутбука в приложение без ручной правки.

Кладёте .ipynb в notebooks/ (или в корень проекта) → `make notebook` → графики на http://localhost:8000.

Что делает:
  1. (EXECUTE=1) перевыполняет копию ноутбука против текущей базы (файл не меняется);
     при ошибке берёт сохранённые в ноутбуке выходы.
  2. Вытаскивает каждую PNG-картинку из выходов ячеек → app/static/notebook/<id>.png.
  3. Заголовок — ближайший markdown-заголовок выше (или первая строка-комментарий ячейки),
     легенда — первое предложение markdown-текста рядом (или строка `# caption: ...` в ячейке).
  4. Пишет app/static/notebook/manifest.json — приложение читает его на каждом запросе.
  5. Сохраняет код ноутбука как notebooks/_extracted/<имя>.py — исходник для переноса логики в SQL.

    python -m pipeline.import_notebook [путь.ipynb ...]
"""

import base64
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "app" / "static" / "notebook"
CODE_DIR = ROOT / "notebooks" / "_extracted"

SENTENCE = re.compile(r"(.+?[.!?…])(\s|$)", re.S)


def find_notebooks(args: list[str]) -> list[pathlib.Path]:
    if args:
        return [pathlib.Path(a).resolve() for a in args]
    found = sorted((ROOT / "notebooks").glob("*.ipynb")) + sorted(ROOT.glob("*.ipynb"))
    unique, seen = [], set()
    for p in found:  # один и тот же ноутбук в notebooks/ и в корне — берём из notebooks/
        if ".ipynb_checkpoints" not in p.parts and p.name not in seen:
            seen.add(p.name)
            unique.append(p)
    return unique


def text(cell) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else src


def first_sentence(md: str) -> str:
    lines = [ln.strip() for ln in md.splitlines()]
    body = " ".join(ln.lstrip("-*> ").strip() for ln in lines if ln and not ln.startswith("#"))
    body = re.sub(r"[*_`]", "", body).strip()
    if not body:
        return ""
    m = SENTENCE.match(body)
    return (m.group(1) if m else body)[:240].strip()


def heading(md: str) -> str:
    for ln in md.splitlines():
        if ln.lstrip().startswith("#"):
            return ln.lstrip("# ").strip()
    return ""


def code_meta(code: str) -> tuple[str, str]:
    """`# title: ...` / `# caption: ...` в ячейке; иначе первая строка-комментарий = заголовок."""
    title = caption = ""
    for ln in code.splitlines():
        s = ln.strip()
        if not s.startswith("#"):
            continue
        body = s.lstrip("# ").strip()
        low = body.lower()
        if low.startswith(("caption:", "легенда:")):
            caption = body.split(":", 1)[1].strip()
        elif low.startswith(("title:", "заголовок:")):
            title = body.split(":", 1)[1].strip()
        elif not title and body:
            title = body
    return title, caption


def execute(nb, path: pathlib.Path):
    """Перевыполнить ноутбук; в контейнере localhost базы — это сервис postgres."""
    import warnings

    import nbformat
    from nbclient import NotebookClient

    warnings.filterwarnings("ignore", category=nbformat.validator.MissingIDFieldWarning)
    run = nbformat.reads(json.dumps(nb), as_version=4)  # нормализует source из списка строк в строку
    # в образе MPLBACKEND=Agg — с ним plt.show() в ядре ничего не выводит; нужен inline, как в Jupyter
    os.environ["MPLBACKEND"] = "module://matplotlib_inline.backend_inline"
    db_host = os.getenv("PGHOST", "localhost")
    if db_host != "localhost":
        for c in run.cells:
            if c.cell_type == "code":
                c.source = re.sub(r"\b(localhost|127\.0\.0\.1)\b", db_host, c.source)
    NotebookClient(run, timeout=600, kernel_name="python3",
                   resources={"metadata": {"path": str(ROOT)}}).execute()
    return json.loads(nbformat.writes(run))  # исходный файл ноутбука не перезаписываем


def import_notebook(path: pathlib.Path, do_execute: bool) -> list[dict]:
    nb = json.loads(path.read_text(encoding="utf-8"))
    if do_execute:
        try:
            nb = execute(nb, path)
            print(f"  выполнен заново: {path.name}")
        except Exception as e:  # ноутбук, который не выполняется в контейнере, всё равно импортируем
            print(f"  ! не выполнился ({type(e).__name__}: {str(e)[:200]}), беру сохранённые выходы")

    stem = re.sub(r"\W+", "_", path.stem).strip("_").lower() or "notebook"
    cells = nb.get("cells", [])
    charts, last_heading, last_md = [], "", ""
    code_lines = [f"# Извлечено из {path.name} (pipeline/import_notebook.py). Не редактировать."]

    for i, cell in enumerate(cells):
        src = text(cell)
        if cell.get("cell_type") == "markdown":
            last_heading = heading(src) or last_heading
            last_md = src
            code_lines.append("\n# " + "\n# ".join(src.splitlines()))
            continue
        if cell.get("cell_type") != "code":
            continue
        code_lines.append(f"\n# %% [cell {i}]\n{src}")

        next_md = text(cells[i + 1]) if i + 1 < len(cells) and cells[i + 1].get("cell_type") == "markdown" else ""
        c_title, c_caption = code_meta(src)
        outputs = cell.get("outputs", [])
        # картинка + легенда выводом display(Markdown(...)) сразу после неё
        images = []
        for n, o in enumerate(outputs):
            data = o.get("data", {})
            if "image/png" not in data:
                continue
            after = outputs[n + 1].get("data", {}) if n + 1 < len(outputs) else {}
            images.append((data["image/png"], text({"source": after.get("text/markdown", "")})))
        # заголовки из ax.set_title('...') — если их ровно столько же, сколько картинок в ячейке
        set_titles = [t.split("{")[0].strip(" :—-") for _, t in re.findall(r"set_title\(\s*f?(['\"])(.*?)\1", src)]
        if len(set_titles) != len(images):
            set_titles = []
        for k, (b64, md_out) in enumerate(images):
            chart_id = f"{stem}_{i:03d}_{k}"
            (OUT_DIR / f"{chart_id}.png").write_bytes(base64.b64decode("".join(b64) if isinstance(b64, list) else b64))
            charts.append({
                "id": chart_id,
                "notebook": path.name,
                "cell": i,
                "title": c_title or (set_titles[k] if set_titles else "") or last_heading or f"{path.stem}: ячейка {i}",
                "caption": (c_caption or first_sentence(md_out) or first_sentence(last_md)
                            or first_sentence(next_md)),
                "src": f"/static/notebook/{chart_id}.png",
            })
        if images:
            last_md = ""  # легенда markdown-ячейки относится только к первому графику после неё

    CODE_DIR.mkdir(parents=True, exist_ok=True)
    (CODE_DIR / f"{stem}.py").write_text("\n".join(code_lines) + "\n", encoding="utf-8")
    return charts


def main(argv: list[str]) -> int:
    notebooks = find_notebooks(argv)
    if not notebooks:
        print("Ноутбуков нет: положите .ipynb в notebooks/ или в корень проекта.")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.png"):
        old.unlink()

    do_execute = os.getenv("EXECUTE") == "1"
    manifest = []
    for nb in notebooks:
        print(f"==> {nb.relative_to(ROOT) if nb.is_relative_to(ROOT) else nb}")
        charts = import_notebook(nb, do_execute)
        print(f"  графиков: {len(charts)}")
        manifest += charts

    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Итого графиков из ноутбуков: {len(manifest)} → app/static/notebook/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
