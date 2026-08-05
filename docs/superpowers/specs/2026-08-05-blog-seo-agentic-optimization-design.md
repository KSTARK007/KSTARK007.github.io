# Making the blog findable by search engines and by agents

2026-08-05

## The problem

The blog went live with one post, `blog/agentic-coding-in-the-wild/`, a Next.js
static export of a scrollytelling reading of arXiv:2608.00101. The blog landing
page was already well covered — canonical, Open Graph, a `Blog` node wired into
the homepage's entity graph by `@id`. The post was not.

It shipped a title, a description, keywords, a canonical and partial Open Graph,
and nothing else:

- No structured data at all, so nothing said the page explains a specific paper,
  and nothing connected it to the `Person` the rest of the site declares.
- No `og:image`, so every share rendered as a bare text card.
- No breadcrumb, and no link back to `/blog/` — the homepage linked down to the
  blog and the post linked back to the homepage, but the middle edge was missing.
- The framework's default favicon.

And for automated readers specifically: no `/llms.txt`, no feed, and no route to
the post's content cheaper than 96 KB of gzipped HTML whose 23 figures are SVG
path geometry. A model could read the prose and learn nothing from any chart.

## What was rejected

**Post-processing the exported HTML at deploy time.** Durable against re-export
and would have worked for future posts, but it puts the post's metadata in a
different repository from the post, where it cannot be reviewed alongside the
thing it describes. Rejected in favour of fixing it at source.

**A separate no-JS reader page.** Duplicate-content management and a second
rendering path, for a marginal gain over the markdown rendition. YAGNI.

**Dropping the Source Serif `opsz` axis.** Measured at 68 KB off the critical
path (120 KB → 52 KB), the largest single performance win available. Rejected
because it changes how the serif renders between the 84px display headline and
the 16px body, and the agreed scope was performance work with no visual change.
Recorded here because it is the first thing to reconsider if page weight ever
becomes the binding constraint.

## What was built

### In the post's source repository

One JSON-LD `@graph` built from `lib/data/facts.ts`, covering `WebPage`,
`BlogPosting`, `ScholarlyArticle` (the source paper, six authors, arXiv
identifier), `BreadcrumbList`, and a minimal `Person` stub.

Two edges carry the weight:

- `BlogPosting.author` → `https://kstark007.github.io/#kiran`, the `@id` the
  homepage already declares. The post joins the existing entity graph rather
  than starting a second one. The stub under the same `@id` means the reference
  still resolves when the post is crawled standalone.
- `BlogPosting` → `about` + `citation` + `isBasedOn` → the paper node. This is
  the only machine-readable statement that the page explains arXiv:2608.00101.
  Without it a crawler cannot connect the two and a reader arriving from a model
  has no path to the primary source.

**Identity is pinned, not derived.** Canonical, Open Graph URLs and JSON-LD
`@id` all come from `POST.canonicalUrl`, not from the deploy environment.
`NEXT_PUBLIC_SITE_URL` is gone. That repository has its own Pages workflow
targeting `kstark007.github.io/agentic_workload_analysis_website/`; Pages is
currently off there, but if it were ever switched on, the old setup would have
published a second copy that self-canonicalised and competed with the real post.
It now points at the published copy instead. `basePath` still comes from the
environment, which is what that setting is for.

**A generated share card.** Rendered at build from `DATASET`, so the headline
stat cannot drift from the page. Built by a script rather than
`app/opengraph-image.tsx` because under `output: export` that route emits a file
with no extension, which GitHub Pages serves as `application/octet-stream` and
the strict card crawlers refuse.

**The machine-readable rendition** — the core of the agent work. `index.md`
carries the prose, converted from the built HTML so it matches what a reader
sees, plus every figure and table as a markdown table built from the same
constants the page renders from. `llms.txt` orients a reader in a page of text.
`figure-data.json` ships the recovered curve geometry for all 23 plots.

Both generators fail the build rather than emit something partial: the rendition
asserts a minimum prose length, so a markup change that breaks the HTML walk
stops the build instead of shipping a truncated file, and it refuses to run if
`facts.ts` gained a data export with no appendix entry.

### In this repository

- `llms.txt`: hand-written orientation, with the post list generated between
  markers.
- `blog/feed.xml`: a real RSS feed, discoverable from the blog's `<head>`.
- `robots.txt`: disallows only the framework build artifacts inside an exported
  post — `_next/`, the `__next.*.txt` and `index.txt` React Server Component
  payloads, and the export's 404 routes. Those restate every post in a form only
  the client router can use, and left crawlable they compete with the post
  itself. Everything else stays open, AI crawlers included, in a single group
  rather than several named ones that would drift apart.
- `stamp_dates.py`: generates the feed and the `llms.txt` post list from the same
  records that already drove the sitemap, and now stamps exported posts too —
  both the JSON-LD `dateModified` and the `article:modified_time` that has to
  move with it or the page states two different dates.

## Invariants

These are enforced, not documented aspirations. Each one failed loudly during
development at least once.

| Invariant | Enforced by |
|---|---|
| Every `facts.ts` data export appears in the rendition appendix | `generate-rendition.mjs`, fails the build |
| The rendition is not silently truncated | minimum prose length assertion |
| The share card's stats match the page's | rendered from `DATASET` at build |
| A post on disk is listed in the blog index's `blogPost` | `stamp_dates.py`, fails the build |
| `dateModified` and `article:modified_time` agree | both substituted in one pass |
| Sitemap, feed and `llms.txt` agree about the posts | all three generated from one record set |
| Discovery files reach the published site | `deploy.yml` asserts each exists in `_site` |

## Deliberately not done

**Named `User-agent` groups for individual AI crawlers.** robots.txt groups do
not inherit, so each named group would have to repeat every rule, and the copies
would diverge the first time one changed. A single `*` group covers every
crawler and is what they all fall back to. Naming them would be decoration.

**Google Scholar `citation_*` meta tags.** They describe a scholarly work. This
is a blog post about one; claiming otherwise would be a misrepresentation to
exactly the index that cares most. The `citation` edge in the JSON-LD says the
true thing instead.

**`wordCount` in the JSON-LD.** Not used for ranking, and it would have created
a build-order dependency between the rendition generator and the page build for
no gain.
