"""Collect private publication text with resumable, report-only registry processing."""
import argparse
import copy
import time
import hashlib
import json
import re
import sys
import os
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import requests
import yaml
from bs4 import BeautifulSoup, ProcessingInstruction
from markdownify import markdownify
from pypdf import PdfReader
from publications_fulltext_report import write_report
from publications import abstract_text, normalize_doi, comparable

HERE = ROOT / 'private_data/fulltext'
SESSION = requests.Session()
SESSION.headers['User-Agent'] = 'CCI-fulltext-collector/1.0 (local research access check)'
LAST_REQUEST = 0.0
INTERVAL = 0.75


def get(url, **kwargs):
    global LAST_REQUEST
    for attempt in range(3):
        time.sleep(max(0, INTERVAL - (time.monotonic() - LAST_REQUEST)))
        LAST_REQUEST = time.monotonic()
        try:
            response = SESSION.get(url, timeout=(15, 35), stream=True, **kwargs)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                delay = response.headers.get('Retry-After', '')
                if delay and (not delay.isdigit() or int(delay) > 30):
                    response.raise_for_status()
                response.close()
                time.sleep(max(2 ** (attempt + 1), int(delay or 0)))
                continue
            try:
                response.raise_for_status()
            except requests.HTTPError:
                response.close()
                raise
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 20_000_000:
                    response.close()
                    raise ValueError('Response exceeds 20 MB collection limit')
                chunks.append(chunk)
            response._content = b''.join(chunks)
            response._content_consumed = True
            response.close()
            return response
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))


def convert_jats(xml):
    soup = BeautifulSoup(xml, 'xml')
    body = soup.find('body')
    if not body:
        raise ValueError('No article body in XML')
    selected = BeautifulSoup('<div></div>', 'html.parser')
    container = selected.div
    abstract = soup.find('abstract')
    if abstract:
        container.append(BeautifulSoup('<h2>Abstract</h2>', 'html.parser'))
        container.append(abstract)
    container.append(body)
    for item in list(container.find_all(string=lambda value: isinstance(value, ProcessingInstruction))):
        item.extract()
    for tag in container.find_all(['ref-list', 'ref']):
        tag.decompose()
    for tag in list(container.find_all('title')):
        tag.name = 'h' + str(min(6, 2 + len(tag.find_parents('sec'))))
    for tag in container.find_all(['xref', 'ext-link']):
        tag.unwrap()
    for tag in container.find_all(['fig', 'table-wrap']):
        tag.name = 'div'
    # Exclude bibliography; preserve captions and tables embedded in the body.
    return markdownify(str(container), heading_style='ATX')


def save(entry, text, suffix=''):
    if len(text.split()) < 15:
        raise ValueError('Too little readable text extracted')
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    target = HERE / 'markdown' / (entry['id'] + suffix + '-' + digest + '.md')
    target.parent.mkdir(exist_ok=True)
    header = (f"# {entry['title']}\n\nDOI: {entry['doi']}\n\n"
              f"Source: {entry['source_url']}\n\n"
              f"Extraction: {entry['extraction']}\n\n"
              f"Coverage: {entry['coverage']} — extraction requires review; supplements may be absent.\n\n---\n\n")
    atomic_write(target, header + text.strip() + '\n')
    return {'file': str(target.relative_to(HERE)), 'words': len(text.split()),
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


def collect(record):
    entry = {'id': record['id'], 'doi': record['doi'], 'title': record['metadata']['title'],
             'attempts': [], 'supplements': 'not_collected', 'access_basis': 'unconfirmed',
             'checked_at': datetime.now(timezone.utc).isoformat()}
    repository_abstract = None
    try:
        result = get('https://www.ebi.ac.uk/europepmc/webservices/rest/search',
                     params={'query': 'DOI:"' + record['doi'] + '"', 'format': 'json', 'resultType': 'core'}).json()
        hits = [r for r in result['resultList']['result'] if r.get('doi', '').lower() == record['doi']]
        for candidate in hits:
            if (candidate.get('abstractText') and
                    SequenceMatcher(None, comparable(candidate.get('title', '')), comparable(entry['title'])).ratio() >= 0.8):
                repository_abstract = candidate
                break
        hit = next((r for r in hits if r.get('isOpenAccess') == 'Y' and r.get('pmcid')), None)
        entry['europe_pmc'] = [{'pmcid': r.get('pmcid'), 'isOpenAccess': r.get('isOpenAccess')} for r in hits]
        entry['attempts'].append({'route': 'europe_pmc_search',
                                  'result': 'oa_xml_candidate' if hit else 'no_oa_xml_candidate'})
        if hit:
            url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/' + hit['pmcid'] + '/fullTextXML'
            xml = get(url).text
            parsed = BeautifulSoup(xml, 'xml')
            article_dois = [normalize_doi(node.get_text()) for node in parsed.find_all('article-id', attrs={'pub-id-type': 'doi'})]
            if record['doi'] not in article_dois:
                raise ValueError('XML article DOI missing or mismatched')
            text = convert_jats(xml)
            entry.update(source_url=url, extraction='Europe PMC JATS XML to Markdown',
                         coverage='full_article_body', access_basis='Europe PMC open-access subset',
                         licence=hit.get('license'))
            entry.update(save(entry, text))
            entry['attempts'].append({'route': 'europe_pmc_xml', 'result': 'success'})
    except (requests.RequestException, ValueError, KeyError) as exc:
        entry['attempts'].append({'route': 'europe_pmc', 'error': str(exc)})
    pdf_candidate = None
    if 'file' not in entry:
        try:
            response = get('https://doi.org/' + record['doi'])
            soup = BeautifulSoup(response.text, 'html.parser')
            meta = soup.find('meta', attrs={'name': re.compile('^citation_doi$', re.I)})
            entry['landing_url'] = response.url
            if meta and meta.get('content', '').lower().removeprefix('https://doi.org/') != record['doi']:
                raise ValueError('Publisher DOI mismatch')
            if not meta:
                raise ValueError('No publisher citation DOI; body extraction not attempted')
            pdf_meta = soup.find('meta', attrs={'name': 'citation_pdf_url'})
            if pdf_meta and pdf_meta.get('content'):
                candidate = urljoin(response.url, pdf_meta['content'])
                if urlparse(candidate).scheme == 'https' and urlparse(candidate).hostname in {'www.nature.com', 'link.springer.com'}:
                    pdf_candidate = candidate
            body = soup.select_one('.c-article-body')
            preview = 'preview of subscription content' in soup.get_text(' ', strip=True).lower()
            if preview:
                abstract = soup.select_one('#Abs1')
                if abstract:
                    abstract = abstract.find_parent('section') or abstract.parent
                    entry.update(source_url=response.url, extraction='Publisher HTML abstract to Markdown',
                                 coverage='abstract_only')
                    entry.update(save(entry, markdownify(str(abstract), heading_style='ATX')))
                entry['attempts'].append({'route': 'publisher_html', 'result': 'subscription_preview_only'})
            elif body and len(body.get_text(' ', strip=True).split()) > 1000:
                for heading in list(body.find_all(re.compile('^h[1-6]$'))):
                    if heading.name is None:
                        continue
                    if heading.get_text(' ', strip=True) in {'Similar content being viewed by others', 'Explore related subjects'}:
                        section = heading.find_parent('section')
                        if section and section is not body and section in body.descendants:
                            section.decompose()
                for tag in body.select('script, style, nav, button, form'):
                    tag.decompose()
                text = markdownify(str(body), heading_style='ATX')
                entry.update(source_url=response.url, extraction='Publisher HTML to Markdown',
                             coverage='article_body_candidate_needs_review')
                entry.update(save(entry, text))
                entry['attempts'].append({'route': 'publisher_html', 'result': 'body_extracted'})
            else:
                entry['attempts'].append({'route': 'publisher_html', 'result': 'no_full_article_body_identified'})
        except (requests.RequestException, ValueError) as exc:
            entry['attempts'].append({'route': 'publisher_html', 'error': str(exc)})
    pdf = HERE / 'pdf' / (record['id'] + '.pdf')
    if entry.get('coverage') in {None, 'abstract_only'} and not pdf.exists() and pdf_candidate:
        try:
            response = get(pdf_candidate)
            if not response.content[:1024].lstrip().startswith(b'%PDF-'):
                raise ValueError('PDF endpoint returned non-PDF content')
            pdf.parent.mkdir(exist_ok=True)
            pdf.write_bytes(response.content)
            entry['attempts'].append({'route': 'publisher_pdf', 'result': 'downloaded', 'source_url': pdf_candidate})
        except (requests.RequestException, ValueError) as exc:
            entry['attempts'].append({'route': 'publisher_pdf', 'error': str(exc)})
    if pdf.exists():
        try:
            reader = PdfReader(pdf)
            text = '\n\n'.join(f'## PDF page {i}\n\n{page.extract_text() or "[No text extracted]"}'
                               for i, page in enumerate(reader.pages, 1))
            pdf_entry = dict(entry, source_url='https://doi.org/' + record['doi'],
                             extraction='pypdf page text to Markdown', coverage='pdf_text_needs_layout_review')
            entry['pdf_comparison'] = save(pdf_entry, text, '-pdf')
            if entry.get('coverage') in {None, 'abstract_only'}:
                entry.update(source_url=pdf_entry['source_url'], extraction=pdf_entry['extraction'],
                             coverage=pdf_entry['coverage'], **entry['pdf_comparison'])
        except Exception as exc:
            entry['attempts'].append({'route': 'existing_pdf', 'error': str(exc)})
    if 'file' not in entry:
        private = ROOT / 'private_data/publication-abstracts.json'
        abstract = None
        if private.exists():
            abstract = next((r.get('abstract') for r in json.loads(private.read_text())['abstracts']
                             if r['id'] == record['id'] and r.get('doi') == record['doi']
                             and r.get('status') in {'publicly_displayable', 'private_only'}), None)
        if abstract and abstract.get('text'):
            entry.update(source_url=abstract.get('source_url') or 'https://doi.org/' + record['doi'],
                         extraction='Previously retrieved DOI metadata abstract', coverage='abstract_only')
            entry.update(save(entry, abstract['text']))
            entry['attempts'].append({'route': 'saved_doi_abstract', 'result': 'success'})
        elif repository_abstract and abstract_text(repository_abstract['abstractText']):
            entry.update(source_url='https://europepmc.org/article/' + repository_abstract['source'] + '/' + repository_abstract['id'],
                         extraction='Europe PMC DOI-matched metadata abstract', coverage='abstract_only')
            entry.update(save(entry, abstract_text(repository_abstract['abstractText'])))
            entry['attempts'].append({'route': 'europe_pmc_abstract', 'result': 'success'})
        else:
            entry['attempts'].append({'route': 'saved_doi_abstract', 'result': 'not_available'})
            for provider in ['crossref', 'doi_csl']:
                try:
                    if provider == 'crossref':
                        data = get('https://api.crossref.org/works/' + record['doi']).json()['message']
                    else:
                        data = get('https://doi.org/' + record['doi'], headers={'Accept': 'application/vnd.citationstyles.csl+json'}).json()
                    if normalize_doi(data.get('DOI')) != record['doi']:
                        raise ValueError('Abstract DOI mismatch')
                    title = data.get('title', '')
                    title = title[0] if isinstance(title, list) and title else title
                    if not isinstance(title, str) or SequenceMatcher(None, comparable(title), comparable(entry['title'])).ratio() < 0.8:
                        raise ValueError('Abstract title requires identity review')
                    text = abstract_text(data.get('abstract'))
                    if not text:
                        entry['attempts'].append({'route': provider + '_abstract', 'result': 'not_available'})
                        continue
                    entry.update(source_url='https://doi.org/' + record['doi'],
                                 extraction=provider + ' DOI metadata abstract', coverage='abstract_only')
                    entry.update(save(entry, text))
                    entry['attempts'].append({'route': provider + '_abstract', 'result': 'success'})
                    break
                except (requests.RequestException, ValueError, KeyError) as exc:
                    entry['attempts'].append({'route': provider + '_abstract', 'error': str(exc)})
            if 'file' not in entry:
                entry['coverage'] = 'unavailable'
    return entry


RANK = {'unavailable': 0, 'abstract_only': 1, 'pdf_text_needs_layout_review': 2,
        'article_body_candidate_needs_review': 2, 'full_article_body': 3}


def atomic_write(path, text):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)


def valid_saved(entry):
    if not entry or not entry.get('file'):
        return False
    path = (HERE / entry['file']).resolve()
    return (path.is_relative_to(HERE.resolve()) and path.is_file()
            and hashlib.sha256(path.read_bytes()).hexdigest() == entry.get('sha256'))


def preserve_best(previous, new):
    if valid_saved(previous) and RANK.get(previous.get('coverage'), 0) >= RANK.get(new.get('coverage'), 0):
        kept = copy.deepcopy(previous)
        kept['last_check'] = {'checked_at': new.get('checked_at'), 'coverage': new.get('coverage'),
                              'attempts': new.get('attempts', []), 'retained_previous': True}
        return kept
    if previous:
        new['previous_checks'] = previous.get('previous_checks', []) + [
            {k: previous[k] for k in ('checked_at', 'coverage', 'file', 'sha256', 'attempts', 'last_check') if k in previous}]
    return new


def main(argv=None):
    global HERE, INTERVAL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doi', action='append', help='Limit to a DOI; repeatable')
    parser.add_argument('--limit', type=int, help='Limit selected records, in registry order')
    parser.add_argument('--refresh', action='store_true', help='Recheck saved results; retain equal or better existing text')
    parser.add_argument('--retry-incomplete', action='store_true', help='Recheck abstracts and unavailable results')
    parser.add_argument('--report-only', action='store_true', help='Regenerate summaries without network requests')
    parser.add_argument('--interval', type=float, default=0.75, help='Minimum seconds between requests (at least 0.5)')
    parser.add_argument('--output', type=Path, default=HERE, help='Output directory inside private_data')
    args = parser.parse_args(argv)
    HERE = args.output.resolve()
    if not HERE.is_relative_to((ROOT / 'private_data').resolve()):
        parser.error('Output must be inside private_data, which is excluded from Git and Jekyll')
    if args.interval < 0.5 or (args.limit is not None and args.limit < 1):
        parser.error('Interval must be at least 0.5 and limit must be positive')
    INTERVAL = args.interval
    HERE.mkdir(parents=True, exist_ok=True)
    manifest_path = HERE / 'manifest.json'
    # Import the pilot results once, without rewriting or deleting their files.
    seed = manifest_path if manifest_path.exists() else HERE / 'pilot-manifest.json'
    manifest = json.loads(seed.read_text()) if seed.exists() else {'articles': []}
    saved = {r['id']: r for r in manifest['articles']}
    records = yaml.safe_load((ROOT / '_publications/registry.yml').read_text())['publications']
    if args.doi:
        requested = {normalize_doi(doi) for doi in args.doi}
        unknown = requested - {r['doi'] for r in records}
        if unknown:
            parser.error('Unknown DOI: ' + ', '.join(sorted(unknown)))
        records = [r for r in records if r['doi'] in requested]
    if args.limit:
        records = records[:args.limit]
    manifest['selected_count'] = len(records)
    manifest['schema_version'] = 1
    manifest['collector_version'] = 1
    for index, record in enumerate(records, 1):
        if args.report_only:
            break
        previous = saved.get(record['id'])
        incomplete = not previous or previous.get('coverage') in {'abstract_only', 'unavailable'}
        skip = previous and not args.refresh and not (args.retry_incomplete and incomplete)
        if skip and (valid_saved(previous) or previous.get('coverage') == 'unavailable'):
            print(f"[{index}/{len(records)}] {record['doi']} resumed: {previous['coverage']}", flush=True)
            continue
        try:
            new = collect(record)
        except Exception as exc:
            new = {'id': record['id'], 'doi': record['doi'], 'title': record['metadata']['title'],
                   'coverage': 'unavailable', 'checked_at': datetime.now(timezone.utc).isoformat(),
                   'attempts': [{'route': 'collector', 'error': f'{type(exc).__name__}: {exc}'}]}
        saved[record['id']] = preserve_best(previous, new)
        manifest['articles'] = list(saved.values())
        manifest['updated_at'] = datetime.now(timezone.utc).isoformat()
        atomic_write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
        write_report(manifest, HERE)
        print(f"[{index}/{len(records)}] {record['doi']} {saved[record['id']]['coverage']}", flush=True)
    manifest['articles'] = list(saved.values())
    manifest['updated_at'] = datetime.now(timezone.utc).isoformat()
    atomic_write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    write_report(manifest, HERE)
    print('Summary:', json.dumps({key: sum(r['coverage'] == key for r in saved.values()) for key in RANK}), flush=True)


if __name__ == '__main__':
    main()
