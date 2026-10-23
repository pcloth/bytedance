#!/usr/bin/env python3
"""Normalize reviewed official contracts and generate the static SDK surface.

Run sync_official_docs.py first, then this script. Contract overrides are used
only for individually reviewed old-format documents or browser-only pages.
"""
import collections
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from sync_official_docs import CACHE, DOC_ROOT, GROUPS, ROOT, identifier, plain

ERROR_FIELDS = {"err_no", "error_no", "errcode", "error_code", "error", "code"}


def errors(schema, prefix=""):
    result = []
    for key, item in schema.items():
        path = prefix + key
        if key in ERROR_FIELDS and not item.get("children"):
            result.append(path)
        if key in ("data", "extra", "result"):
            result.extend(errors(item.get("children", {}), path + "."))
    return result


def defaults(request):
    result = {}
    for where, fields in request.items():
        location = {"BodyParam": "body", "QueryParam": "query", "HeaderParam": "header"}.get(where)
        if not location:
            continue
        for field in fields:
            value = {"appid": "app_id", "app_id": "app_id", "client_key": "app_id",
                     "secret": "app_secret", "client_secret": "app_secret"}.get(field)
            if value:
                result.setdefault(location, {})[field] = value
    return result


def credential_kind(text):
    if "client_token" in text or "clt." in text:
        return "client"
    if "business_token" in text or "bus_act." in text:
        return "business"
    if "oauth/access_token" in text:
        return "user"
    if "get_auth_token" in text or "authorizer_access_token" in text:
        return "authorizer"
    if "component_access_token" in text:
        return "component"
    if "apps/v2/token" in text or "getAccessToken" in text or "小程序" in text or "X-Token" in text:
        return "mini_app"
    return "explicit"


def metadata_contract(page, meta):
    request = meta["request"]
    spec = {"domain": meta["domain"].rstrip("/"), "path": meta["path"],
            "method": {1: "GET", 2: "POST", 3: "PUT", 4: "HEAD", 5: "DELETE", 6: "OPTIONS", 7: "PATCH"}[meta["method_code"]],
            "sandbox": bool(meta["sandbox"]), "encoding": "json",
            "defaults": defaults(request), "error_paths": errors(meta["response"].get("BodyParam", {}))}
    token = meta.get("token_metadata") or {}
    info = token.get("InfoV2") or token
    active = not info.get("Hidden", token.get("Hidden", True))
    for where, fields in request.items():
        for name, item in fields.items():
            location = {"HeaderParam": "header", "QueryParam": "query", "BodyParam": "body"}.get(where)
            if location and name.lower() in ("access-token", "access_token", "x-token", "client_token"):
                description = item.get("description", "")
                # TokenUsage explicitly records separate direct/service-provider flows.
                usage = [x for x in info.get("TokenUsage", []) if x.get("ShowInDoc", True)]
                direct = [x for x in usage if "非服务商" in x.get("Scene", "") or "应用授权" in x.get("Scene", "")]
                evidence = json.dumps(direct or usage, ensure_ascii=False) if usage else description
                spec["auth"] = {"in": location, "name": name, "kind": credential_kind(evidence)}
    if "auth" not in spec and active:
        position = info.get("Position", "header")
        if position in ("header", "query", "body"):
            spec["auth"] = {"in": position, "name": info.get("Name", token.get("Name", "access-token")),
                            "kind": credential_kind(json.dumps(info, ensure_ascii=False))}
    for name, item in request.get("HeaderParam", {}).items():
        if name.lower() == "byte-authorization":
            spec["signing"] = "rsa"
        if name.lower() == "content-type":
            content_type = (item.get("description", "") + str(item.get("example", ""))).lower()
            if "multipart/form-data" in content_type:
                spec["encoding"] = "multipart"
            elif "application/x-www-form-urlencoded" in content_type:
                spec["encoding"] = "form"
    # A file field is sufficient evidence for multipart even when Content-Type
    # is missing from the published schema.
    if any(v.get("type") == 9 for v in request.get("BodyParam", {}).values()):
        spec["encoding"] = "multipart"
    if spec["path"] == "/api/apps/v2/token":
        spec["defaults"].setdefault("body", {})["grant_type"] = "client_credential"
    if spec["path"] == "/oauth/client_token/":
        spec["defaults"].setdefault("body", {})["grant_type"] = "client_credential"
    response_headers = str(meta["response"].get("HeaderParam", {})).lower()
    spec["binary"] = any(x in response_headers for x in ("image/", "octet-stream", "application/zip"))
    return spec


def cached_page(page):
    digest = hashlib.sha256(page["url"].encode()).hexdigest()
    source = (CACHE / (digest + ".html")).read_text(encoding="utf-8")
    text = (CACHE / (digest + ".txt")).read_text(encoding="utf-8")
    text = text[text.rfind("我的收藏"):].split("该文档是否有帮助")[0].replace("\x00", "")
    return source, text


def manual_contract(page):
    source, text = cached_page(page)
    if any(word in page["title"] for word in ("接入指南", "API列表", "常见问题", "FAQ", "结算说明", "收费规则")):
        return "guide", None
    url, method = None, None
    basic = re.search(r"HTTP URL\s*([\s\S]*?)HTTP Method\s*(GET|POST|PUT|DELETE)", text, re.I)
    if basic:
        urls = re.findall(r"https://[a-zA-Z0-9.\-]+/[a-zA-Z0-9_/.-]+", basic.group(1))
        urls = [u for u in urls if "open-sandbox" not in u]
        if urls:
            url, method = urls[0], basic.group(2).upper()
    if not url:
        match = re.search(r"\b(GET|POST|PUT|DELETE)\s+(https://[a-zA-Z0-9.\-]+/[a-zA-Z0-9_/.-]+)", text)
        if match:
            method, url = match.groups()
    if not url:
        if (any(x in text for x in ("回调参数", "回调地址", "扩展点", "event", "消息推送")) or any(
                x in page["title"] for x in ("回调", "通知", "推送", "事件", "扩展点"))) and not any(
                x in page["title"] for x in ("介绍", "设置", "查询回调地址", "指南", "说明")):
            return "callback", None
        return "guide", None
    if not urlsplit(url).hostname in ("developer.toutiao.com", "open.douyin.com", "webcast.bytedance.com"):
        return "guide", None
    request_text = re.split(r"\n\s*(?:响应参数|返回值|返回参数|返回示例)\s*\n", text, maxsplit=1)[0]
    spec = {"method": method, "domain": "https://" + urlsplit(url).netloc,
            "path": urlsplit(url).path, "sandbox": "https://open-sandbox.douyin.com" in text,
            "encoding": "multipart" if ("multipart" in request_text or "--form " in request_text) else "json",
            "defaults": {}, "error_paths": ["err_no", "error_no", "error", "errcode", "error_code",
                "code", "extra.error_code", "extra.sub_error_code", "data.error_code"]}
    where = "query" if method == "GET" else "body"
    for name in ("app_id", "appid", "client_key"):
        if re.search(r"(?:^|\n)\s*" + name + r"\s*\n", request_text):
            spec["defaults"].setdefault(where, {})[name] = "app_id"
    if re.search(r"(?:^|\n)\s*X-Token\s*\n", request_text, re.I):
        spec["auth"] = {"in": "header", "name": "X-Token", "kind": "mini_app"}
    elif re.search(r"(?:^|\n)\s*access-token(?:必填\w*)?\s*\n", request_text, re.I):
        spec["auth"] = {"in": "header", "name": "access-token", "kind": credential_kind(request_text)}
    elif re.search(r"(?:^|\n)\s*access_token\s*\n", request_text):
        spec["auth"] = {"in": where, "name": "access_token", "kind": "mini_app"}
    if "/trade-system/trading/" in page["doc_path"] and "/api/apps/trade/" in url:
        spec["signing"] = "rsa"
        spec.pop("auth", None)
    if ("/locallife/" in page["doc_path"] or "/trade-system/general/" in page["doc_path"]) and not "/api/apps/ecpay/" in url:
        spec.setdefault("auth", {"in": "header", "name": "access-token", "kind": "client"})
    if ("/ecpay/" in url or "/bills" in spec["path"]) and re.search(r"(?:^|\n)\s*sign\s*\n", request_text):
        spec["signing"] = "ecpay"
    if "Byte-Authorization" in request_text:
        spec["signing"] = "rsa"
    if "/bills" in spec["path"]:
        spec["binary"] = True
    return "api", spec


def callback_protocol(page):
    if "/payment/ecpay/" in page["doc_path"]:
        return "ecpay"
    if any(x in page["doc_path"] for x in ("/payment/", "/locallife/")):
        return "trade"
    return "webhook"


def main():
    catalog = json.loads((ROOT / "docs/official_catalog.json").read_text(encoding="utf-8"))
    overrides = json.loads((ROOT / "docs/contract_overrides.json").read_text(encoding="utf-8"))
    contracts, roots, callbacks = {}, {}, []
    for page in catalog["pages"]:
        relative = page["doc_path"].split(DOC_ROOT + "/", 1)[1]
        override = overrides.get(relative, {})
        if page["kind"] == "historical":
            continue
        if relative.split("/")[0] not in GROUPS:
            page["kind"] = "guide"
            continue
        spec = None
        meta = page.get("openApiMeta") or page.get("unRegulatoryOpenApiMeta")
        if override.get("contract"):
            spec = override["contract"]
            page.update(kind="api", reason=override["reason"])
        elif meta:
            page["kind"] = "api"
            spec = metadata_contract(page, meta)
            # Some regenerated metadata contradicts the still-published manual
            # contract (notably X-Token card APIs). Prefer the concrete HTTP
            # article when it documents the SAME endpoint, never a linked API.
            manual_kind, manual = manual_contract(page)
            if manual_kind == "api" and manual["path"] == spec["path"]:
                manual_auth = manual.get("auth", {})
                if manual_auth.get("name") == "X-Token":
                    spec["auth"] = manual_auth
                    spec["encoding"] = manual["encoding"]
                    spec["error_paths"] = manual["error_paths"]
                    page["contract_note"] = "Manual HTTP article overrides conflicting regenerated token metadata"
            if not spec["error_paths"]:
                spec["error_paths"] = ["err_no", "error_no", "error", "errcode", "error_code", "code",
                                       "extra.error_code", "data.error_code"]
        elif page["kind"] != "unresolved":
            page["kind"], spec = manual_contract(page)
        if override.get("kind"):
            page["kind"] = override["kind"]
            page["reason"] = override["reason"]
            if page["kind"] != "api":
                spec = None
        if page["kind"] == "guide":
            page.setdefault("reason", "Guide, shared parameters, client-side helper or redirect; no separate server endpoint")
        if spec:
            spec.update(override.get("patch", {}))
            segments = relative.split("/")
            segments[0] = GROUPS[segments[0]]
            segments = [identifier(s).lower() for s in segments]
            name = ".".join(segments)
            page["sdk_method"] = name
            spec.update(title=page["title"], url=page["url"], scope=page.get("scope", ""))
            if not spec.get("domain") or not spec.get("path", "").startswith("/"):
                raise ValueError("Incomplete contract: " + name)
            contracts[name] = spec
            tree = roots
            for segment in segments[:-1]:
                tree = tree.setdefault(segment, {})
            if segments[-1] in tree:
                raise ValueError("Namespace collision: " + name)
            tree[segments[-1]] = name
        if page["kind"] == "callback":
            page["protocol"] = override.get("protocol", callback_protocol(page))
            if "protocol" not in override:
                _, article = cached_page(page)
                if "Byte-Signature" in article:
                    page["protocol"] = "trade"
                elif "msg_signature" in article:
                    page["protocol"] = "ecpay"
            callbacks.append({"title": page["title"], "url": page["url"], "protocol": page["protocol"]})
    if any(p["kind"] == "review" for p in catalog["pages"]):
        raise ValueError("Unclassified documents remain")
    directory = ROOT / "src/bytedance"
    (directory / "contracts.json").write_text(
        json.dumps(contracts, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ['# -*- coding: utf-8 -*-', '"""Generated by tools/build_catalog.py; edit the reviewed catalog instead."""',
             'import json', 'import os', '',
             'with open(os.path.join(os.path.dirname(__file__), "contracts.json"), encoding="utf-8") as _stream:',
             '    CONTRACTS = json.load(_stream)', '', '']
    def generate(tree, parts):
        class_name = "Api_" + "_".join(parts)
        for key, value in tree.items():
            if isinstance(value, dict):
                generate(value, parts + [key])
        lines.extend(['class {}(object):'.format(class_name), '    def __init__(self, client):',
                      '        self._client = client'])
        for key, value in tree.items():
            if isinstance(value, dict):
                lines.append('        self.{} = Api_{}(client)'.format(key, "_".join(parts + [key])))
        for key, value in tree.items():
            if isinstance(value, str):
                lines.extend(['', '    def {}(self, body=None, query=None, headers=None, files=None, path_params=None, token=None):'.format(key),
                              '        """{}\n\n        {}\n        """'.format(contracts[value]["title"].replace('"', "'"), contracts[value]["url"]),
                              '        return self._client.call({!r}, body, query, headers, files, path_params, token)'.format(value)])
        lines.extend(['', ''])
    for key, value in roots.items():
        generate(value, [key])
    lines.append('def attach(client):')
    for key in GROUPS.values():
        lines.append('    client.{} = Api_{}(client)'.format(key, key))
    (directory / "generated.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Contracts shared across document entries use one transport specification;
    # keep documented namespace aliases so every page remains discoverable.
    canonical = {}
    for name, spec in contracts.items():
        identity = (spec["method"], spec["domain"], spec["path"])
        if identity in canonical:
            spec["alias_of"] = canonical[identity]
        else:
            canonical[identity] = name
    (directory / "contracts.json").write_text(
        json.dumps(contracts, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = dict(collections.Counter(p["kind"] for p in catalog["pages"]))
    catalog["summary"] = dict(summary, sdk_methods=len(contracts), unique_endpoints=len(canonical))
    (ROOT / "docs/official_catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    docs = ["# 小程序服务端接口索引", "", "核对日期：" + catalog["checked_at"], "",
            "以下清单来自官方目录；文档页数与主动调用接口数量不同。", "",
            "统计：`{}`。".format(json.dumps(catalog["summary"], ensure_ascii=False)), "",
            "所有新增方法接受 body/query/headers/files/path_params 字典及可选 token，返回官方完整响应。", "",
            "## 主动调用接口", "", "| SDK 方法（前缀 app.） | 官方文档 | HTTP | 鉴权 |", "| --- | --- | --- | --- |"]
    for name, spec in contracts.items():
        auth = spec.get("auth") or {}
        docs.append("| `{}` | [{}]({}) | {} `{}` | {} {} |".format(
            name, spec["title"].strip(), spec["url"], spec["method"], spec["path"],
            auth.get("kind", "none"), spec.get("signing", "")))
    docs.extend(["", "## 单独核对及文档差异", "",
                 "以下条目使用了官方正文、旧文档地址或官方 SDK 交叉核对；具体契约和依据保存在 contract_overrides.json。", ""])
    for page in catalog["pages"]:
        relative = page["doc_path"].split(DOC_ROOT + "/", 1)[1]
        override = overrides.get(relative, {})
        if override or page.get("contract_note"):
            evidence = override.get("evidence", page["url"])
            docs.append("- [{}]({}): {}".format(page["title"], evidence,
                        override.get("reason", page.get("contract_note", ""))))
    for kind, label in (("callback", "平台回调"), ("guide", "说明页"), ("historical", "历史版本（不新增）"), ("unresolved", "待核实文档（不计入已实现）")):
        docs.extend(["", "## " + label, ""])
        for page in catalog["pages"]:
            if page["kind"] == kind:
                detail = page.get("protocol") or page.get("reason", "")
                docs.append("- [{}]({}){}".format(page["title"].strip(), page["url"], " — " + detail if detail else ""))
    (ROOT / "docs/API.md").write_text("\n".join(docs) + "\n", encoding="utf-8")
    print(json.dumps(catalog["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
