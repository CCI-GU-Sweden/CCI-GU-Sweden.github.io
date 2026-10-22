"""Generate human-readable and spreadsheet retrieval summaries from the manifest."""
import csv
import io
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / 'private_data/fulltext'
STATUS = {
    'full_article_body': ('Article body retrieved', 'Review methods and collect supplements'),
    'article_body_candidate_needs_review': ('Article body candidate', 'Verify completeness against PDF; collect supplements'),
    'pdf_text_needs_layout_review': ('PDF text extracted', 'Check reading order and completeness; collect supplements'),
    'abstract_only': ('Abstract only', 'Obtain full text; detailed methods may be missing'),
    'unavailable': ('No usable text', 'Try publisher API or supply a permitted local copy'),
}


def write_report(manifest, destination=HERE):
    destination = Path(destination)
    rows = []
    for entry in manifest['articles']:
        status, followup = STATUS.get(entry['coverage'], (entry['coverage'], 'Review retrieval result'))
        rows.append({
            'id': entry['id'], 'doi': entry['doi'], 'title': entry['title'],
            'coverage': entry['coverage'], 'result': status,
            'source': entry.get('extraction', 'None'),
            'words': entry.get('words', 0), 'markdown': entry.get('file', ''),
            'pdf_comparison': entry.get('pdf_comparison', {}).get('file', ''),
            'supplements': entry.get('supplements', 'unknown'),
            'technology_evidence_review': 'Not assessed',
            'follow_up': followup,
            'attempts': json.dumps(entry.get('attempts', []), ensure_ascii=False),
            'checked_at': entry.get('checked_at', manifest.get('retrieved_at', 'unknown')),
            'latest_check': json.dumps(entry.get('last_check', {}), ensure_ascii=False),
        })
    fields = ['id', 'doi', 'title', 'coverage', 'result', 'source', 'words', 'markdown',
              'pdf_comparison', 'supplements', 'technology_evidence_review', 'follow_up', 'attempts',
              'checked_at', 'latest_check']
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    (destination / 'retrieval-summary.csv').write_text(output.getvalue())
    counts = {key: sum(r['coverage'] == key for r in rows) for key in STATUS}
    lines = ['# Retrieval success table', '',
             f"Manifest run: {manifest.get('updated_at', manifest.get('retrieved_at', 'unknown'))}", '',
             f"{len(rows)} articles: {counts['full_article_body']} article bodies, "
             f"{counts['article_body_candidate_needs_review']} body candidates, "
             f"{counts['pdf_text_needs_layout_review']} PDF-only extractions, "
             f"{counts['abstract_only']} abstract-only, {counts['unavailable']} unavailable.", '',
             'Retrieval success describes available text, not whether technology labels are supported. '
             'Technology evidence has not yet been assessed. Article bodies may lack supplementary methods. '
             'Only recorded attempts are listed in the CSV; an untried route is not a failed route.', '',
             '| Article | Result | Source | Words | Supplements | Follow-up |',
             '| --- | --- | --- | ---: | --- | --- |']
    def escape(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    for row in rows:
        article = f"[{escape(row['title'])}](https://doi.org/{row['doi']})"
        if row['markdown']:
            article += f" ([text]({row['markdown']}))"
        lines.append('| ' + ' | '.join([article, escape(row['result']), escape(row['source']),
                                        str(row['words']), escape(row['supplements']),
                                        escape(row['follow_up'])]) + ' |')
    lines.extend(['', 'Spreadsheet version: [retrieval-summary.csv](retrieval-summary.csv).', ''])
    (destination / 'retrieval-summary.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    write_report(json.loads((HERE / 'manifest.json').read_text()))
