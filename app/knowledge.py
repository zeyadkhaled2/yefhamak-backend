"""Import trusted UTF-8 .md/.txt documents: python -m app.knowledge --help."""
import argparse
from pathlib import Path
from uuid import UUID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seller-id', required=True, type=UUID)
    parser.add_argument('--file', required=True, type=Path)
    parser.add_argument('--title', required=True)
    args = parser.parse_args()
    if args.file.suffix.lower() not in {'.md', '.txt'} or args.file.stat().st_size > 400_000:
        parser.error('Use a UTF-8 Markdown/text file no larger than 400 KB')
    from app.db.session import SessionLocal
    from app.services.knowledge import import_document
    with SessionLocal() as db:
        count = import_document(db, args.seller_id, args.file.name, args.title, args.file.read_text(encoding='utf-8'))
    print(f'Imported {count} passages from {args.file.name}')


if __name__ == '__main__':
    main()
