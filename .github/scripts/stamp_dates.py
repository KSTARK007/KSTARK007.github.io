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
import json
import re
import subprocess
import sys
import xml.dom.minidom

INDEX = "index.html"
SITEMAP = "sitemap.xml"

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

    # --- sitemap.xml: one <lastmod> per <url>, matched via its <loc> so the
    # substitution does not depend on the order entries happen to appear in ---
    xml_text = open(SITEMAP, encoding="utf-8").read()
    for loc, date, label in (
        ("https://kstark007.github.io/", page_d, "sitemap homepage lastmod"),
        ("https://kstark007.github.io/assets/cv.pdf", cv_d, "sitemap cv lastmod"),
    ):
        xml_text = sub_once(
            xml_text,
            r"(<loc>" + re.escape(loc) + r"</loc>\s*<lastmod>)[^<]*",
            lambda m, d=date: m.group(1) + d,
            label,
        )
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
    print("JSON-LD and sitemap.xml both valid")


if __name__ == "__main__":
    main()
