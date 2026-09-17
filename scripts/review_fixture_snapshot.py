"""Read-only source/current manifest. Does not import or overwrite shared IDs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml


def inventory(root: Path) -> dict:
    docs = {}
    for path in sorted(root.rglob('*.yaml')):
        raw = path.read_bytes()
        doc = yaml.safe_load(raw)
        if not isinstance(doc, dict) or not doc.get('kind') or not doc.get('id'):
            continue
        if doc['id'] in docs:
            raise ValueError(f"duplicate document id: {doc['id']}")
        docs[doc['id']] = dict(path=path.relative_to(root).as_posix(), kind=doc['kind'],
                              sha256=hashlib.sha256(raw).hexdigest(),
                              variants=sorted(v['id'] for v in doc.get('variants', [])))
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source, current = inventory(args.source), inventory(args.current)
    shared = sorted(source.keys() & current.keys())
    report = dict(source=source, current=current, shared_ids=shared,
                  changed_ids=[key for key in shared if source[key]['sha256'] != current[key]['sha256']],
                  current_only_variants={key:sorted(set(current[key]['variants'])-set(source.get(key, {}).get('variants', [])))
                                         for key in current if current[key]['variants']},
                  promotion_status='blocked_pending_model_validation')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
