import test from "node:test";
import assert from "node:assert/strict";
import {selectPublications, publicationURL} from "../assets/js/publications.js";

// Synthetic fixtures: not part of the public catalogue.
const records = [
  {id: "a", title: "Åström microscopy study", authors_text: "Anna Åström", authors: ["Anna Åström"], year: 2024,
    journal: "Test Journal", doi: "10.1234/alpha", technologies: ["confocal", "light_sheet"]},
  {id: "b", title: "Beta tissue study", authors_text: "Jane Doe", year: 2025,
    journal: "Other Journal", doi: "10.1234/beta", technologies: ["electron"]},
  {id: "c", title: "Gamma microscopy", authors_text: "John Doe", year: 2024,
    journal: "Test Journal", doi: null, technologies: []},
];

test("search supports accents and terms across author/title/journal/DOI", () => {
  assert.deepEqual(selectPublications(records, {query: "astrom microscopy"}).map(r => r.id), ["a"]);
  assert.deepEqual(selectPublications(records, {query: "10.1234/beta"}).map(r => r.id), ["b"]);
  assert.deepEqual(selectPublications(records, {query: "Doe Other"}).map(r => r.id), ["b"]);
});

test("year and technology filters combine with text search", () => {
  assert.deepEqual(selectPublications(records, {year: "2024", query: "microscopy"}).map(r => r.id), ["a", "c"]);
  assert.deepEqual(selectPublications(records, {technologies: ["electron", "confocal"]}).map(r => r.id), ["b", "a"]);
  assert.equal(selectPublications(records, {year: "2025", technologies: ["confocal"]}).length, 0);
});

test("technology labels are searchable", () => {
  const labels = new Map([["confocal", "Optical sectioning"]]);
  assert.deepEqual(selectPublications(records, {query: "optical"}, labels).map(r => r.id), ["a"]);
});

test("sorting is stable and does not mutate the catalogue", () => {
  const before = structuredClone(records);
  assert.deepEqual(selectPublications(records).map(r => r.id), ["b", "a", "c"]);
  assert.deepEqual(selectPublications(records, {sort: "oldest"}).map(r => r.id), ["a", "c", "b"]);
  assert.deepEqual(selectPublications(records, {sort: "title"}).map(r => r.id), ["a", "b", "c"]);
  assert.deepEqual(records, before);
});

test("publication links use DOI or safe HTTP URLs", () => {
  assert.equal(publicationURL(records[0]), "https://doi.org/10.1234/alpha");
  assert.equal(publicationURL({doi: "10.1234/a?b#c"}), "https://doi.org/10.1234/a%3Fb%23c");
  assert.equal(publicationURL({publication_url: "javascript:alert(1)"}), null);
  assert.equal(publicationURL({publication_url: "https://example.org/article"}), "https://example.org/article");
  assert.equal(publicationURL({}), null);
});
