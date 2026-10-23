"""Import, check, curate, and export CCI publications. No deployment operations."""

from __future__ import annotations

import argparse
import copy
import csv
from datetime import date
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import quote, unquote
import uuid
import xml.etree.ElementTree as ET

from habanero import Crossref
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "_publications/registry.yml"
VOCABULARY = ROOT / "_publications/vocabulary.yml"
CACHE = ROOT / ".local/publications-cache"
REPORT = ROOT / "private_data/publications-import-report.json"
OUTPUT = ROOT / "assets/data/publications.json"
UPDATES = ROOT / "private_data/doi-updates.json"
ABSTRACT_STORE = ROOT / "private_data/publication-abstracts.json"
FIELDS = {"title", "authors", "authors_text", "journal", "year", "publication_url", "type"}


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))).strip()


def normalize_doi(value):
    value = str(value or "").strip().replace("\\:", ":")
    if not value or value.lower() in {"n/a", "none", "-"}:
        return None
    # Markdown DOI links, including balanced parentheses within their targets.
    link = re.fullmatch(r"\[.*\]\((.*)\)", value)
    if link:
        value = link[1]
    value = unquote(re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I))
    # The supplied tables sometimes terminate a DOI with citation punctuation.
    value = value.strip().rstrip(".,;")
    if not re.fullmatch(r"10\.\d{4,9}/[^\s<>]+", value, flags=re.I):
        raise ValueError(f"Invalid DOI: {value!r}")
    return value.lower()


def safe_url(value):
    return isinstance(value, str) and bool(re.match(r"^https?://[^\s/]+(?:/[^\s]*)?$", value))


def normalize_pmid(value):
    value = str(value or "").strip()
    link = re.fullmatch(r"\[.*\]\((.*)\)", value)
    if link:
        value = link[1]
    value = re.sub(r"^(?:pmid:\s*|https?://pubmed\.ncbi\.nlm\.nih\.gov/)", "", value, flags=re.I).rstrip("/")
    if not re.fullmatch(r"[1-9]\d*", value):
        raise ValueError(f"Invalid PMID: {value!r}")
    return value


def parse_identifier(value):
    text = str(value or "").strip()
    target = re.fullmatch(r"\[.*\]\((.*)\)", text)
    target = target[1] if target else text
    if re.match(r"^(?:pmid:|https?://pubmed\.ncbi\.nlm\.nih\.gov/)", target, re.I):
        return None, normalize_pmid(text)
    return normalize_doi(text), None


def identifier(doi, citation):
    key = doi or (f"pmid:{citation['pmid']}" if citation.get("pmid") else
                  f"{citation['title']}|{citation['authors_text']}|{citation['year']}")
    return "cci-" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex


def read_tables(paths):
    citations = []
    for path in paths:
        count = 0
        columns, section_year = None, None
        aliases = {"author": "authors_text", "authors": "authors_text", "year": "year",
                   "title": "title", "journal": "journal", "source": "journal",
                   "article": "citation_text", "doi": "doi", "identifier": "doi",
                   "doi status": "doi_status"}
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.lstrip().startswith("|"):
                if line.strip():
                    columns = None
                heading = re.match(r"^#{1,6}\s+(.+)", line)
                if heading:
                    year = re.fullmatch(r"(20\d{2})", heading[1].strip())
                    section_year = int(year[1]) if year else None
                continue
            row_text = line.strip()[1:]
            if row_text.endswith("|"):
                row_text = row_text[:-1]
            cells = [clean(c) for c in re.split(r"(?<!\\)\|", row_text)]
            if all(re.fullmatch(r":?-+:?", c) for c in cells):
                continue
            if {"doi", "identifier"} & {c.lower() for c in cells}:
                columns = [aliases.get(c.lower()) for c in cells]
                recognized = [c for c in columns if c]
                if len(recognized) != len(set(recognized)):
                    raise ValueError(f"Repeated table column: {path.name}:{line_number}")
                continue
            if columns is not None:
                if len(cells) == len(columns) + 1 and cells[0].isdigit():
                    cells = cells[1:]
                if len(cells) != len(columns):
                    raise ValueError(f"Unsupported table row: {path.name}:{line_number}")
                values = {key: value for key, value in zip(columns, cells) if key}
                authors, title, journal = (values.get(k, "") for k in ("authors_text", "title", "journal"))
                raw_doi = values.get("doi", "")
                raw_year = values.get("year")
                if raw_year and not re.fullmatch(r"20\d{2}", raw_year):
                    raise ValueError(f"Invalid year: {path.name}:{line_number}")
                year = int(raw_year) if raw_year else section_year
            else:
                # Compatibility with the original five-column and numbered tables.
                if not any(re.fullmatch(r"20\d{2}", c) for c in cells):
                    continue
                if len(cells) == 6 and cells[0].isdigit():
                    cells = cells[1:]
                if len(cells) != 5 or not re.fullmatch(r"20\d{2}", cells[1]):
                    raise ValueError(f"Unsupported table row: {path.name}:{line_number}")
                authors, year, title, journal, raw_doi = cells
                year = int(year)
                values = {}
            if not raw_doi and not (authors and title and journal and year):
                raise ValueError(f"Missing DOI or complete manual citation: {path.name}:{line_number}")
            # One source table appends a preprint disclaimer inside the DOI cell.
            doi_text = re.sub(r"\s+This content is a preprint.*$", "", raw_doi, flags=re.I)
            try:
                doi, pmid = parse_identifier(doi_text)
                error = None
            except ValueError as exc:
                doi, pmid, error = None, None, str(exc)
            if not doi and not pmid and not (authors and title and journal and year):
                raise ValueError(f"Valid DOI/PMID or complete manual citation required: {path.name}:{line_number}: {error or raw_doi}")
            citations.append({
                "file": path.name, "line": line_number,
                "title": title, "authors_text": authors, "journal": journal,
                "year": year, "original_doi": raw_doi,
                "doi": doi, "doi_error": error,
                "doi_warning": "Preprint disclaimer removed from DOI cell" if doi_text != raw_doi else None,
            })
            if pmid:
                citations[-1]["pmid"] = pmid
            if values.get("doi_status"):
                if values["doi_status"] != "confirmed-unavailable" or doi:
                    raise ValueError(f"Invalid DOI status: {path.name}:{line_number}")
                citations[-1]["doi_status"] = values["doi_status"]
            if values.get("citation_text"):
                citations[-1]["citation_text"] = values["citation_text"]
            count += 1
        if not count:
            raise ValueError(f"No publication rows found in {path}")
    return citations


def import_citations(citations, registry=None):
    registry = copy.deepcopy(registry or {"schema_version": 1, "publications": []})
    records = registry["publications"]
    by_doi = {r["doi"]: r for r in records if r["doi"]}
    by_pmid = {r["pmid"]: r for r in records if r.get("pmid")}
    by_id = {r["id"]: r for r in records}
    by_source = {(c["file"], c["line"]): r for r in records for c in r["original_citations"]}
    for citation in citations:
        doi = citation["doi"]
        pmid = citation.get("pmid")
        record_id = identifier(doi, citation)
        source_record = by_source.get((citation["file"], citation["line"]))
        # Preserve explicit DOI corrections on an unchanged source citation, but
        # don't confuse a reordered table row with its former occupant.
        if source_record and not any(c["file"] == citation["file"] and c["line"] == citation["line"]
                                     and c["doi"] == doi and c.get("pmid") == pmid for c in source_record["original_citations"]):
            source_record = None
        doi_record, pmid_record = by_doi.get(doi), by_pmid.get(pmid)
        if doi_record and pmid_record and doi_record['id'] != pmid_record['id']:
            raise ValueError(f"DOI {doi} and PMID {pmid} identify separate existing records; curate their merge explicitly")
        record = doi_record or pmid_record or source_record or by_id.get(record_id)
        if record is None:
            record = {
                "id": record_id, "doi": doi, "approved": True,
                "technologies": [], "services": [], "tagging_status": "pending",
                "reporting_years": [], "original_citations": [],
                "metadata": {
                    "title": citation["title"], "authors": [],
                    "authors_text": citation["authors_text"], "journal": citation["journal"],
                    "year": citation["year"], "type": None,
                    "publication_url": f"https://doi.org/{doi}" if doi else (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None),
                },
                "overrides": {}, "metadata_check": {"status": "not_checked", "issues": []},
            }
            records.append(record)
            by_id[record_id] = record
            if doi:
                by_doi[doi] = record
        if pmid:
            if record.get("pmid") and record['pmid'] != pmid:
                raise ValueError(f"Conflicting PubMed identifiers for {record['id']}")
            if record.get("doi") and doi and record['doi'] != doi:
                raise ValueError(f"Conflicting DOI for PMID {pmid}; curate the identifier change explicitly")
            record['pmid'] = pmid
            by_pmid[pmid] = record
            if doi and not record.get('doi'):
                record['doi'] = doi
                by_doi[doi] = record
            if citation.get('doi_status') and not record.get('doi'):
                record['doi_status'] = citation['doi_status']
        if citation not in record["original_citations"]:
            record["original_citations"].append(copy.deepcopy(citation))
        by_source[(citation["file"], citation["line"])] = record
        source_years = [citation["year"]] if citation["year"] is not None else []
        record["reporting_years"] = record.get("reporting_years_override", sorted(set(record["reporting_years"] + source_years)))
    records.sort(key=lambda r: r["id"])
    return registry


def first(value):
    return (value[0] if value else None) if isinstance(value, list) else value


class AbstractText(HTMLParser):
    """Convert provider JATS/HTML into paragraphs of plain text, never HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.split(":")[-1]
        if tag in {"script", "style"}:
            self.suppressed += 1
        elif not self.suppressed and tag in {"p", "title", "sec", "br", "div", "li"}:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        tag = tag.split(":")[-1]
        if tag in {"script", "style"}:
            self.suppressed = max(0, self.suppressed - 1)
        elif not self.suppressed and tag in {"p", "title", "sec", "div", "li"}:
            self.parts.append("\n\n")

    def handle_data(self, text):
        if not self.suppressed:
            self.parts.append(text)


def abstract_text(value):
    if not isinstance(value, str) or not value.strip():
        return None
    parser = AbstractText()
    parser.feed(value)
    text = "\n\n".join(re.sub(r"\s+", " ", part).strip()
                        for part in re.split(r"\n\s*\n", "".join(parser.parts)) if part.strip())
    text = re.sub(r"^Abstract\s*\n+", "", text, flags=re.I).strip()
    if re.fullmatch(r"(?:Abstract|(?:No abstract(?: is)? available(?: for this article)?|Abstract not available)\.?)", text, re.I):
        return None
    return text or None


def reusable_abstract_license(url):
    """Conservative initial public-display allowlist: CC BY and CC0."""
    return isinstance(url, str) and bool(re.fullmatch(
        r"https?://(?:www\.)?creativecommons\.org/(?:licenses/by/(?:1\.0|2\.0|2\.5|3\.0|4\.0)|publicdomain/zero/1\.0)/?(?:legalcode(?:\.[a-z]+)?/?)?",
        url, re.I))


def extract_abstract(data, doi):
    text = abstract_text(data.get("abstract"))
    if not text:
        return None
    licenses = data.get("license", [])
    if isinstance(licenses, str):
        licenses = [{"URL": licenses}]
    if not isinstance(licenses, list):
        licenses = []
    candidates, public_license = [], None
    for entry in licenses:
        if not isinstance(entry, dict) or not safe_url(entry.get("URL")):
            continue
        start = entry.get("start") or {}
        starts_on = str(start.get("date-time", ""))[:10] if isinstance(start, dict) else ""
        try:
            if starts_on:
                starts_on = date.fromisoformat(starts_on).isoformat()
            elif isinstance(start, dict):
                parts = start.get("date-parts", [])
                if parts and parts[0]:
                    y, m, d = (parts[0] + [1, 1])[:3]
                    starts_on = date(y, m, d).isoformat()
        except (ValueError, TypeError, IndexError):
            starts_on = "unknown"
        version = entry.get("content-version") or "unspecified"
        candidates.append({"url": entry["URL"], "content_version": version, "starts_on": starts_on or None})
        if (reusable_abstract_license(entry["URL"]) and version in {"vor", "unspecified"}
                and (not starts_on or starts_on <= date.today().isoformat())):
            public_license = entry["URL"]
    return {"text": text, "source_url": f"https://doi.org/{doi}",
            "licenses": candidates, "public_license_url": public_license}


def normalize_metadata(data):
    """Normalize bibliography; optional abstract enrichment is stored separately."""
    title = clean(first(data.get("title")))
    authors = [clean(a.get("literal") or " ".join(filter(None, [a.get("given"), a.get("family")])))
               for a in data.get("author", [])]
    authors = [a for a in authors if a]
    year = None
    # Prefer the final journal-issue year over an earlier online-first date.
    for field in ("published-print", "published", "issued", "published-online", "posted"):
        parts = (data.get(field) or {}).get("date-parts", [])
        if parts and parts[0]:
            year = int(parts[0][0])
            break
    if not title:
        raise ValueError("Provider returned no title")
    return {
        "title": title, "authors": authors, "authors_text": "; ".join(authors),
        "journal": clean(first(data.get("container-title")) or data.get("publisher")),
        "year": year, "type": clean(data.get("type")) or None,
        "publication_url": f"https://doi.org/{normalize_doi(data['DOI'])}",
    }


def normalize_pubmed(xml, pmid):
    """Read the requested article, never identifiers/authors from its references."""
    pmid = normalize_pmid(pmid)
    root = ET.fromstring(xml)
    article = next((a for a in root.findall('./PubmedArticle')
                    if a.findtext('./MedlineCitation/PMID') == pmid), None)
    if article is None:
        raise ValueError(f"PubMed returned no article for PMID {pmid}")

    def text(path):
        node = article.find(path)
        return clean(''.join(node.itertext())) if node is not None else ''

    identifiers = {n.get('IdType'): n.text for n in article.findall('./PubmedData/ArticleIdList/ArticleId')}
    if any(n.text != pmid for n in article.findall('./PubmedData/ArticleIdList/ArticleId[@IdType="pubmed"]')):
        raise ValueError('PubMed returned a different PMID')
    doi_values = [n.text for n in article.findall('./PubmedData/ArticleIdList/ArticleId[@IdType="doi"]')] + [n.text for n in article.findall(
        './MedlineCitation/Article/ELocationID[@EIdType="doi"]') if n.get('ValidYN', 'Y') == 'Y']
    dois = {normalize_doi(v) for v in doi_values if v}
    if len(dois) > 1:
        raise ValueError('PubMed returned conflicting article DOIs')
    doi = next(iter(dois), None)
    authors = []
    for a in article.findall('./MedlineCitation/Article/AuthorList/Author'):
        name = a.findtext('CollectiveName') or ' '.join(filter(None, [
            a.findtext('ForeName') or a.findtext('Initials'), a.findtext('LastName'), a.findtext('Suffix')]))
        if clean(name):
            authors.append(clean(name))
    pubdate = text('./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year') or text(
        './MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate')
    year = re.search(r'\b(\d{4})\b', pubdate)
    title = text('./MedlineCitation/Article/ArticleTitle')
    if not title:
        raise ValueError('PubMed returned no article title')
    url = f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/'
    paragraphs = []
    for n in article.findall('./MedlineCitation/Article/Abstract/AbstractText'):
        body = clean(''.join(n.itertext()))
        if body:
            paragraphs.append((n.get('Label') + ': ' if n.get('Label') else '') + body)
    result = {'pmid': pmid, 'doi': doi, 'provider': 'pubmed', 'metadata': {
        'title': title, 'authors': authors, 'authors_text': '; '.join(authors),
        'journal': text('./MedlineCitation/Article/Journal/Title'),
        'year': int(year[1]) if year else None, 'type': 'journal-article', 'publication_url': url},
        'abstract': {'text': '\n\n'.join(paragraphs), 'source_url': url,
                     'licenses': [], 'public_license_url': None} if paragraphs else None}
    if identifiers.get('pmc'):
        result['pmcid'] = identifiers['pmc']
    return result


def provider_error(provider, exc):
    # HTTP exception strings can include contact emails in request URLs.
    if isinstance(exc, requests.RequestException):
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        return f'{provider}: {type(exc).__name__}' + (f' (HTTP {status})' if status else '')
    return f'{provider}: {type(exc).__name__}: {str(exc)[:180]}'


class MetadataClient:
    def __init__(self, cache=CACHE, offline=False, refresh=False, mailto=None, include_abstracts=False):
        self.cache, self.offline, self.refresh = Path(cache), offline, refresh
        self.include_abstracts = include_abstracts
        self.mailto = mailto
        self.crossref = Crossref(mailto=mailto, timeout=20, ua_string="CCI-publications/1.0")

    def lookup(self, doi):
        doi = normalize_doi(doi)
        path = self.cache / (hashlib.sha256(doi.encode()).hexdigest() + ".json")
        cached = read_json(path) if path.exists() else None
        if cached and not self.refresh and (not self.include_abstracts or "abstract" in cached):
            return {**cached, "cached": True}
        if self.offline:
            raise LookupError(f"No cached metadata for {doi}")
        errors = []
        for provider in ("crossref", "doi-csl"):
            for attempt in range(3):
                try:
                    if provider == "crossref":
                        data = self.crossref.works(ids=doi)["message"]
                    else:
                        response = requests.get(
                            "https://doi.org/" + quote(doi, safe="/"),
                            headers={"Accept": "application/vnd.citationstyles.csl+json",
                                     "User-Agent": "CCI-publications/1.0"}, timeout=20,
                        )
                        response.raise_for_status()
                        data = response.json()
                    if normalize_doi(data.get("DOI")) != doi:
                        raise ValueError("Provider returned a different DOI")
                    result = {"doi": doi, "provider": provider, "metadata": normalize_metadata(data),
                              "abstract": extract_abstract(data, doi)}
                    write_json(path, result)
                    time.sleep(0.25)
                    return result
                except Exception as exc:
                    response = getattr(exc, "response", None)
                    status = getattr(response, "status_code", None)
                    if status in {429, 502, 503, 504} and attempt < 2:
                        retry_after = getattr(response, "headers", {}).get("Retry-After", "")
                        delay = int(retry_after) if retry_after.isdigit() else 2 ** attempt
                        if delay <= 30:
                            time.sleep(delay)
                            continue
                    errors.append(provider_error(provider, exc))
                    break
        if cached:
            return {**cached, "cached": True, "refresh_error": "; ".join(errors)}
        raise LookupError("; ".join(errors))

    def lookup_pubmed(self, pmid):
        pmid = normalize_pmid(pmid)
        path = self.cache / (hashlib.sha256(f'pmid:{pmid}'.encode()).hexdigest() + '.json')
        cached = read_json(path) if path.exists() else None
        if cached and not self.refresh:
            return {**cached, 'cached': True}
        if self.offline:
            raise LookupError(f'No cached PubMed metadata for PMID {pmid}')
        for attempt in range(3):
            try:
                params = {'db': 'pubmed', 'id': pmid, 'retmode': 'xml', 'tool': 'CCI-publications'}
                if self.mailto:
                    params['email'] = self.mailto
                response = requests.get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi',
                                        params=params, timeout=20)
                response.raise_for_status()
                result = normalize_pubmed(response.content, pmid)
                write_json(path, result)
                time.sleep(0.35)
                return result
            except Exception as exc:
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                if status in {429, 502, 503, 504} and attempt < 2:
                    retry_after = getattr(exc.response, 'headers', {}).get('Retry-After', '')
                    delay = int(retry_after) if retry_after.isdigit() else 2 ** attempt
                    if delay <= 30:
                        time.sleep(delay)
                        continue
                error = provider_error('PubMed', exc)
                if cached:
                    return {**cached, 'cached': True, 'refresh_error': error}
                raise LookupError(error) from exc


def comparable(text):
    text = unicodedata.normalize("NFKD", clean(text)).casefold()
    return " ".join(re.findall(r"[^\W_]+", "".join(c for c in text if not unicodedata.combining(c))))


def compare_metadata(citation, metadata):
    issues = []
    # Book-chapter citations can embed the containing book/editor after the title.
    title = re.split(r"\.\s+In:\s", citation["title"], maxsplit=1)[0]
    similarity = SequenceMatcher(None, comparable(title), comparable(metadata["title"])).ratio()
    if title and similarity < 0.85:
        issues.append({"field": "title", "severity": "review", "similarity": round(similarity, 3)})
    correction = re.match(r"^(corrigendum|erratum|correction|retraction)\b", comparable(metadata["title"]))
    if correction and not comparable(title).startswith(correction[0]):
        issues.append({"field": "title", "severity": "review", "reason": "DOI may identify a correction or retraction rather than the cited article"})
    if metadata.get("year") is None:
        issues.append({"field": "year", "severity": "review", "reason": "missing provider year"})
    elif citation.get("year") is not None and metadata["year"] != citation["year"]:
        issues.append({"field": "year", "severity": "review" if abs(metadata["year"] - citation["year"]) > 1 else "info"})
    # Author formatting differs across years. Compare the first surname, not initials.
    first_author = comparable(citation["authors_text"]).split()
    if not metadata.get("authors"):
        issues.append({"field": "authors", "severity": "review", "reason": "missing provider authors"})
    elif first_author and first_author[0] not in comparable(metadata["authors"][0]).split():
        issues.append({"field": "authors", "severity": "review", "reason": "first author differs"})
    if not metadata.get("journal") or (citation["journal"] and comparable(citation["journal"]) != comparable(metadata.get("journal"))):
        issues.append({"field": "journal", "severity": "info" if metadata.get("journal") else "review", "reason": "source formatting or name differs"})
    return issues


def lookup_record(client, record):
    return client.lookup(record['doi']) if record.get('doi') else client.lookup_pubmed(record['pmid'])


def enrich(registry, client, record_ids=None, prefer_retrieved_ids=None, prefetched_pubmed=None):
    for number, record in enumerate(registry["publications"], 1):
        if record_ids is not None and record["id"] not in record_ids:
            continue
        print(f"[{number}/{len(registry['publications'])}] {record['doi'] or record['id']}", flush=True)
        if not record["doi"] and not record.get('pmid'):
            record["metadata_check"] = {"status": "manual_required", "issues": []}
            continue
        try:
            if record.get('pmid') in (prefetched_pubmed or {}):
                retrieved = prefetched_pubmed[record['pmid']]
                if isinstance(retrieved, LookupError):
                    raise retrieved
            else:
                retrieved = lookup_record(client, record)
        except LookupError as exc:
            # A transient refresh failure must not erase previously usable metadata.
            record["last_lookup_error"] = str(exc)
            if "retrieved" not in record:
                record["metadata_check"] = {"status": "lookup_failed", "issues": []}
            continue
        record.pop("last_lookup_error", None)
        if retrieved.get("refresh_error"):
            record["last_lookup_error"] = retrieved["refresh_error"]
            # A cached fallback after a failed live check is not a new update.
            # In particular, don't regress newer manually supplied metadata.
            continue
        if retrieved.get('pmid'):
            record['pmid'] = retrieved['pmid']
            if retrieved.get('doi'):
                if any(r['id'] != record['id'] and r.get('doi') == retrieved['doi'] for r in registry['publications']):
                    raise ValueError(f"Discovered DOI {retrieved['doi']} belongs to another record; curate the merge explicitly")
                if record.get('doi') and record['doi'] != retrieved['doi']:
                    raise ValueError(f"Conflicting DOI for PMID {record['pmid']}")
                record['doi'] = retrieved['doi']
            record['doi_status'] = ('available' if record.get('doi') else
                                    record.get('doi_status', 'not-listed'))
            if retrieved.get('pmcid'):
                record['pmcid'] = retrieved['pmcid']
        record["retrieved"] = {k: v for k, v in retrieved.items() if k in {"doi", "pmid", "pmcid", "provider", "metadata"}}
        issues = []
        for citation in record["original_citations"]:
            issues.extend({**issue, "file": citation["file"], "line": citation["line"]}
                          for issue in compare_metadata(citation, retrieved["metadata"]))
        if not any(c.get("title") for c in record["original_citations"]):
            # DOI-only additions need a person to check the returned citation.
            status = "review"
        else:
            status = "review" if any(i["severity"] == "review" for i in issues) else "matched"
        record["metadata_check"] = {"status": status, "issues": issues}
        # A changed author list is often a publication-stage update. Prefer DOI
        # metadata when the title matches and required fields are present, but
        # still report that author difference for review. Identity mismatches
        # and corrections/retractions retain the existing citation.
        identity_issue = any(i["severity"] == "review" and
                             (i["field"] == "title" or i.get("reason", "").startswith("missing"))
                             for i in issues)
        source_selected = (record.get("metadata_review", {}).get("basis") == "existing_citation" and
                           record.get("metadata_review", {}).get("fingerprint") == review_fingerprint(record))
        provider_complete = all(retrieved["metadata"].get(field) for field in ("title", "authors", "authors_text", "journal", "year"))
        # An already registered DOI is its identity: publication-stage changes
        # may update the title as well as authors/year. Explicit curator choices
        # and correction/retraction warnings still require review.
        trusted_doi = record["id"] in (prefer_retrieved_ids or set())
        correction_issue = any(i.get("reason", "").startswith("DOI may identify") for i in issues)
        if (not identity_issue or trusted_doi and not correction_issue) and not source_selected and provider_complete:
            record["metadata"] = copy.deepcopy(retrieved["metadata"])
        if not record["reporting_years"] and type(record["metadata"].get("year")) is int:
            record["reporting_years"] = [record["metadata"]["year"]]
        review = record.get("metadata_review", {})
        if review.get("fingerprint") == review_fingerprint(record):
            record["metadata_check"]["status"] = "accepted"


def review_fingerprint(record):
    content = {"doi": record["doi"], "retrieved": record.get("retrieved"),
               "original_citations": record["original_citations"]}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def import_table_records(citations, registry, client):
    """Merge DOI identities, refresh each selected record once, and report changes."""
    before = {r["id"]: copy.deepcopy(r["metadata"]) for r in registry["publications"]}
    identifiers_before = {r['id']: {key: r.get(key) for key in ('doi', 'pmid', 'pmcid', 'doi_status')}
                          for r in registry['publications']}
    citations = copy.deepcopy(citations)
    prefetched = {}
    # Resolve PMID aliases before merging: an article may already be registered
    # under the DOI returned by PubMed. Repeated PMID rows trigger one lookup.
    for citation in citations:
        pmid = citation.get('pmid')
        if not pmid:
            continue
        if pmid not in prefetched:
            try:
                prefetched[pmid] = client.lookup_pubmed(pmid)
            except LookupError as exc:
                prefetched[pmid] = exc
        result = prefetched[pmid]
        if not isinstance(result, LookupError) and not result.get('refresh_error'):
            citation['doi'] = result.get('doi')
    registry = import_citations(citations, registry)
    source_keys = {(c["file"], c["line"], c["doi"], c.get('pmid')) for c in citations}
    selected = {r["id"] for r in registry["publications"]
                if any((c["file"], c["line"], c["doi"], c.get('pmid')) in source_keys for c in r["original_citations"])}
    enrich(registry, client, selected, prefer_retrieved_ids=set(before), prefetched_pubmed=prefetched)
    updates = []
    for record in registry["publications"]:
        if record["id"] not in selected:
            continue
        previous = before.get(record["id"], {})
        changes = {field: {"before": previous.get(field), "after": record["metadata"].get(field)}
                   for field in sorted(FIELDS) if previous.get(field) != record["metadata"].get(field)}
        identity_changes = {key: {'before': value, 'after': record.get(key)}
                            for key, value in identifiers_before.get(record['id'], {}).items()
                            if value != record.get(key)}
        status = ("lookup_failed" if record.get("last_lookup_error") else
                  "new" if record["id"] not in before else "updated" if changes or identity_changes else
                  "review_required" if record.get("retrieved", {}).get("metadata") != record["metadata"] else "unchanged")
        updates.append({"id": record["id"], "doi": record["doi"], "status": status, "changes": changes})
        if record.get('pmid'):
            updates[-1]['pmid'] = record['pmid']
        if identity_changes:
            updates[-1]['identifier_changes'] = identity_changes
    return registry, updates


def accept_review(record, use_retrieved=False, note=""):
    if use_retrieved:
        if "retrieved" not in record:
            raise ValueError("No retrieved metadata to accept")
        record["metadata"] = copy.deepcopy(record["retrieved"]["metadata"])
    record["metadata_review"] = {"fingerprint": review_fingerprint(record),
                                 "basis": "retrieved" if use_retrieved else "existing_citation",
                                 "note": note}
    record["metadata_check"]["status"] = "accepted"


def effective_metadata(record):
    return {**record["metadata"], **record["overrides"]}


def fetch_abstracts(registry, client, store=ABSTRACT_STORE, record_ids=None):
    """Keep all available abstracts private; export only eligible, matched text."""
    previous = read_json(store) if Path(store).exists() else {"abstracts": []}
    saved = {entry["id"]: entry for entry in previous["abstracts"]}
    results = []
    for number, record in enumerate(registry["publications"], 1):
        if record_ids is not None and record["id"] not in record_ids:
            continue
        print(f"Abstract [{number}/{len(registry['publications'])}] {record['doi'] or record['id']}", flush=True)
        entry = {"id": record["id"], "doi": record["doi"], "abstract": None}
        if not record["doi"] and not record.get('pmid'):
            entry["status"] = "no_doi"
        else:
            try:
                result = lookup_record(client, record)
                if result.get("refresh_error"):
                    raise LookupError(result["refresh_error"])
                candidate = result.get("abstract")
                entry.update(abstract=candidate, provider=result["provider"])
                if not candidate and saved.get(record["id"], {}).get("doi") == record["doi"]:
                    entry["abstract"] = saved[record["id"]].get("abstract")
                title_issues = compare_metadata(effective_metadata(record), result["metadata"])
                identity_issue = any(i["field"] == "title" and i["severity"] == "review" for i in title_issues)
                if not candidate:
                    entry["status"] = "not_available"
                elif identity_issue:
                    entry["status"] = "identity_review"
                    entry["retrieved_title"] = result["metadata"]["title"]
                elif candidate.get("public_license_url"):
                    record["abstract"] = {"text": candidate["text"], "source_url": candidate["source_url"],
                                          "license_url": candidate["public_license_url"]}
                    entry["status"] = "publicly_displayable"
                else:
                    entry["status"] = "private_only"
                # A successful new response governs public eligibility. The
                # private store retains text even when it must not be exported.
                if entry["status"] != "publicly_displayable":
                    record.pop("abstract", None)
            except LookupError as exc:
                entry = {**saved.get(record["id"], entry), "status": "failed", "error": str(exc)}
                # An outage must not erase a previously retrieved abstract.
        saved[record["id"]] = entry
        results.append(entry)
    summary = {status: sum(e["status"] == status for e in results)
               for status in ("publicly_displayable", "private_only", "not_available", "identity_review", "failed", "no_doi")}
    write_json(store, {"schema_version": 1, "summary": summary,
                       "abstracts": sorted(saved.values(), key=lambda e: e["id"])})
    print(json.dumps(summary, indent=2))
    return summary


def check_updates(registry, client, output=UPDATES, record_ids=None):
    """Compare live provider metadata to the last retrieval without editing records."""
    records = []
    for number, record in enumerate(registry["publications"], 1):
        if record_ids is not None and record["id"] not in record_ids:
            continue
        print(f"Checking [{number}/{len(registry['publications'])}] {record['doi'] or record['id']}", flush=True)
        item = {"id": record["id"], "doi": record["doi"], "changes": {},
                "protected_fields": sorted(record["overrides"])}
        if record.get('pmid'):
            item['pmid'] = record['pmid']
        if not record["doi"] and not record.get('pmid'):
            item["status"] = "no_doi"
        else:
            try:
                latest = lookup_record(client, record)
                if latest.get("refresh_error"):
                    raise LookupError(latest["refresh_error"])
                previous = (record.get("retrieved") or {}).get("metadata", record["metadata"])
                item["changes"] = {field: {"before": previous.get(field), "after": latest["metadata"].get(field)}
                                   for field in sorted(FIELDS) if previous.get(field) != latest["metadata"].get(field)}
                if not record.get('doi') and latest.get('doi'):
                    item['changes']['doi'] = {'before': None, 'after': latest['doi']}
                item["status"] = "changed" if item["changes"] else "unchanged"
                item["provider"] = latest["provider"]
            except LookupError as exc:
                item.update(status="failed", error=str(exc))
        records.append(item)
    summary = {status: sum(r["status"] == status for r in records)
               for status in ("changed", "unchanged", "failed", "no_doi")}
    write_json(output, {"summary": summary, "records": records})
    lines = ["DOI metadata update check (registry and public catalogue unchanged)",
             json.dumps(summary, indent=2), ""]
    for item in records:
        if item["status"] == "unchanged":
            continue
        lines.append(f"{item['doi'] or ('PMID:' + item['pmid'] if item.get('pmid') else item['id'])}: {item['status']}")
        for field, change in item["changes"].items():
            protected = " (manual override protected)" if field in item["protected_fields"] else ""
            lines.extend([field + protected, "  Before: " + str(change["before"]), "  After: " + str(change["after"])])
        if item.get("error"):
            lines.append(item["error"])
        lines.append("")
    write_text(Path(output).with_suffix(".txt"), "\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))
    return summary


def validate(registry, vocabulary):
    if registry.get("schema_version") != 1 or not isinstance(registry.get("publications"), list):
        raise ValueError("Expected schema_version: 1 and a publications list")
    ids, dois, pmids = set(), set(), set()
    for r in registry["publications"]:
        if not isinstance(r.get("id"), str) or not r["id"] or r["id"] in ids:
            raise ValueError(f"Missing or duplicate ID: {r.get('id')}")
        ids.add(r["id"])
        if "cci_involvement" in r and r["cci_involvement"] not in {"scientific-collaboration", "service-provision"}:
            raise ValueError(f"{r['id']}: invalid cci_involvement")
        if "cci_involvement_override" in r and r["cci_involvement_override"] not in {"scientific-collaboration", "service-provision"}:
            raise ValueError(f"{r['id']}: invalid cci_involvement_override")
        doi = normalize_doi(r.get("doi"))
        if doi != r.get("doi") or doi and doi in dois:
            raise ValueError(f"Noncanonical or duplicate DOI: {r.get('doi')}")
        if doi:
            dois.add(doi)
        if r.get('pmid') is not None:
            pmid = normalize_pmid(r['pmid'])
            if pmid != r['pmid'] or pmid in pmids:
                raise ValueError(f"Noncanonical or duplicate PMID: {r['pmid']}")
            pmids.add(pmid)
        if r.get('pmcid') is not None and not re.fullmatch(r'PMC[1-9]\d*', str(r['pmcid'])):
            raise ValueError(f"Invalid PMCID: {r['pmcid']}")
        if 'doi_status' in r:
            if (r['doi_status'] not in {'available', 'not-listed', 'confirmed-unavailable'} or
                    (r['doi_status'] == 'available') != bool(doi)):
                raise ValueError(f"Invalid DOI status: {r['id']}")
        if type(r.get("approved")) is not bool:
            raise ValueError(f"{r['id']}: approved must be boolean")
        for field in ("technologies", "services"):
            values = r.get(field)
            known = {entry["id"] for entry in vocabulary[field]}
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                raise ValueError(f"{r['id']}: invalid {field}")
            if len(values) != len(set(values)) or set(values) - known:
                raise ValueError(f"{r['id']}: duplicate or unknown {field}")
        if r.get("tagging_status") not in {"pending", "reviewed"}:
            raise ValueError(f"{r['id']}: invalid tagging_status")
        if not isinstance(r.get("reporting_years"), list) or any(type(y) is not int or not 1500 <= y <= 2200 for y in r["reporting_years"]):
            raise ValueError(f"{r['id']}: invalid reporting_years")
        if "reporting_years_override" in r and (not r["reporting_years_override"] or r["reporting_years_override"] != r["reporting_years"]):
            raise ValueError(f"{r['id']}: reporting year override must match reporting_years")
        if not isinstance(r.get("overrides"), dict) or set(r["overrides"]) - FIELDS:
            raise ValueError(f"{r['id']}: invalid override fields")
        m = effective_metadata(r)
        for field in ("title", "authors_text", "journal"):
            if not isinstance(m.get(field), str) or not m[field].strip():
                raise ValueError(f"{r['id']}: {field} is required; use edit to supply it")
        if type(m.get("year")) is not int or not 1500 <= m["year"] <= 2200:
            raise ValueError(f"{r['id']}: invalid publication year")
        if not isinstance(m.get("authors"), list) or any(not isinstance(a, str) or not a.strip() for a in m["authors"]):
            raise ValueError(f"{r['id']}: authors must be a list of names")
        if m.get("publication_url") is not None and not safe_url(m["publication_url"]):
            raise ValueError(f"{r['id']}: publication_url must be an HTTP(S) URL")
        if r.get("abstract") is not None:
            abstract = r["abstract"]
            if (not isinstance(abstract, dict) or not isinstance(abstract.get("text"), str)
                    or not abstract["text"].strip() or not safe_url(abstract.get("source_url"))
                    or not reusable_abstract_license(abstract.get("license_url"))):
                raise ValueError(f"{r['id']}: invalid public abstract or missing reuse license")


def public_catalogue(registry, vocabulary):
    validate(registry, vocabulary)
    records = []
    for r in registry["publications"]:
        if not r["approved"]:
            continue
        m = effective_metadata(r)
        # Explicit allowlist: never export source citations, notes, or provider payloads.
        records.append({"id": r["id"], "doi": r["doi"],
                        **{field: m.get(field) for field in sorted(FIELDS)},
                        "reporting_years": r["reporting_years"],
                        "technologies": r["technologies"], "services": r["services"]})
        if r.get("abstract"):
            records[-1]["abstract"] = {key: r["abstract"][key] for key in ("text", "source_url", "license_url")}
        if r.get("cci_involvement"):
            records[-1]["cci_involvement"] = r["cci_involvement"]
        for key in ('pmid', 'pmcid'):
            if r.get(key):
                records[-1][key] = r[key]
    records.sort(key=lambda r: (-r["year"], comparable(r["title"]), r["id"]))
    public_vocabulary = {kind: [{key: entry[key] for key in ("id", "label", "parent") if key in entry}
                                for entry in vocabulary[kind]]
                         for kind in ("technologies", "services")}
    return {"schema_version": 1, "publications": records, "vocabulary": public_vocabulary}


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_registry(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def save_registry(path, registry):
    write_text(path, yaml.safe_dump(registry, allow_unicode=True, sort_keys=False, width=100))


def write_report(path, registry, import_updates=None):
    rows = []
    for r in registry["publications"]:
        rows.append({"id": r["id"], "doi": r["doi"], "pmid": r.get('pmid'), "status": r["metadata_check"]["status"],
                     "issues": r["metadata_check"]["issues"], "lookup_error": r.get("last_lookup_error"),
                     "original_citations": r["original_citations"],
                     "retrieved": r.get("retrieved"), "review_decision": r.get("metadata_review"),
                     "effective_metadata": effective_metadata(r),
                     "duplicate": len(r["original_citations"]) > 1})
    summary = {"records": len(rows), "source_rows": sum(len(r["original_citations"]) for r in rows),
               "duplicates": sum(r["duplicate"] for r in rows),
               "statuses": {s: sum(r["status"] == s for r in rows) for s in sorted({r["status"] for r in rows})}}
    report = {"summary": summary, "records": rows}
    if import_updates is not None:
        report["import_updates"] = import_updates
    write_json(path, report)
    review_lines = ["CCI publication import review", "", json.dumps(summary, indent=2), "",
                    "Matches are automated comparisons, not a substitute for bibliographic review.",
                    "Inspect flagged differences and import changes; explicit curator overrides remain protected.", ""]
    if import_updates is not None:
        review_lines.extend(["This import (bibliographic metadata and identifiers):",
                             *[f"{r['doi'] or ('PMID:' + r['pmid'] if r.get('pmid') else r['id'])}: {r['status']}" +
                               (" (" + ", ".join(sorted(set(r['changes']) | set(r.get('identifier_changes', {})))) + ")"
                                if r['changes'] or r.get('identifier_changes') else "")
                               for r in import_updates], ""])
    for row in rows:
        if row["status"] == "matched" and not row["duplicate"]:
            continue
        review_lines.extend([f"{row['id']} | {row['doi'] or ('PMID:' + row['pmid'] if row.get('pmid') else 'no identifier')} | {row['status']}"])
        if row["duplicate"]:
            review_lines.append("Repeated DOI: one registry record, all source years retained.")
        if row["review_decision"]:
            review_lines.append("Recorded decision: " + row["review_decision"]["note"])
        for citation in row["original_citations"]:
            review_lines.extend([f"Source: {citation['file']}:{citation['line']} ({citation['year']})",
                                 f"  Title: {citation['title']}", f"  Authors: {citation['authors_text']}"])
            if citation.get("citation_text"):
                review_lines.append("  Original citation: " + citation["citation_text"])
        candidate = (row["retrieved"] or {}).get("metadata", {})
        if candidate:
            review_lines.extend([f"Retrieved title: {candidate['title']}", f"Retrieved authors: {candidate['authors_text']}"])
        for issue in row["issues"]:
            if issue["severity"] == "review":
                review_lines.append(("ACCEPTED: " if row["status"] == "accepted" else "REVIEW: ") + json.dumps(issue, ensure_ascii=False))
        if row["lookup_error"]:
            review_lines.append("Lookup error: " + row["lookup_error"])
        review_lines.append("")
    write_text(Path(path).with_suffix(".txt"), "\n".join(review_lines) + "\n")
    csv_path = Path(path).with_suffix(".csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "doi", "status", "duplicate", "source_years", "source_titles", "retrieved_year", "retrieved_title", "issues", "lookup_error", "pmid"])
        for r in rows:
            candidate = (r["retrieved"] or {}).get("metadata", {})
            writer.writerow([r["id"], r["doi"], r["status"], r["duplicate"],
                             "; ".join(str(c["year"]) for c in r["original_citations"]),
                             " | ".join(c["title"] or c.get("citation_text", "") for c in r["original_citations"]),
                             candidate.get("year"), candidate.get("title"), json.dumps(r["issues"]), r["lookup_error"], r.get('pmid')])
    print(json.dumps(summary, indent=2))
    return summary


def sample_citations(citations):
    """Deterministic sample across years, duplicates, preprints, and chapters."""
    selected = []
    for filename in sorted({c["file"] for c in citations}):
        selected.extend([c for c in citations if c["file"] == filename][:3])
    counts = {}
    for c in citations:
        if c["doi"]:
            counts[c["doi"]] = counts.get(c["doi"], 0) + 1
    selected.extend(c for c in citations if counts.get(c["doi"], 0) > 1)
    for term in ("tomography-based", "arxiv", "chemrxiv"):
        candidate = next((c for c in citations if term in (c["title"] + c["journal"]).lower()), None)
        if candidate:
            selected.append(candidate)
    keys = {(c["file"], c["line"]) for c in selected}
    return [c for c in citations if (c["file"], c["line"]) in keys]


def manual_fields(args):
    result = {}
    for name in ("title", "journal", "year", "publication_url", "type"):
        value = getattr(args, name, None)
        if value is not None:
            result[name] = clean(value) if isinstance(value, str) else value
    if args.author:
        result["authors"] = [clean(a) for a in args.author]
        result["authors_text"] = "; ".join(result["authors"])
    return result


def prompt_fields(metadata):
    fields = {}
    for field in ("title", "authors_text", "journal", "year", "publication_url"):
        current = metadata.get(field) or ""
        answer = input(f"{field} [{current}]: ").strip()
        if answer:
            fields[field] = int(answer) if field == "year" else clean(answer)
    if "authors_text" in fields:
        fields["authors"] = [clean(a) for a in fields["authors_text"].split(";") if a.strip()]
    return fields


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--vocabulary", type=Path, default=VOCABULARY)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--mailto", default=os.environ.get("CROSSREF_MAILTO"))
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import-tables")
    importer.add_argument("files", type=Path, nargs="+")
    importer.add_argument("--sample", action="store_true")
    refresh = commands.add_parser("refresh")
    refresh.add_argument("--id", action="append", help="Refresh only these record IDs (repeatable)")
    abstracts = commands.add_parser("fetch-abstracts")
    abstracts.add_argument("--id", action="append")
    abstracts.add_argument("--refresh", action="store_true", help="Recheck providers even when abstract metadata is cached")
    updates = commands.add_parser("check-updates")
    updates.add_argument("--id", action="append")
    updates.add_argument("--output", type=Path, default=UPDATES)
    updates.add_argument("--fail-on-changes", action="store_true")
    commands.add_parser("validate")
    show = commands.add_parser("show")
    show.add_argument("id")
    review = commands.add_parser("review")
    review.add_argument("id")
    review.add_argument("--use-retrieved", action="store_true")
    review.add_argument("--note", default="")
    build = commands.add_parser("build")
    build.add_argument("--output", type=Path, default=OUTPUT)
    build.add_argument("--check-updates", action="store_true", help="Check live DOI metadata before building")
    for name in ("add", "edit"):
        sub = commands.add_parser(name)
        if name == "edit":
            sub.add_argument("id")
            sub.add_argument("--doi", help="Correct the DOI without changing the internal ID")
            sub.add_argument("--accept-retrieved", action="store_true")
        else:
            sub.add_argument("--doi")
            sub.add_argument("--manual", action="store_true")
        sub.add_argument("--interactive", action="store_true")
        sub.add_argument("--approved", action=argparse.BooleanOptionalAction, default=None)
        sub.add_argument("--title")
        sub.add_argument("--author", action="append")
        sub.add_argument("--journal")
        sub.add_argument("--year", type=int)
        sub.add_argument("--reporting-year", type=int, action="append", help="Override reporting years (repeatable)")
        sub.add_argument("--publication-url")
        sub.add_argument("--type")
        sub.add_argument("--doi-status", choices=['available', 'not-listed', 'confirmed-unavailable'])
    args = parser.parse_args(argv)
    import_updates = None
    vocabulary = read_registry(args.vocabulary)
    if args.command in {"validate", "build", "refresh", "edit", "show", "review", "check-updates", "fetch-abstracts"} and not args.registry.exists():
        raise ValueError(f"Registry not found: {args.registry}; import tables or add a record first")
    registry = read_registry(args.registry) if args.registry.exists() else {"schema_version": 1, "publications": []}
    if args.command == "check-updates" or args.command == "build" and args.check_updates:
        if args.offline:
            raise ValueError("Live update checks cannot run with --offline; use validate/build for offline checks")
        validate(registry, vocabulary)
        selected = set(args.id) if args.command == "check-updates" and args.id else None
        if selected and selected - {r["id"] for r in registry["publications"]}:
            raise ValueError("Unknown ID requested for update check")
        summary = check_updates(registry, MetadataClient(args.cache, refresh=True, mailto=args.mailto),
                                args.output if args.command == "check-updates" else UPDATES, selected)
        if args.command == "check-updates":
            if summary["failed"]:
                return 3
            return 2 if args.fail_on_changes and summary["changed"] else 0
        if summary["failed"]:
            raise ValueError("Live metadata check failed; see private_data/doi-updates.txt")
    if args.command == "fetch-abstracts":
        selected = set(args.id) if args.id else None
        if selected and selected - {r["id"] for r in registry["publications"]}:
            raise ValueError("Unknown ID requested for abstract enrichment")
        fetch_abstracts(registry, MetadataClient(args.cache, args.offline, refresh=args.refresh,
                                               mailto=args.mailto, include_abstracts=True),
                        store=ABSTRACT_STORE, record_ids=selected)
    elif args.command == "import-tables":
        citations = read_tables(args.files)
        if args.sample:
            citations = sample_citations(citations)
        registry, import_updates = import_table_records(
            citations, registry, MetadataClient(args.cache, args.offline, refresh=not args.offline, mailto=args.mailto))
    elif args.command == "refresh":
        selected = set(args.id) if args.id else None
        if selected and selected - {r["id"] for r in registry["publications"]}:
            raise ValueError("Unknown ID requested for refresh")
        enrich(registry, MetadataClient(args.cache, args.offline, refresh=not args.offline, mailto=args.mailto), selected)
    elif args.command == "review":
        record = next((r for r in registry["publications"] if r["id"] == args.id), None)
        if record is None:
            raise ValueError(f"Unknown publication ID: {args.id}")
        accept_review(record, args.use_retrieved, args.note)
    elif args.command in {"add", "edit"}:
        if args.command == "add":
            doi = normalize_doi(args.doi)
            if doi and any(r["doi"] == doi for r in registry["publications"]):
                raise ValueError(f"DOI already exists: {doi}; use edit")
            record = {"id": "cci-" + uuid.uuid4().hex, "doi": doi,
                      "approved": False, "technologies": [], "services": [], "tagging_status": "pending",
                      "reporting_years": [], "original_citations": [], "metadata": {}, "overrides": {},
                      "metadata_check": {"status": "manual_required", "issues": []}}
            registry["publications"].append(record)
            if doi and not args.manual:
                enrich(registry, MetadataClient(args.cache, args.offline, mailto=args.mailto), {record["id"]})
                if record.get("retrieved"):
                    record["metadata"] = copy.deepcopy(record["retrieved"]["metadata"])
        else:
            record = next((r for r in registry["publications"] if r["id"] == args.id), None)
            if record is None:
                raise ValueError(f"Unknown publication ID: {args.id}")
            if args.doi is not None:
                doi = normalize_doi(args.doi)
                if doi and any(r is not record and r["doi"] == doi for r in registry["publications"]):
                    raise ValueError(f"DOI already exists: {doi}")
                if doi != record["doi"]:
                    record["doi"] = doi
                    if 'doi_status' in record:
                        record['doi_status'] = 'available' if doi else 'not-listed'
                    record.pop("retrieved", None)
                    record.pop("abstract", None)
                    record.pop("last_lookup_error", None)
                    record["metadata_check"] = {"status": "not_checked", "issues": []}
                    record["overrides"]["publication_url"] = f"https://doi.org/{doi}" if doi else None
            if args.accept_retrieved:
                if "retrieved" not in record:
                    raise ValueError("No retrieved metadata to accept")
                # Explicit acceptance locks these fields against future refreshes.
                record["overrides"].update(record["retrieved"]["metadata"])
        record["overrides"].update(manual_fields(args))
        if args.doi_status is not None:
            record['doi_status'] = args.doi_status
        if args.reporting_year:
            record["reporting_years_override"] = sorted(set(args.reporting_year))
            record["reporting_years"] = record["reporting_years_override"][:]
        if args.interactive:
            record["overrides"].update(prompt_fields(effective_metadata(record)))
        if args.approved is not None:
            record["approved"] = args.approved
        if not record["reporting_years"]:
            record["reporting_years"] = [effective_metadata(record).get("year")]
        if record["doi"] and not effective_metadata(record).get("publication_url"):
            record["overrides"]["publication_url"] = f"https://doi.org/{record['doi']}"
        print(json.dumps(record, ensure_ascii=False, indent=2))
    if import_updates is not None:
        # Keep a useful private report even when a DOI-only lookup failed and
        # incomplete metadata prevents writing the canonical registry.
        write_report(args.report, registry, import_updates)
    validate(registry, vocabulary)
    if args.command == "show":
        record = next((r for r in registry["publications"] if r["id"] == args.id), None)
        if record is None:
            raise ValueError(f"Unknown publication ID: {args.id}")
        print(json.dumps(record, ensure_ascii=False, indent=2))
    elif args.command == "build":
        write_json(args.output, public_catalogue(registry, vocabulary))
        print(f"Built {args.output}")
    elif args.command == "validate":
        print(f"Validated {len(registry['publications'])} publications")
    else:
        registry["publications"].sort(key=lambda r: r["id"])
        save_registry(args.registry, registry)
        if import_updates is None:
            write_report(args.report, registry)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, yaml.YAMLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
