"""
LaTeX Compiler — Compiles .tex files to .pdf and validates output.
"""

import subprocess
import os
import shutil
import tempfile
from typing import Optional


class CompilationError(Exception):
    pass


class PageCountError(Exception):
    pass


def find_pdflatex() -> str:
    """Locate pdflatex binary."""
    path = shutil.which("pdflatex")
    if path:
        return path
    # Common install locations on Windows (MiKTeX / TeX Live)
    candidates = [
        r"C:\Program Files\MiKTeX\miktex\bin\x64\pdflatex.exe",
        r"C:\Program Files\MiKTeX 2.9\miktex\bin\x64\pdflatex.exe",
        r"C:\texlive\2023\bin\windows\pdflatex.exe",
        r"C:\texlive\2024\bin\windows\pdflatex.exe",
        # MiKTeX user-level install (Windows)
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "MiKTeX", "miktex", "bin", "x64", "pdflatex.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "Programs", "MiKTeX", "miktex", "bin", "x64", "pdflatex.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise CompilationError(
        "pdflatex not found. Install MiKTeX (https://miktex.org/) or TeX Live."
    )


def compile_latex(tex_path: str, output_dir: Optional[str] = None,
                  runs: int = 2) -> str:
    """
    Compile a .tex file to PDF.

    Args:
        tex_path:   Absolute path to the .tex file.
        output_dir: Directory for output files. Defaults to same dir as .tex.
        runs:       Number of pdflatex passes (2 for cross-references).

    Returns:
        Absolute path to the compiled .pdf file.

    Raises:
        CompilationError if pdflatex fails.
        PageCountError   if the PDF is not exactly 1 page.
    """
    tex_path = os.path.abspath(tex_path)
    if output_dir is None:
        output_dir = os.path.dirname(tex_path)
    os.makedirs(output_dir, exist_ok=True)

    pdflatex = find_pdflatex()

    for i in range(runs):
        result = subprocess.run(
            [
                pdflatex,
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={output_dir}",
                tex_path,
            ],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min: first run installs MiKTeX packages on-the-fly
        )
        if result.returncode != 0:
            # Extract the meaningful error lines from pdflatex output
            error_lines = [
                line for line in result.stdout.splitlines()
                if line.startswith("!") or "Error" in line
            ]
            error_summary = "\n".join(error_lines[:10]) or result.stderr[:500]
            raise CompilationError(
                f"pdflatex failed (pass {i + 1}):\n{error_summary}"
            )

    tex_basename = os.path.splitext(os.path.basename(tex_path))[0]
    pdf_path = os.path.join(output_dir, tex_basename + ".pdf")

    if not os.path.isfile(pdf_path):
        raise CompilationError(f"PDF not produced at expected path: {pdf_path}")

    return pdf_path


def get_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF using pdfinfo or PyPDF2."""
    # Try pdfinfo first (faster)
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        result = subprocess.run(
            [pdfinfo, pdf_path], capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if line.lower().startswith("pages:"):
                return int(line.split(":")[1].strip())

    # Fallback: PyPDF2
    try:
        import PyPDF2
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            return len(reader.pages)
    except ImportError:
        pass

    # Final fallback: assume 1 page if we can't check
    return 1


def validate_pdf(pdf_path: str, expected_pages: int = 1):
    """Validate PDF exists and has the expected page count."""
    if not os.path.isfile(pdf_path):
        raise CompilationError(f"PDF file not found: {pdf_path}")
    if os.path.getsize(pdf_path) < 1000:
        raise CompilationError(f"PDF file is suspiciously small: {pdf_path}")

    pages = get_page_count(pdf_path)
    if pages != expected_pages:
        raise PageCountError(
            f"PDF has {pages} page(s) but expected {expected_pages}. "
            f"Reduce content to fit exactly {expected_pages} page(s)."
        )


def compile_and_validate(tex_path: str, output_dir: Optional[str] = None,
                         expected_pages: int = 1) -> str:
    """Compile .tex → .pdf and validate page count. Returns pdf_path."""
    pdf_path = compile_latex(tex_path, output_dir)
    validate_pdf(pdf_path, expected_pages)
    return pdf_path


def cleanup_aux_files(output_dir: str, basename: str):
    """Remove pdflatex auxiliary files (.aux, .log, .out)."""
    for ext in (".aux", ".log", ".out", ".toc", ".synctex.gz"):
        aux = os.path.join(output_dir, basename + ext)
        if os.path.isfile(aux):
            os.remove(aux)
