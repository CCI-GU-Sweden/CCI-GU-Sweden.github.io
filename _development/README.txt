LOCAL DEVELOPMENT

This website uses GitHub Pages-compatible Jekyll 3.10.0 and the Slate 0.2.0
theme gem. The Gemfile lists the plugins this site uses. Node.js and Docker
are not required to preview the site. See _development/dependencies.txt for
the dependency security decision.

Initial setup (Ubuntu / WSL)

1. Install Ruby and native extension build tools in your terminal:

   sudo apt-get update
   sudo apt-get install -y ruby-full ruby-dev build-essential zlib1g-dev

2. From the repository directory, install the project dependencies:

   bash _development/site.sh setup

   Internet access is required. Gems are installed inside this checkout,
   without sudo. Keep the generated Gemfile.lock for repeatable installs.

Preview

   bash _development/site.sh serve

Open http://127.0.0.1:4000 in your browser. Jekyll rebuilds after edits and
LiveReload refreshes the browser. Restart the server after configuration
changes. Press Ctrl+C to stop. The server listens only on this computer.
If Windows cannot reach the WSL preview, try the browser inside WSL or
check WSL localhost forwarding before changing the server bind address.

serve cci-page uses this same script. Each start clears generated Jekyll
output/caches and rebuilds before serving. Development responses explicitly
disable browser caching; page-specific assets also have versioned URLs and
the publication catalogue bypasses the browser cache. These settings apply
only to local preview. No shell-profile changes are needed after pulling.

Check before publishing

   bash _development/site.sh check

This builds the site and checks front matter. Also inspect the desktop and
mobile layouts, every navigation link, documentation content, and PDF
downloads in the browser. A successful build does not test browser JavaScript
or the external services used by documentation pages.

Python environment for publication development

The Jekyll preview uses Ubuntu Ruby and project-local gems. Publication
import and validation tools use a separate Conda environment named cci-page.
Miniforge/Conda or Mamba must already be installed.

Create the environment once, from the repository directory:

   conda env create -f environment.yml

Activate it when working on Python tools:

   conda activate cci-page

It includes Python 3.12, Habanero (Crossref metadata), Requests (HTTP
fallbacks), PyYAML (curated records), and pytest (data validation tests).
Private full-text experiments additionally use Beautiful Soup and lxml for
HTML/JATS XML parsing, markdownify for Markdown conversion, and pypdf with
fonttools for PDF text extraction. These are development tools, not website
build dependencies.

The publication importer and manual curation commands are documented in
_development/publications.txt.
The catalogue view and its browser checks are described in
_development/portal.txt.
Private article-text collection and its resumable retrieval reports are
described in _development/fulltext.txt.

After changing environment.yml, update the environment with:

   conda env update -n cci-page -f environment.yml --prune

Use conda deactivate when finished. The serve cci-page command does not
require this Python environment to be active.

environment.yml constrains compatible versions; it is not an exact lock.
_development/conda-linux-64.explicit.txt records the tested Linux packages.
To reproduce those exact packages on Linux x86-64, use:

   conda create -n cci-page -f _development/conda-linux-64.explicit.txt

After intentionally updating dependencies, regenerate the snapshot:

   conda list -n cci-page --explicit > _development/conda-linux-64.explicit.txt

Where to edit

- Root *.md files: home, contact, rules, events, documentation index.
- docs/*.md: documentation pages, many loading external Markdown/PDFs.
- _data/navigation.yml: navigation links and labels.
- _layouts/default.html: regular page layout.
- _layouts/document.html: documentation layout with Markdown/PDF controls.
- _includes/navigation.html: navigation markup.
- assets/css/style.scss: styles extending the Slate theme.
- assets/js/utils.js: external Markdown and PDF handling.
- _config.yaml: shared website configuration.

External dependencies

The theme is installed as a gem during setup; builds do not download a theme
ZIP. GitHub metadata and several documentation pages still use external
services. Documentation pages load
Markdown, PDFs, JavaScript libraries, and an iframe from other repositories
or CDNs at runtime, so a complete preview needs internet access. Changes in
this checkout do not change content hosted by those other repositories.
Existing layouts include GoatCounter analytics; these remain unchanged.

Safe editing and release

Work on dev/local-preview, or create another development branch from it.
Local edits, commits, builds, and previews do not publish the website.
GitHub Pages settings were checked on 2026-10-22: the publishing source is
main, from the repository root (/). Pushing or merging into main can publish
the site. Wait until testing is complete and publication has been explicitly
approved. Recheck GitHub Settings > Pages before release if settings change.

There are no deployment commands in these scripts. The local override only
sets local URLs and repository metadata. Generated files and dependencies
are ignored by Git. Jekyll excludes the _development directory from output
because its name starts with an underscore.

Reference:
https://docs.github.com/en/pages/setting-up-a-github-pages-site-with-jekyll/testing-your-github-pages-site-locally-with-jekyll
