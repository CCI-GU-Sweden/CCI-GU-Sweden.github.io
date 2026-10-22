"""Classify CCI involvement offline using a private staff roster and author lists."""
import argparse
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata

from publications import ROOT, REGISTRY, VOCABULARY, effective_metadata, read_registry, validate, write_json, write_text

STAFF = ROOT / 'private_data/cci-staff.yml'
REPORT = ROOT / 'private_data/cci-involvement'
VALUES = {'scientific-collaboration', 'service-provision'}


def normalized_name(value):
    value = unicodedata.normalize('NFKD', value).casefold()
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^\w\s]', ' ', value).split())


def staff_index(roster):
    if roster.get('schema_version') != 1 or not isinstance(roster.get('staff'), list):
        raise ValueError('Expected staff roster schema_version: 1 and staff list')
    index, ids = {}, set()
    for staff in roster['staff']:
        if not staff.get('id') or staff['id'] in ids:
            raise ValueError('Missing or duplicate staff ID')
        ids.add(staff['id'])
        for period in staff['membership_periods']:
            start, end = period['start_year'], period['end_year']
            if type(start) is not int or (end is not None and (type(end) is not int or end < start)):
                raise ValueError(f"Invalid membership years: {staff['id']}")
        for name in [staff['name'], *staff.get('name_variants', [])]:
            key = normalized_name(name)
            if len(key.split()) < 2 or any(len(token) == 1 for token in key.split()):
                raise ValueError(f"Staff names must be full names, not initials: {name}")
            index.setdefault(key, {})[staff['id']] = staff
    return index


def identify(record, index):
    metadata = effective_metadata(record)
    matches, review = [], []
    year = metadata['year']
    for author in metadata['authors']:
        candidates = list(index.get(normalized_name(author), {}).values())
        # Do not resolve a shared full name by dates alone.
        if len(candidates) > 1:
            review.append({'author': author, 'reason': 'name shared by multiple roster entries'})
            continue
        for staff in candidates:
            periods = [period for period in staff['membership_periods']
                       if period['start_year'] <= year and
                       (period['end_year'] is None or year <= period['end_year'])]
            if periods:
                matches.append({'staff_id': staff['id'], 'staff_name': staff['name'],
                                'author': author, 'publication_year': year,
                                'membership_period': periods[0]})
            else:
                review.append({'author': author, 'staff_id': staff['id'],
                               'reason': 'outside recorded membership years or membership dates missing'})
    return {'id': record['id'], 'doi': record['doi'], 'title': metadata['title'], 'year': year,
            'cci_involvement': 'scientific-collaboration' if matches else 'service-provision',
            'basis': 'staff_author_and_year_match' if matches else 'default_no_confirmed_roster_match',
            'matches': matches, 'review_notes': review}


def classify(registry, roster):
    index = staff_index(roster)
    result = copy.deepcopy(registry)
    rows = []
    for record in result['publications']:
        row = identify(record, index)
        # Explicitly curated corrections can be protected from subsequent runs.
        if record.get('cci_involvement_override') is not None:
            value = record['cci_involvement_override']
            if value not in VALUES:
                raise ValueError(f"Invalid involvement override: {record['id']}")
            row['suggested_cci_involvement'] = row['cci_involvement']
            row['cci_involvement'] = value
            row['basis'] = 'curator_override'
        record['cci_involvement'] = row['cci_involvement']
        rows.append(row)
    return result, rows


def write_reports(rows, staff_path, prefix):
    counts = {value: sum(r['cci_involvement'] == value for r in rows) for value in sorted(VALUES)}
    write_json(prefix.with_suffix('.json'), {
        'schema_version': 1, 'staff_roster_sha256': hashlib.sha256(staff_path.read_bytes()).hexdigest(),
        'policy': 'Exact normalized full names/approved variants plus inclusive publication-year membership; otherwise service provision by curator instruction.',
        'summary': counts, 'publications': rows})
    output = io.StringIO(newline='')
    fields = ['doi', 'title', 'year', 'cci_involvement', 'basis', 'matched_authors', 'review_notes']
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    lines = ['# CCI involvement review', '',
             'Service Provision is the requested default when the current roster yields no confirmed match. '
             'It does not independently verify acknowledgements. Former staff can be added and this report rerun.', '',
             '| Article | Year | CCI involvement | Matching staff authors | Basis |',
             '| --- | ---: | --- | --- | --- |']
    for row in rows:
        authors = '; '.join(m['author'] for m in row['matches'])
        writer.writerow({**{key: row[key] for key in fields if key in row},
                         'matched_authors': authors, 'review_notes': json.dumps(row['review_notes'], ensure_ascii=False)})
        title = row['title'].replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| [{title}](https://doi.org/{row['doi']}) | {row['year']} | {row['cci_involvement']} | {authors or '—'} | {row['basis']} |")
    write_text(prefix.with_suffix('.csv'), output.getvalue())
    write_text(prefix.with_suffix('.md'), '\n'.join(lines) + '\n')
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staff', type=Path, default=STAFF)
    parser.add_argument('--registry', type=Path, default=REGISTRY)
    parser.add_argument('--report', type=Path, default=REPORT)
    parser.add_argument('--apply', action='store_true', help='Write cci_involvement to the registry; otherwise report only')
    args = parser.parse_args(argv)
    if not args.report.resolve().is_relative_to((ROOT / 'private_data').resolve()):
        parser.error('Evidence reports must remain under private_data')
    registry, rows = classify(read_registry(args.registry), read_registry(args.staff))
    validate(registry, read_registry(VOCABULARY))
    counts = write_reports(rows, args.staff, args.report)
    if args.apply:
        import yaml
        write_text(args.registry, yaml.safe_dump(registry, sort_keys=False, allow_unicode=True, width=100))
    print(json.dumps({'applied': args.apply, **counts}, indent=2))


if __name__ == '__main__':
    main()
