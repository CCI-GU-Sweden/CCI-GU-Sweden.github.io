"""Preview or apply a curated, year-scoped technology assignment file offline."""
import argparse
import copy
import json
from pathlib import Path

from publications import REGISTRY, VOCABULARY, effective_metadata, read_registry, save_registry, validate


def apply_assignments(registry, vocabulary, assignments, year):
    if assignments.get('schema_version') != 1 or assignments.get('year') != year:
        raise ValueError('Assignment schema/year does not match the requested year')
    rows = assignments.get('publications')
    if not isinstance(rows, list):
        raise ValueError('Expected a publications assignment list')
    known = {entry['id'] for entry in vocabulary['technologies']}
    records = {record['id']: record for record in registry['publications']}
    seen = set()
    for row in rows:
        record_id = row['id']
        if record_id in seen or record_id not in records:
            raise ValueError(f'Duplicate or unknown publication ID: {record_id}')
        seen.add(record_id)
        record = records[record_id]
        if effective_metadata(record)['year'] != year or row.get('doi') != record['doi']:
            raise ValueError(f'Publication year/DOI mismatch: {record_id}')
        tags = row.get('technologies')
        if (not isinstance(tags, list) or any(not isinstance(t, str) for t in tags)
                or len(tags) != len(set(tags)) or set(tags) - known):
            raise ValueError(f'Invalid or unknown technology IDs: {record_id}')
        if record.get('technologies') and set(record['technologies']) != set(tags):
            raise ValueError(f'Existing labels differ; curate this record explicitly before replacing: {record_id}')
    result = copy.deepcopy(registry)
    by_id = {row['id']: row for row in rows}
    for record in result['publications']:
        if record['id'] in by_id:
            record['technologies'] = by_id[record['id']]['technologies'][:]
            # Local trials stay pending until the curator approves their final labels.
    validate(result, vocabulary)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('assignments', type=Path, help='Curated JSON assignment plan, not raw model output')
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--registry', type=Path, default=REGISTRY)
    parser.add_argument('--vocabulary', type=Path, default=VOCABULARY)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    assignments = json.loads(args.assignments.read_text())
    result = apply_assignments(read_registry(args.registry), read_registry(args.vocabulary), assignments, args.year)
    if args.apply:
        save_registry(args.registry, result)
    print(json.dumps({'applied': args.apply, 'year': args.year, 'records': len(assignments['publications']),
                      'tagged_records': sum(bool(r['technologies']) for r in assignments['publications'])}, indent=2))


if __name__ == '__main__':
    main()
