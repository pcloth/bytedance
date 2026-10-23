#!/usr/bin/env python3
"""Read the public Douyin mini-app documentation; never call business APIs.

Usage: python tools/sync_official_docs.py [--offline] [--workers 4]
Raw HTML is cached outside the repository. Only public API contracts, not whole
articles or internal publication metadata, are written to the SDK catalog.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import html
import json
import keyword
import os
import re
import sys
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://developer.open-douyin.com"
DOC_ROOT = "/zh-CN/mini-app/develop/server"
CACHE = Path(tempfile.gettempdir()) / "bytedance-official-docs"
GROUPS = {"basic-abilities": "basic", "reach-marketing": "marketing",
          "payment": "payment", "operation": "operation", "locallife": "locallife",
          "industry": "industry", "other": "other"}


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("p", "div", "tr", "li", "br", "h1", "h2", "h3", "pre"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain(value):
    if value and value.lstrip().startswith("{"):
        try:
            document = json.loads(value)
        except ValueError:
            pass
        else:
            parts = []
            def visit(node):
                if isinstance(node, dict):
                    if isinstance(node.get("insert"), str):
                        parts.append(node["insert"])
                    for child in node.values():
                        visit(child)
                elif isinstance(node, list):
                    for child in node:
                        visit(child)
            visit(document)
            if parts:
                return "".join(parts).strip()
    parser = Text()
    parser.feed(value or "")
    return html.unescape("".join(parser.parts)).strip()


def fetch(url, offline=False):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".html")
    if offline and path.exists():
        return path.read_text(encoding="utf-8")
    if offline:
        raise RuntimeError("No cached document: " + url)
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=40)
            response.raise_for_status()
            path.write_text(response.text, encoding="utf-8")
            return response.text
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def object_at(source, start):
    depth, quoted, escaped = 0, False, False
    for pos in range(start, len(source)):
        char = source[pos]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:pos + 1]
    raise ValueError("Incomplete documentation object")


def directory(offline):
    source = fetch(BASE + "/docs/resource" + DOC_ROOT + "/server-api-introduction", offline)
    scripts = re.findall(r'<script[^>]*src="([^"]+)"', source)
    main = next(s for s in scripts if re.search(r"/main\.[^/]+\.js", s))
    if main.startswith("//"):
        main = "https:" + main
    script = fetch(main, offline)
    marker = script.index('Path:"' + DOC_ROOT + '"')
    start = script.rfind("{Title:", 0, marker)
    raw = object_at(script, start)
    raw = re.sub(r'([{,])([A-Za-z_$][A-Za-z0-9_$]*):', r'\1"\2":', raw)
    return json.loads(raw)


def leaves(node, ancestors=()):
    if node.get("Type") == 2:
        yield node, ancestors
    for child in node.get("Children", []):
        yield from leaves(child, ancestors + (node["Title"],))


def clean_schema(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for name, spec in value.items():
        if not isinstance(spec, dict) or spec.get("Hidden"):
            continue
        item = {"required": not spec.get("Optional", True), "type": spec.get("Type")}
        if spec.get("Desc"):
            item["description"] = plain(spec["Desc"])
        if "Example" in spec and spec["Example"] != "":
            item["example"] = spec["Example"]
        if spec.get("Children"):
            item["children"] = clean_schema(spec["Children"])
        result[name] = item
    return result


def identifier(value):
    value = re.sub(r"[^a-zA-Z0-9_]", "_", value)
    if not value or value[0].isdigit():
        value = "api_" + value
    if keyword.iskeyword(value):
        value += "_"
    return value


def read_page(item, offline):
    node, ancestors = item
    url = BASE + "/docs/resource" + node["Path"]
    result = {"title": node["Title"], "doc_path": node["Path"], "url": url,
              "categories": list(ancestors[1:])}
    if any("历史" in name or "不推荐" in name for name in ancestors + (node["Title"],)):
        result.update(kind="historical", reason="Official historical/not recommended category")
        return result
    try:
        for candidate in (url, url + "/", url.replace("developer.open-douyin.com", "partner.open-douyin.com")):
            source = fetch(candidate, offline)
            marker = source.index("_ROUTER_DATA = ") + len("_ROUTER_DATA = ")
            router = json.loads(object_at(source, marker))
            data = next(v["data"] for v in router["loaderData"].values()
                        if isinstance(v, dict) and isinstance(v.get("data"), dict))
            if data.get("title"):
                if candidate != url:
                    result["resolved_url"] = candidate
                break
        result["doc_type"] = data.get("docType")
        result["scope"] = data.get("scope", "")
        result["page_title"] = data.get("title", "")
        # All three metadata slots sometimes contain identical sample-code-only
        # objects. A real endpoint must have its own Path and request schema.
        for key in ("openApiMeta", "unRegulatoryOpenApiMeta", "webhookApiMeta", "spiApiMeta"):
            meta = data.get(key) or {}
            if meta.get("Path"):
                result[key] = {
                    "id": str(meta.get("EndpointId", "")), "name": meta.get("Name", ""),
                    "path": meta["Path"], "domain": meta.get("Domain", ""),
                    "method_code": meta.get("Method"), "version": meta.get("Version", ""),
                    "sandbox": meta.get("SupportSandBox", False),
                    "request": {k: clean_schema(v) for k, v in meta.get("ReqSchema", {}).items()},
                    "response": {k: clean_schema(v) for k, v in meta.get("RespSchema", {}).items()},
                    "token_metadata": meta.get("Token"),
                }
        if data.get("docType") == 5:
            meta = data.get("webhookApiMeta") or {}
            result["event"] = meta.get("Identify", "")
            result["kind"] = "callback"
        result.setdefault("kind", "review")
        # Plain page text is cached only in /tmp for reviewing manual contracts.
        (CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".txt")).write_text(
            plain(source), encoding="utf-8")
        if not result["page_title"]:
            result.update(kind="unresolved", reason="Official page contains no document body")
    except Exception as exc:
        result.update(kind="unresolved", reason=str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    entries = list(leaves(directory(args.offline)))
    pages = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for index, page in enumerate(executor.map(lambda x: read_page(x, args.offline), entries), 1):
            pages.append(page)
            if index % 40 == 0:
                print("Read {}/{} documents".format(index, len(entries)), flush=True)
    catalog = {"source": BASE + "/docs/resource" + DOC_ROOT + "/",
               "checked_at": datetime.date.today().isoformat(), "pages": pages}
    output = ROOT / "docs" / "official_catalog.json"
    output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Saved {} pages to {}".format(len(pages), output))


if __name__ == "__main__":
    main()
