"""
Inspects ieslibrary.com's structure before we build a real downloader --
same principle as ifc_extractor.py's inspect_file(): look at what's
actually there before writing code that assumes a structure.

Uses Python's standard library (urllib) plus certifi for SSL certificates
-- macOS Python installed from python.org (rather than Homebrew or system
Python) commonly doesn't trust your Mac's certificate store automatically,
causing CERTIFICATE_VERIFY_FAILED errors. certifi bundles a trusted
certificate set directly, sidestepping that -- more portable than relying
on the "Install Certificates.command" script some installs include, since
that fix depends on exactly how Python was installed.

Requires: pip install certifi

Usage: python3 inspect_ieslibrary.py
"""

import ssl
import html
import urllib.request

import certifi

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

HEADERS = {
    # A real, honest User-Agent identifying this as a script, not
    # pretending to be a regular browser -- good scraping etiquette.
    "User-Agent": "ies-library-inspector/0.1 (personal lighting-design project)"
}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return None, str(e)


def main():
    print("--- Checking robots.txt (already confirmed permissive, re-checking programmatically) ---")
    status, body = fetch("https://ieslibrary.com/robots.txt")
    print(f"Status: {status}")
    if body:
        print(body[:500])

    print("\n--- Checking for sitemap.xml ---")
    sub_sitemap_url = None
    for path in ["/sitemap.xml", "/sitemap_index.xml", "/en/sitemap.xml"]:
        status, body = fetch(f"https://ieslibrary.com{path}")
        print(f"{path}: status={status}")
        if body and status == 200:
            print("FOUND. First 1000 chars:")
            print(body[:1000])
            import re
            match = re.search(r"<loc>([^<]+)</loc>", body)
            if match:
                sub_sitemap_url = match.group(1)
            break

    if sub_sitemap_url:
        sub_sitemap_url = html.unescape(sub_sitemap_url)  # fix: XML has &amp; not &,
        # which broke the query string (?sitemap=pages&amp;cHash=... was being sent
        # literally instead of as two separate query params) and caused the previous
        # run to loop back on a malformed request instead of fetching the real content.
        print(f"\n--- Following sub-sitemap: {sub_sitemap_url} ---")
        status, body = fetch(sub_sitemap_url)
        print(f"Status: {status}")
        if body:
            print(f"Length: {len(body)} chars")
            import re
            urls = re.findall(r"<loc>([^<]+)</loc>", body)
            print(f"URLs found in this sitemap: {len(urls)}")
            print("Sample of first 15:")
            for u in urls[:15]:
                print(f"  {u}")
            # Check whether any of these look like individual product/file pages
            # vs. just CMS content pages (blog posts, about pages, etc.)
            product_like = [u for u in urls if any(kw in u.lower() for kw in
                             ["light", "download", "product", "ies", "browse"])
                             and "spotlight" not in u.lower()]
            print(f"\nURLs that might be product/file pages (not blog content): {len(product_like)}")
            print("Sample:", product_like[:10])

    print("\n--- Fetching the browse page to inspect its structure ---")
    status, body = fetch("https://ieslibrary.com/en/browse")
    print(f"Status: {status}")
    if body:
        print(f"Page length: {len(body)} chars")
        # Look for anything that looks like a link to an individual file
        # or a .ies download, without assuming a specific HTML structure.
        import re
        ies_links = re.findall(r'href="([^"]*\.ies[^"]*)"', body, re.IGNORECASE)
        detail_links = re.findall(r'href="([^"]*(?:light|luminaire|file|item)[^"]*)"', body, re.IGNORECASE)
        print(f"Direct .ies links found: {len(ies_links)}")
        print(f"Sample: {ies_links[:5]}")
        print(f"Possible detail-page links found: {len(detail_links)}")
        print(f"Sample: {detail_links[:5]}")
    else:
        print(f"Could not fetch page: {body}")


if __name__ == "__main__":
    main()