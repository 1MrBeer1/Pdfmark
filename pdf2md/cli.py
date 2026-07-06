"""Command-line interface for pdf2md."""

from __future__ import annotations

import argparse
from pathlib import Path
from tqdm import tqdm

from .config import ConversionError, DependencyError, resolve_output_paths, setup_logger
from .converter import convert_pdf
from .splitter import split_markdown

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_DEPENDENCY = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert PDF to Markdown with images and tables.")
    parser.add_argument("input", help="Input PDF path")
    parser.add_argument("--out", dest="out", help="Output Markdown path")
    parser.add_argument("--assets", dest="assets", help="Assets directory path")
    parser.add_argument("--format", dest="md_format", choices=["github", "gfm", "obsidian"], default="github")
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI for images/tables/OCR")
    parser.add_argument("--ocr", choices=["auto", "off", "always"], default="auto")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--split", action="store_true", help="Split the output Markdown by H1 headings")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = setup_logger(verbose=args.verbose)

    progress = None
    try:
        total_pages = _get_page_count(args.input, args.max_pages)
        progress = tqdm(total=total_pages, desc="Pages", unit="page")

        report = convert_pdf(
            input_path=args.input,
            out_path=args.out,
            assets_dir=args.assets,
            md_format=args.md_format,
            dpi=args.dpi,
            ocr=args.ocr,
            max_pages=args.max_pages,
            keep_temp=args.keep_temp,
            verbose=args.verbose,
            logger=logger,
            progress=progress,
        )
    except DependencyError as exc:
        logger.error(str(exc))
        return EXIT_DEPENDENCY
    except ConversionError as exc:
        logger.error(str(exc))
        return EXIT_ERROR
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return EXIT_ERROR
    finally:
        if progress is not None:
            progress.close()

    print(report.summary_text())
    if args.split:
        out_path, _ = resolve_output_paths(
            Path(args.input),
            Path(args.out) if args.out else None,
            Path(args.assets) if args.assets else None,
        )
        split_files = split_markdown(out_path)
        print("split files:")
        for split_file in split_files:
            print(f"- {split_file}")
    return EXIT_OK


def _get_page_count(input_path: str, max_pages: int | None) -> int | None:
    try:
        import fitz  # type: ignore
    except Exception:
        return None
    try:
        doc = fitz.open(input_path)
    except Exception:
        return None
    try:
        pages = doc.page_count
    finally:
        doc.close()
    if max_pages:
        pages = min(pages, max_pages)
    return pages


if __name__ == "__main__":
    raise SystemExit(main())
