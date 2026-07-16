import os
import sys
from pathlib import Path
from pypdf import PdfReader


def convert_pdfs():
    # Define potential data directory paths
    script_dir = Path(__file__).resolve().parent

    # Path 1: relative to active backend/
    path1 = script_dir / "data" / "scheme_docs"
    # Path 2: relative to sibling git repo backend/
    path2 = (
        script_dir.parent
        / "Government-Scheme-Financial-Inclusion-Navigator-"
        / "backend"
        / "data"
        / "scheme_docs"
    )

    docs_dir = None
    if path1.exists() and any(path1.glob("*.pdf")):
        docs_dir = path1
    elif path2.exists() and any(path2.glob("*.pdf")):
        docs_dir = path2
    else:
        print(
            "Error: Could not locate a 'data/scheme_docs/' directory containing any PDF files."
        )
        print(f"Looked in:\n1. {path1}\n2. {path2}")
        sys.exit(1)

    print(f"Located PDF directory at: {docs_dir.resolve()}")

    # List all .pdf files
    pdf_files = list(docs_dir.glob("*.pdf"))

    total_found = len(pdf_files)
    total_converted = 0
    total_skipped = 0
    empty_or_short = []

    for pdf_path in pdf_files:
        txt_path = pdf_path.with_suffix(".txt")

        # Skip if txt already exists
        if txt_path.exists():
            total_skipped += 1
            print(f"Skipped: {pdf_path.name} (TXT already exists)")

            # Check length of existing text files just to verify
            try:
                with open(txt_path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                if len(content.strip()) < 50:
                    empty_or_short.append((pdf_path.name, len(content.strip())))
            except Exception:
                pass
            continue

        print(f"Converting: {pdf_path.name}...")

        try:
            reader = PdfReader(pdf_path)
            extracted_text = []

            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    extracted_text.append(text)

            full_text = "\n".join(extracted_text).strip()

            # Save the text
            with open(txt_path, "w", encoding="utf-8") as fh:
                fh.write(full_text)

            total_converted += 1

            # Verify length
            if len(full_text) < 50:
                empty_or_short.append((pdf_path.name, len(full_text)))

        except Exception as e:
            print(f"Error converting {pdf_path.name}: {e}")

    print("\n" + "=" * 50)
    print("PDF CONVERSION SUMMARY")
    print("=" * 50)
    print(f"Total PDFs found:     {total_found}")
    print(f"Total PDFs converted: {total_converted}")
    print(f"Total PDFs skipped:   {total_skipped}")

    if empty_or_short:
        print(
            "\n[WARNING] The following files had empty or extremely short extracted text (< 50 chars):"
        )
        for filename, length in empty_or_short:
            print(
                f"  - {filename} ({length} characters) -> Likely scanned image without text layer."
            )
    else:
        print("\nAll extracted text files are valid (> 50 characters).")
    print("=" * 50)


if __name__ == "__main__":
    convert_pdfs()
