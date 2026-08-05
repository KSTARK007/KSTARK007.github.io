#!/usr/bin/env python3
"""Tell the IndexNow search engines which URLs changed in this push.

Run by .github/workflows/deploy.yml *after* the deploy job succeeds. Submitting
before the content is live would only invite a crawl of the old copy.

One request to api.indexnow.org is forwarded to every participating engine —
Bing, Yandex, Seznam, Naver, Yep. Google does not participate and has never
adopted the protocol, so nothing here reaches it; for Google the sitemap and
Search Console remain the only route.

The key is not a secret. IndexNow proves control of a host by requiring the key
to be readable at https://<host>/<key>.txt, so it is public by construction, and
the worst anyone can do with it is ask a search engine to recrawl this site.

Only URLs whose files actually changed are submitted. The protocol asks for
this, and submitting an unchanged page teaches the engines nothing.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import xml.dom.minidom

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stamp_dates import SITE, SITEMAP, site_url  # noqa: E402

ENDPOINT = "https://api.indexnow.org/indexnow"
KEY = "ff93bf625b094e4f9ba2f616af28cebe"
HOST = "kstark007.github.io"
# The protocol's per-request ceiling. This site is nowhere near it; the check
# exists so that a future bulk change fails loudly rather than being truncated.
MAX_URLS = 10_000


def sitemap_urls():
    """Every URL we are willing to submit. The sitemap is the definition of
    what counts as a page here, so anything outside it is not ours to announce."""
    doc = xml.dom.minidom.parse(SITEMAP)
    return {
        loc.firstChild.nodeValue.strip()
        for loc in doc.getElementsByTagName("loc")
        if loc.firstChild
    }


def changed_paths(before, after):
    """Files touched between two commits, or None if that cannot be determined.

    A first push, a force push, or a manual workflow_dispatch all leave us
    without a usable base. None means "no opinion", and the caller falls back to
    submitting everything rather than silently submitting nothing.
    """
    if not before or not after or set(before) == {"0"}:
        return None
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", before, after],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        # The base commit is not in this checkout - shallow clone, or the
        # branch was rewritten. Treat it the same as having no base.
        return None
    return [line for line in out.splitlines() if line]


def urls_for(paths, known):
    """Map changed files to the page URLs they are.

    Deliberately narrow: a path counts only if it maps to a URL the sitemap
    already lists. A changed JS chunk or an edited script is not a page, and an
    exported post's asset should not re-announce the post.
    """
    found = set()
    for path in paths:
        url = site_url(path)
        if url in known:
            found.add(url)
    return found


def submit(urls):
    payload = json.dumps({
        "host": HOST,
        "key": KEY,
        "keyLocation": f"{SITE}{KEY}.txt",
        "urlList": sorted(urls),
    }).encode()

    req = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read(2000).decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode(errors="replace")
    except urllib.error.URLError as e:
        return None, str(e.reason)


def main():
    known = sitemap_urls()
    if not known:
        print("::error::no URLs in sitemap.xml, nothing could be submitted")
        return 1

    paths = changed_paths(os.environ.get("BEFORE_SHA"), os.environ.get("AFTER_SHA"))
    if paths is None:
        print("no usable base commit; submitting every sitemap URL")
        urls = known
    else:
        urls = urls_for(paths, known)
        if not urls:
            print(f"{len(paths)} file(s) changed, none of them a listed page. "
                  f"Nothing to submit.")
            return 0

    if len(urls) > MAX_URLS:
        print(f"::error::{len(urls)} URLs exceeds the {MAX_URLS} per-request "
              f"limit; this needs batching")
        return 1

    print(f"submitting {len(urls)} URL(s):")
    for u in sorted(urls):
        print(f"  {u}")

    status, body = submit(urls)

    # 200 accepted outright; 202 accepted with the key still to be validated,
    # which is the normal answer the first time a new key is used.
    if status in (200, 202):
        print(f"IndexNow accepted the submission (HTTP {status})")
        return 0
    # A bad key or a host mismatch is a real misconfiguration and stays broken
    # until someone looks, so it is worth reddening the run. The deploy itself
    # has already succeeded by this point; the site is live either way.
    if status in (400, 403, 422):
        print(f"::error::IndexNow rejected the submission (HTTP {status}): {body}")
        print(f"::error::check that {SITE}{KEY}.txt is reachable and contains "
              f"exactly the key")
        return 1
    # Rate limiting or an outage on their side. Not worth failing a deploy for;
    # the sitemap still carries the same information at the next crawl.
    print(f"::warning::IndexNow did not accept the submission "
          f"(HTTP {status}): {body}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
