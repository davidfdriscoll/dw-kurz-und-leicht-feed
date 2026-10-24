#!/usr/bin/env python3
"""Rebuild DW's "Kurz und leicht" podcast feed with working <enclosure> tags.

DW's own feed (rss.dw.com/xml/DKpodcast_kurzundleicht_de) stopped carrying
enclosures in Aug 2026. Each episode's article page still embeds an HLS URL
whose progressive-MP4 twin lives on tvdownloaddw-a.akamaihd.net, so we look
that up per episode and splice it back in.
"""
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE = "https://rss.dw.com/xml/DKpodcast_kurzundleicht_de"
SELF_URL = "https://davidfdriscoll.github.io/dw-kurz-und-leicht-feed/feed.xml"
PREFERRED = "AVC_640x360"  # smallest sensible file; Overcast mostly plays it as audio
MAX_LOOKUPS = 40  # per run, so a cold cache doesn't hammer DW
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

ROOT = Path(__file__).parent
CACHE = ROOT / "cache.json"
OUT = ROOT / "public" / "feed.xml"

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "spotify": "http://www.spotify.com/ns/rss",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "georss": "http://www.georss.org/georss",
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def fetch(url, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30)


def resolve(article_url):
    """Article page -> (mp4 url, byte length), or None."""
    html = fetch(article_url).read().decode("utf-8", "replace")
    m = re.search(r"https?://hlsvod\.dw\.com/i/(vps/webvideos/[^\"\\ ]+?)_,([^\"\\ ]+?),\.mp4\.csmil/master\.m3u8", html)
    if not m:
        return None
    path, variants = m.group(1), m.group(2).split(",")
    variant = PREFERRED if PREFERRED in variants else variants[0]
    mp4 = f"https://tvdownloaddw-a.akamaihd.net/{path}_{variant}.mp4"
    with fetch(mp4, method="HEAD") as r:
        return mp4, int(r.headers.get("Content-Length", 0))


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    tree = ET.ElementTree(ET.fromstring(fetch(SOURCE).read()))
    channel = tree.getroot().find("channel")

    self_link = channel.find("atom:link", NS)
    if self_link is not None:
        self_link.set("href", SELF_URL)

    lookups = 0
    for item in list(channel.findall("item")):
        guid = item.findtext("guid")
        enc = item.find("enclosure")
        if enc is not None:
            cache.setdefault(guid, {"url": enc.get("url"), "length": int(enc.get("length") or 0)})
            continue
        if guid not in cache and lookups < MAX_LOOKUPS:
            lookups += 1
            try:
                found = resolve(item.findtext("link"))
            except Exception as e:  # one bad page shouldn't sink the feed
                print(f"warn: {guid}: {e}", file=sys.stderr)
                found = None
            if found:
                cache[guid] = {"url": found[0], "length": found[1]}
        if guid in cache:
            ET.SubElement(item, "enclosure", url=cache[guid]["url"],
                          type="video/mp4", length=str(cache[guid]["length"]))
        else:
            channel.remove(item)  # nothing playable; leave it out

    OUT.parent.mkdir(exist_ok=True)
    ET.indent(tree, space=" ")
    tree.write(OUT, encoding="UTF-8", xml_declaration=True)
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n")
    kept = len(channel.findall("item"))
    print(f"{kept} episodes written, {lookups} page lookups")


if __name__ == "__main__":
    main()
