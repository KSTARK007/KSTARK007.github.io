# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Kiran Hombal's static academic site, served by GitHub Pages at https://kstark007.github.io/. There is no site generator, package manager, or test suite: `index.html` and `blog/index.html` are hand-written HTML (Bootstrap 4 from CDN plus `assets/style-2.css`), and every push to `master` deploys via `.github/workflows/deploy.yml`. `README.md` documents the discovery pipeline, IndexNow, blog export builds, and font subsetting in more depth.

## Deploy pipeline

The workflow does three things beyond serving the repo verbatim:

1. **`python3 .github/scripts/stamp_dates.py`** rewrites files in place: it stamps `dateModified` into the JSON-LD of `index.html` and every blog post (plus `article:modified_time` for exported posts) from `git log`, and **regenerates** `sitemap.xml` (blog and `assets/papers/*/*.pdf` entries), `blog/feed.xml`, and the block between `<!-- posts:begin -->` / `<!-- posts:end -->` in `llms.txt`. All of this comes from each post's own `BlogPosting` JSON-LD. Any regex substitution that doesn't match exactly once is a hard failure, so changing the shape of the markup it targets (`"dateModified": "..."`, the `<loc>…</loc><lastmod>` pairs, the llms.txt markers) means updating the script too.
2. **Assembles `_site/` with rsync**, excluding `.git*`, `.github`, `README.md`, `reference/`, `local/`, `*.zip`, then asserts that a fixed list of discovery files exists (Google verification file, IndexNow key file, `llms.txt`, `robots.txt`, `sitemap.xml`, `blog/feed.xml`, and each exported post's `index.md`, `llms.txt`, `opengraph-image.png`).
3. **After deploy, `.github/scripts/indexnow.py`** submits only the changed URLs that also appear in the sitemap (all sitemap URLs if there's no usable base SHA). It imports helpers from `stamp_dates.py`.

The committed `sitemap.xml`, `feed.xml` and `llms.txt` are just output from the last run. The deployed copies get regenerated, so don't hand-edit the generated parts.

Because `stamp_dates.py` mutates the tree and needs full git history, test it on a scratch copy and never in the working tree:

```sh
rsync -a --exclude=.git ./ /tmp/site-test/ && cp -R .git /tmp/site-test/.git
cd /tmp/site-test && python3 .github/scripts/stamp_dates.py
```

## Adding or changing a blog post

A post is either a single `blog/*.html` file or a self-contained Next.js static export in `blog/<slug>/` built in a separate repo and rsynced in wholesale (see README). Don't edit files inside an export by hand; they get replaced on the next rebuild. Every page in `blog/` other than the index must carry a `BlogPosting` JSON-LD node with `headline`, `description`, and ISO 8601 datetime-with-offset `datePublished`/`dateModified` (Google rejects date-only values).

To add a post:
- Add it to the `blogPost` list in `blog/index.html`'s JSON-LD **and** to the visible post list in the body. `stamp_dates.py` fails the build if a post on disk is missing from `blogPost`.
- For a directory export, add its `index.md`, `llms.txt` and `opengraph-image.png` to the required-files loop in `deploy.yml`.
- Sitemap, feed and llms.txt entries are generated automatically, so no edits are needed there.

## Conventions

- **Cache busting:** local CSS/JS are referenced with a `?v=N` query (e.g. `style-2.css?v=3`, `news-fit.js?v=2`). Bump `N` in every `<link rel="preload">` and `<link rel="stylesheet">`/`<script>` that references the file, on both `index.html` and `blog/index.html`, whenever you edit it.
- **Entity graph:** the homepage JSON-LD defines the `Person` (`#kiran`) and `WebSite` (`#website`) nodes. Other pages point to them by `@id` and don't redefine them. JSON-LD must stay valid JSON, since the stamp script parses it after substitution.
- **Homepage content** (news, publications, awards) lives in `index.html`. The Publications section and the prose in `llms.txt` are hand-written and kept in sync with it manually. Paper PDFs go under `assets/papers/<venue>/` and get sitemap entries automatically.
- **Never publish working material:** everything under `blog/` is served verbatim. `local/`, `tmp/`, `docs/`, `reference/`, `blog/review-output/` and `blog/**/*.zip` are gitignored (and the first few are also rsync-excluded) for that reason.
- `robots.txt` deliberately allows all crawlers, including AI crawlers, and disallows only export build artifacts (`_next/`, `__next.*.txt`, the 404 routes).
- `google93b692f99fc0a434.html` (Search Console) and `ff93bf625b094e4f9ba2f616af28cebe.txt` (IndexNow key, public by design) must stay at the repo root.
