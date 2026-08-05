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

SITE = "https://kstark007.github.io/"
INDEX = "index.html"
SITEMAP = "sitemap.xml"
BLOG_DIR = "blog"

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


def stamp_blog():
    """Stamp each post's dateModified from git, and return one sitemap entry
    per blog page. The entries are generated rather than substituted so that
    adding a post never means remembering to hand-edit sitemap.xml.

    The blog index carries a Blog node listing its posts and has no date of its
    own to stamp; every other page in blog/ must be a BlogPosting.
    """
    index_path = os.path.join(BLOG_DIR, "index.html")
    if not os.path.isfile(index_path):
        fail(f"{index_path} is missing - the blog section needs a landing page")

    entries = []
    for path in sorted(glob.glob(os.path.join(BLOG_DIR, "*.html"))):
        page_dt = git_date(path, "%cI")   # datetime+offset, for JSON-LD
        page_d = git_date(path, "%cs")    # date only, for the sitemap
        if not ISO_DATETIME.match(page_dt):
            fail(f"git returned {page_dt!r} for {path}, "
                 f"which is not the ISO 8601 datetime form")
        print(f"{path} last changed: {page_dt}")

        text = open(path, encoding="utf-8").read()
        is_index = path == index_path

        if is_index:
            load_ld(text, path)
        else:
            text = sub_once(
                text,
                r'("dateModified":\s*")[^"]*(")',
                lambda m: m.group(1) + page_dt + m.group(2),
                f"{path} dateModified",
            )
            open(path, "w", encoding="utf-8").write(text)

            post = next((n for n in load_ld(text, path)["@graph"]
                         if n.get("@type") == "BlogPosting"), None)
            if post is None:
                fail(f"{path}: no BlogPosting node in the JSON-LD. Every page in "
                     f"{BLOG_DIR}/ other than the index is expected to be a post.")
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

        entries.append((site_url(path), page_d, "0.7" if is_index else "0.6"))

    # A post can also ship as a self-contained static export in its own
    # subdirectory (blog/<slug>/index.html) rather than as a single file. That
    # HTML is generated by another toolchain and carries its own metadata, so it
    # is listed in the sitemap but never rewritten. Only the export's entry
    # point is listed; its 404 and asset routes are not content.
    for path in sorted(glob.glob(os.path.join(BLOG_DIR, "*", "index.html"))):
        page_d = git_date(path, "%cs")
        print(f"{path} last changed: {page_d} (exported post, listed but not stamped)")
        entries.append((site_url(path), page_d, "0.6"))

    return entries


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
        f"    <loc>{loc}</loc>\n"
        f"    <lastmod>{date}</lastmod>\n"
        f"    <changefreq>monthly</changefreq>\n"
        f"    <priority>{priority}</priority>\n"
        f"  </url>\n"
        for loc, date, priority in entries
    )
    return sub_once(
        xml_text,
        r"</urlset>",
        lambda m: block + "</urlset>",
        "sitemap blog entries",
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
    print(f"listed {len(blog_entries)} blog page(s) in {SITEMAP}")
    print("JSON-LD and sitemap.xml both valid")


if __name__ == "__main__":
    main()
