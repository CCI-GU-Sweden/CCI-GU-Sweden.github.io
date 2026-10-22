# frozen_string_literal: true

source "https://rubygems.org"

# Match the GitHub Pages Jekyll/theme versions without installing its full
# plugin bundle, which pins a vulnerable rubyzip through jekyll-remote-theme.
gem "jekyll", "3.10.0"
gem "jekyll-theme-slate", "0.2.0"
gem "kramdown-parser-gfm", "1.1.0"

group :jekyll_plugins do
  gem "jekyll-github-metadata", "2.16.1"
  gem "jekyll-seo-tag", "2.8.0"
  gem "jekyll-relative-links", "0.6.1"
  gem "jekyll-optional-front-matter", "0.3.2"
  gem "jekyll-readme-index", "0.3.0"
  gem "jekyll-default-layout", "0.1.5"
  gem "jekyll-titles-from-headings", "0.5.3"
end

# Ruby 3 no longer ships the HTTP server used by Jekyll's local preview.
gem "webrick", "~> 1.8"
