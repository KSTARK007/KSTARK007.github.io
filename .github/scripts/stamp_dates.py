#!/usr/bin/env python3
"""Stamp last-modified dates into the site from git history, at deploy time.

Run by .github/workflows/deploy.yml against a full-history checkout. Keeping
this a script rather than inline shell means it can be run locally against a
scratch copy, which is how the substitutions are tested.

Anything that fails to substitute is an error, not a warning: silently shipping
an unstamped page would leave a date that lies about when the page changed,
which is exactly the drift this exists to prevent.
"""

import datetime
import glob
import json
import os
import re
import subprocess
import sys
import xml.dom.minidom
from xml.sax.saxutils import escape as xml_escape

SITE = "https://kstark007.github.io/"
INDEX = "index.html"
SITEMAP = "sitemap.xml"
BLOG_DIR = "blog"
FEED = os.path.join(BLOG_DIR, "feed.xml")
LLMS = "llms.txt"

# The post list in llms.txt is generated between these markers; everything
# around them is hand-written and is left alone.
LLMS_BEGIN = "<!-- posts:begin -->"
LLMS_END = "<!-- posts:end -->"

AUTHOR_NAME = "Kiran Hombal"
AUTHOR_EMAIL = "kiranhombal98@gmail.com"
BLOG_TITLE = "Blog — Kiran Hombal"
BLOG_DESCRIPTION = (
    "Notes and visual readings on computer systems — AI coding agents and LLM "
    "serving, disaggregated memory (CXL), and distributed storage."
)

# Google validates ProfilePage dates against the datetime form with an offset
# (2024-12-23T12:34:00-05:00), not the date-only form, despite the prose in the
# spec saying "ISO 8601 date format".
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$")


def fail(msg):
    print(f"::error::{msg}")
    sys.exit(1)


def git_date(path, fmt):
    """Commit date of the last change to `path`. %cI = ISO 8601, %cs = date."""
    out = subprocess.run(
        ["git", "log", "-1", f"--format={fmt}", "--", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not out:
        fail(f"no commit found for {path} - is this a shallow checkout? "
             f"the workflow needs fetch-depth: 0")
    return out


def sub_once(text, pattern, replacement, what):
    new, n = re.subn(pattern, replacement, text, count=1)
    if n != 1:
        fail(f"{what}: expected exactly 1 substitution, made {n}. "
             f"The markup has changed shape and this script needs updating.")
    return new


def load_ld(text, path):
    """Parse the page's JSON-LD block. Called after stamping, so a parse error
    here means a substitution corrupted the JSON."""
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
    if not m:
        fail(f"JSON-LD block not found in {path}")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        fail(f"{path}: JSON-LD is not valid JSON ({e})")


def site_url(path):
    """Public URL for a repo-relative path. A directory's index.html is served
    at the directory itself, so it gets that form rather than the file name."""
    directory, name = os.path.split(path)
    if name == "index.html":
        return SITE + (directory + "/" if directory else "")
    return SITE + path


def check_post_dates(path, post):
    """A post's own dates must be the form Google accepts, and in order."""
    for field in ("datePublished", "dateModified"):
        value = post.get(field)
        if not value or not ISO_DATETIME.match(value):
            fail(f"{path}: {field}={value!r} is not the ISO 8601 "
                 f"datetime form Google requires")
    # Compared as dates, not instants: a post committed the same day it
    # is published would otherwise trip this on the clock alone.
    published = datetime.datetime.fromisoformat(post["datePublished"]).date()
    modified = datetime.datetime.fromisoformat(post["dateModified"]).date()
    if published > modified:
        fail(f"{path}: datePublished ({published}) is after "
             f"dateModified ({modified}) - is the post dated in the future?")


def stamp_post(path, page_dt, exported):
    """Stamp one post's last-modified date and return what it says about itself.

    Both post shapes carry a BlogPosting in their JSON-LD and both get stamped;
    an exported post additionally carries an article:modified_time meta tag,
    which has to move with the JSON-LD or the page states two different dates.
    """
    text = open(path, encoding="utf-8").read()
    text = sub_once(
        text,
        r'("dateModified":\s*")[^"]*(")',
        lambda m: m.group(1) + page_dt + m.group(2),
        f"{path} dateModified",
    )
    if exported:
        text = sub_once(
            text,
            r'(<meta property="article:modified_time" content=")[^"]*(")',
            lambda m: m.group(1) + page_dt + m.group(2),
            f"{path} article:modified_time",
        )
    open(path, "w", encoding="utf-8").write(text)

    post = next((n for n in load_ld(text, path)["@graph"]
                 if n.get("@type") == "BlogPosting"), None)
    if post is None:
        fail(f"{path}: no BlogPosting node in the JSON-LD. Every page in "
             f"{BLOG_DIR}/ other than the index is expected to be a post.")
    check_post_dates(path, post)

    for field in ("headline", "description"):
        if not post.get(field):
            fail(f"{path}: BlogPosting has no {field}, which the feed and "
                 f"llms.txt entries are built from")

    return post


def stamp_blog():
    """Stamp every post's dateModified from git, and return one record per blog
    page. The records drive sitemap.xml, feed.xml and llms.txt, all of which are
    generated rather than hand-maintained so that adding a post never means
    remembering to edit three files.

    The blog index carries a Blog node listing its posts and has no date of its
    own to stamp; every other page in blog/ must be a BlogPosting.

    A post ships either as a single HTML file here or as a self-contained static
    export in its own subdirectory. The export is generated by another toolchain
    and its prose is never touched, but its dates are stamped the same way: it
    is the deploying repository that knows when the served copy last changed,
    and a build-time date would be the date of whichever build produced it.
    """
    index_path = os.path.join(BLOG_DIR, "index.html")
    if not os.path.isfile(index_path):
        fail(f"{index_path} is missing - the blog section needs a landing page")

    # (path, is the post a directory export) - the index first, then posts.
    pages = [(p, False) for p in sorted(glob.glob(os.path.join(BLOG_DIR, "*.html")))]
    # Only the export's entry point is a page; its 404 and asset routes are not.
    pages += [(p, True) for p in
              sorted(glob.glob(os.path.join(BLOG_DIR, "*", "index.html")))]

    records = []
    for path, exported in pages:
        page_dt = git_date(path, "%cI")   # datetime+offset, for JSON-LD
        page_d = git_date(path, "%cs")    # date only, for the sitemap
        if not ISO_DATETIME.match(page_dt):
            fail(f"git returned {page_dt!r} for {path}, "
                 f"which is not the ISO 8601 datetime form")
        print(f"{path} last changed: {page_dt}")

        is_index = path == index_path
        if is_index:
            index_ld = load_ld(open(path, encoding="utf-8").read(), path)
            post = None
        else:
            post = stamp_post(path, page_dt, exported)

        records.append({
            "url": site_url(path),
            "lastmod": page_d,
            "is_index": is_index,
            "priority": "0.7" if is_index else "0.6",
            "headline": post["headline"] if post else None,
            "description": post["description"] if post else None,
            "published": post["datePublished"] if post else None,
            "modified": post["dateModified"] if post else None,
        })

    # The index's Blog node lists its posts, and that list is hand-written while
    # the sitemap, feed and llms.txt entries are generated. Checking it here is
    # what stops the two from silently diverging as posts are added.
    listed = {
        entry.get("url")
        for node in index_ld["@graph"] if node.get("@type") == "Blog"
        for entry in node.get("blogPost", [])
    }
    for r in records:
        if not r["is_index"] and r["url"] not in listed:
            fail(f"{r['url']} is a post but is not in the blogPost list in "
                 f"{index_path}. Add it there, and to the page body with it.")

    return records


def add_blog_urls(xml_text, entries):
    """Replace the blog's <url> entries with freshly generated ones.

    Any entry already under /blog/ is dropped before the new ones are appended,
    which keeps the script idempotent: running it locally and committing what it
    produced does not wedge the next run the way appending blindly would.
    """
    xml_text = re.sub(
        r"[^\S\n]*<url>\s*<loc>" + re.escape(site_url(BLOG_DIR + "/index.html"))
        + r"[^<]*</loc>.*?</url>\n?",
        "",
        xml_text,
        flags=re.S,
    )
    block = "".join(
        f"  <url>\n"
        f"    <loc>{r['url']}</loc>\n"
        f"    <lastmod>{r['lastmod']}</lastmod>\n"
        f"    <changefreq>monthly</changefreq>\n"
        f"    <priority>{r['priority']}</priority>\n"
        f"  </url>\n"
        for r in entries
    )
    return sub_once(
        xml_text,
        r"</urlset>",
        lambda m: block + "</urlset>",
        "sitemap blog entries",
    )


def rfc2822(iso):
    """RSS wants dates in RFC 822, which is the one thing ISO 8601 is not."""
    dt = datetime.datetime.fromisoformat(iso)
    stamp = dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    return stamp


def write_feed(records):
    """Write blog/feed.xml from the posts' own JSON-LD.

    A feed is the one discovery route that does not depend on a crawler
    choosing to revisit: readers and aggregators are told. Generated from the
    same records as the sitemap so a post cannot appear in one and not the
    other.
    """
    posts = [r for r in records if not r["is_index"]]
    # Newest first, which is the order a feed reader will present them.
    posts.sort(key=lambda r: r["published"], reverse=True)

    items = "".join(
        f"    <item>\n"
        f"      <title>{xml_escape(r['headline'])}</title>\n"
        f"      <link>{r['url']}</link>\n"
        f"      <guid isPermaLink=\"true\">{r['url']}</guid>\n"
        f"      <description>{xml_escape(r['description'])}</description>\n"
        f"      <pubDate>{rfc2822(r['published'])}</pubDate>\n"
        f"      <author>{AUTHOR_EMAIL} ({AUTHOR_NAME})</author>\n"
        f"    </item>\n"
        for r in posts
    )
    built = rfc2822(max(r["modified"] for r in posts)) if posts else ""
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{BLOG_TITLE}</title>\n"
        f"    <link>{SITE}blog/</link>\n"
        f"    <description>{xml_escape(BLOG_DESCRIPTION)}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{built}</lastBuildDate>\n"
        f'    <atom:link href="{SITE}blog/feed.xml" rel="self" '
        'type="application/rss+xml"/>\n'
        f"{items}"
        "  </channel>\n"
        "</rss>\n"
    )
    open(FEED, "w", encoding="utf-8").write(feed)
    xml.dom.minidom.parseString(feed)  # raises if a field broke the markup
    print(f"wrote {FEED} with {len(posts)} item(s)")


def update_llms(records):
    """Regenerate the post list inside llms.txt.

    llms.txt is hand-written prose about the site, except for this one block:
    the posts are filled in from the same records as the sitemap and the feed,
    so the file cannot quietly fall behind the blog.
    """
    posts = [r for r in records if not r["is_index"]]
    posts.sort(key=lambda r: r["published"], reverse=True)

    lines = [
        f"- [{r['headline']}]({r['url']}) ({r['published'][:10]}): "
        f"{r['description']}\n"
        f"  Markdown: {r['url']}index.md\n"
        for r in posts
    ]
    block = "".join(lines)

    text = open(LLMS, encoding="utf-8").read()
    return sub_once(
        text,
        r"(?s)" + re.escape(LLMS_BEGIN) + r"\n.*?" + re.escape(LLMS_END),
        lambda m: LLMS_BEGIN + "\n" + block + LLMS_END,
        "llms.txt post list",
    )


def main():
    page_dt = git_date(INDEX, "%cI")     # datetime+offset, for JSON-LD
    page_d = git_date(INDEX, "%cs")      # date only, for the sitemap
    cv_d = git_date("assets/cv.pdf", "%cs")
    print(f"{INDEX} last changed: {page_dt}")
    print(f"assets/cv.pdf last changed: {cv_d}")

    if not ISO_DATETIME.match(page_dt):
        fail(f"git returned {page_dt!r}, which is not the ISO 8601 datetime form")

    # --- index.html: JSON-LD dateModified ---
    html = open(INDEX, encoding="utf-8").read()
    html = sub_once(
        html,
        r'("dateModified":\s*")[^"]*(")',
        lambda m: m.group(1) + page_dt + m.group(2),
        "index.html dateModified",
    )
    open(INDEX, "w", encoding="utf-8").write(html)

    # --- blog/*.html: stamp each post, collect its sitemap entry ---
    blog_entries = stamp_blog()

    # --- sitemap.xml: one <lastmod> per hand-written <url>, matched via its
    # <loc> so the substitution does not depend on the order entries happen to
    # appear in; the blog's entries are generated and appended ---
    xml_text = open(SITEMAP, encoding="utf-8").read()
    for loc, date, label in (
        (SITE, page_d, "sitemap homepage lastmod"),
        (SITE + "assets/cv.pdf", cv_d, "sitemap cv lastmod"),
    ):
        xml_text = sub_once(
            xml_text,
            r"(<loc>" + re.escape(loc) + r"</loc>\s*<lastmod>)[^<]*",
            lambda m, d=date: m.group(1) + d,
            label,
        )
    xml_text = add_blog_urls(xml_text, blog_entries)
    open(SITEMAP, "w", encoding="utf-8").write(xml_text)

    # --- blog/feed.xml and llms.txt: both generated from the same records, so
    # the three places a post is announced cannot disagree about it ---
    write_feed(blog_entries)
    # Rendered before the file is opened: opening for writing truncates it, and
    # update_llms reads the existing text to substitute into.
    llms_text = update_llms(blog_entries)
    open(LLMS, "w", encoding="utf-8").write(llms_text)

    # --- validate what we are about to publish ---
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    if not m:
        fail("JSON-LD block not found in index.html")
    data = json.loads(m.group(1))  # raises if the stamp corrupted the JSON

    pp = next(n for n in data["@graph"] if n["@type"] == "ProfilePage")
    for field in ("dateCreated", "dateModified"):
        value = pp[field]
        if not ISO_DATETIME.match(value):
            fail(f"{field}={value!r} is not the ISO 8601 datetime form Google requires")
        datetime.datetime.fromisoformat(value)
    if datetime.datetime.fromisoformat(pp["dateCreated"]) > datetime.datetime.fromisoformat(pp["dateModified"]):
        fail("dateCreated is after dateModified")
    if pp["dateModified"] != page_dt:
        fail(f"dateModified is {pp['dateModified']!r}, expected {page_dt!r}")

    xml.dom.minidom.parseString(xml_text)  # raises if the stamp corrupted the XML

    print(f"stamped dateModified={page_dt}")
    print(f"listed {len(blog_entries)} blog page(s) in {SITEMAP}, {FEED} and {LLMS}")
    print("JSON-LD, sitemap.xml and feed.xml all valid")


if __name__ == "__main__":
    main()
