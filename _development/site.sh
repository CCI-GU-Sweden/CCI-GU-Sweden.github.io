#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v ruby >/dev/null || ! command -v gem >/dev/null; then
  echo 'Install Ruby first (Ubuntu / WSL):' >&2
  echo 'sudo apt-get update && sudo apt-get install -y ruby-full ruby-dev build-essential zlib1g-dev' >&2
  exit 1
fi

# Keep downloaded gems and Bundler inside this checkout; no sudo gem install.
export GEM_HOME="$PWD/.local/gems"
export GEM_PATH="$GEM_HOME:$(ruby -e 'puts Gem.default_dir')"
export PATH="$GEM_HOME/bin:$PATH"
export JEKYLL_ENV=development

case "${1:-serve}" in
  setup)
    if [[ ! -x "$GEM_HOME/bin/bundle" ]]; then
      gem install bundler --version '~> 2.5.0' --no-document
    fi
    bundle config set --local path vendor/bundle
    bundle install
    ;;
  serve|check)
    if [[ ! -x "$GEM_HOME/bin/bundle" ]]; then
      echo 'Run bash _development/site.sh setup first.' >&2
      exit 1
    fi
    bundle check
    if [[ "${1:-serve}" == check ]]; then
      bundle exec jekyll build --config _config.yaml,_development/config.yml --strict_front_matter
    else
      # Recreate preview output and Jekyll caches before starting the watcher.
      # The development config also tells browsers not to cache responses.
      bundle exec jekyll clean --config _config.yaml,_development/config.yml
      exec bundle exec jekyll serve --config _config.yaml,_development/config.yml --livereload
    fi
    ;;
  *)
    echo 'Usage: bash _development/site.sh [setup|serve|check]' >&2
    exit 1
    ;;
esac
