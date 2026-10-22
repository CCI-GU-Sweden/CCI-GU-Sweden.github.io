"""Check private model findings against the registry, vocabulary and saved text."""
import argparse
import hashlib
import json
from pathlib import Path

from publications import ROOT, REGISTRY, VOCABULARY, effective_metadata, read_registry


def validate_findings(findings, registry, vocabulary, manifest, text_root, year):
    expected = {r['id']: r for r in registry['publications'] if effective_metadata(r)['year'] == year}
    if not isinstance(findings, list) or len(findings) != len(expected) or {r['id'] for r in findings} != set(expected):
        raise ValueError(f'Findings must cover exactly the {len(expected)} unique records from {year}')
    known = {tag['id'] for tag in vocabulary['technologies']}
    sources = {r['id']: r for r in manifest['articles']}
    text_root = Path(text_root).resolve()
    references = 0
    for row in findings:
        record, source = expected[row['id']], sources[row['id']]
        if row['doi'] != record['doi'] or row.get('effective_year', year) != year:
            raise ValueError(f"Record identity/year mismatch: {row['id']}")
        if row.get('coverage') != source['coverage']:
            raise ValueError(f"Source coverage mismatch: {row['id']}")
        if row.get('review_status') != 'proposed':
            raise ValueError(f"Expected proposed findings: {row['id']}")
        for field in ['proposed_technology_ids', 'discussed_technology_ids']:
            tags = row.get(field, [])
            if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags) or len(tags) != len(set(tags)) or set(tags) - known:
                raise ValueError(f"Invalid technology IDs: {row['id']}")
        if not source.get('file'):
            if row.get('input_file') or row.get('input_sha256') or row.get('proposed_technology_ids') or row.get('discussed_technology_ids'):
                raise ValueError(f"Unavailable text cannot support assignments: {row['id']}")
            continue
        if row.get('input_file') != source['file']:
            raise ValueError(f"Input does not match collected file: {row['id']}")
        path = (text_root / row['input_file']).resolve()
        if not path.is_relative_to(text_root):
            raise ValueError('Input path escapes private text collection')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row.get('input_sha256') or digest != source['sha256']:
            raise ValueError(f"Input checksum mismatch: {row['id']}")
        lines = path.read_text().splitlines()
        supported_tags = set()

        def check(node):
            nonlocal references
            if isinstance(node, dict):
                for field in ['proposed_tags', 'discussed_tags']:
                    if field in node:
                        tags = node[field]
                        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags) or set(tags) - known:
                            raise ValueError(f"Invalid finding-level tags: {row['id']}")
                        if isinstance(node.get('evidence'), dict) and node['evidence'].get('excerpt'):
                            supported_tags.update(tags)
                if node.get('excerpt'):
                    line = node.get('line')
                    if (node.get('file') != row['input_file'] or type(line) is not int or
                            not 1 <= line <= len(lines) or node['excerpt'] not in lines[line - 1]):
                        raise ValueError(f"Excerpt/line mismatch: {row['id']}")
                    references += 1
                for child in node.values():
                    check(child)
            elif isinstance(node, list):
                for child in node:
                    check(child)

        before_references = references
        check(row.get('findings', {}))
        if (row.get('proposed_technology_ids') or row.get('discussed_technology_ids')) and references == before_references:
            raise ValueError(f"Positive labels require source evidence: {row['id']}")
        declared = set(row.get('proposed_technology_ids', []) + row.get('discussed_technology_ids', []))
        if declared - supported_tags:
            raise ValueError(f"Labels lack a tagged supporting finding: {row['id']}: {sorted(declared - supported_tags)}")
    return {'year': year, 'records': len(findings), 'verified_references': references}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('findings', type=Path)
    parser.add_argument('--year', type=int, required=True)
    args = parser.parse_args(argv)
    result = validate_findings(json.loads(args.findings.read_text()), read_registry(REGISTRY), read_registry(VOCABULARY),
                               json.loads((ROOT / 'private_data/fulltext/manifest.json').read_text()),
                               ROOT / 'private_data/fulltext', args.year)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
