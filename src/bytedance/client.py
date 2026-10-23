# -*- coding: utf-8 -*-
"""HTTP transport, credential routing and the public compatibility client."""
import copy
import json
import os
import re
from urllib.parse import quote, urlsplit

import requests
from requests.structures import CaseInsensitiveDict

from .base import ByteDanceError, Map
from .legacy import LegacyMethods
from .security import (CallbackTools, authorization, ecpay_signature, json_bytes,
                       signed_order, verify_platform)
from .tokens import TokenCache, token_string


class ByteDance(LegacyMethods):
    def __init__(self, **config):
        self.app_id = config["app_id"]
        self.app_secret = config["app_secret"]
        self.session = config.get("session") or requests.Session()
        self.timeout = config.get("timeout", 20)
        self.environment = config.get("environment", "production")
        if self.environment not in ("production", "sandbox"):
            raise ByteDanceError("environment must be production or sandbox")
        self.api_domains = dict(config.get("api_domains") or {})
        self.private_key = config.get("private_key")
        self.platform_public_key = config.get("platform_public_key")
        self.key_version = str(config.get("key_version", "1"))
        self.payment_salt = config.get("payment_salt") or config.get("mch_secret")
        self.callback_token = config.get("callback_token")
        for name in ("mch_id", "mch_secret", "mch_app_id"):
            if name in config:
                setattr(self, name, config[name])
        self.access_token_type = config.get("access_token_type") or "auto"
        if self.access_token_type not in ("auto", "redis", "file"):
            raise ByteDanceError("access_token_type只能是auto/redis/file三选一")
        self.redis_conf = dict(config.get("redis") or {
            "host": "redis", "port": 6379, "decode_responses": True})
        self.ac_path = os.fspath(config.get("ac_path") or os.path.join(
            os.path.expanduser("~"), "{}.access_token".format(self.app_id)))
        domain = "https://developer.toutiao.com"
        if self.environment == "sandbox":
            domain = "https://open-sandbox.douyin.com"
        self.api_uri = domain + "/api"
        self._tokens = TokenCache(self, config)
        self.callbacks = CallbackTools(self)
        from .generated import attach
        attach(self)
        from . import __version__
        self.__version__ = __version__

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def access_token(self):
        return self._tokens.get("mini_app")

    @property
    def client_token(self):
        return self._tokens.get("client")

    def _application_credential(self, kind):
        if kind == "mini_app":
            return self.access_token
        if kind == "client":
            return self.client_token
        raise ByteDanceError("This interface requires an explicit {} token".format(kind))

    def _fetch_application_token(self, kind):
        if kind == "mini_app":
            return self._get_access_token()
        if kind == "client":
            domain = ("https://open-sandbox.douyin.com" if self.environment == "sandbox"
                      else "https://open.douyin.com")
            response = self._request("POST", self.api_domains.get(domain, domain) + "/oauth/client_token/",
                                     body={"client_key": self.app_id, "client_secret": self.app_secret,
                                           "grant_type": "client_credential"})
            return response.get("data", response)
        raise ByteDanceError("Unsupported cached credential: " + kind)

    def _get_access_token(self):
        domain = self.api_uri.rsplit("/api", 1)[0]
        response = self._request("POST", self.api_domains.get(domain, domain) + "/api/apps/v2/token", body={
            "appid": self.app_id, "secret": self.app_secret, "grant_type": "client_credential"})
        return response.get("data", response)

    def code2_session(self, code=None, anonymous_code=None, refresh=None):
        """V2 login with the historical flat session result."""
        if not code and not anonymous_code:
            raise ByteDanceError("code or anonymous_code is required")
        body = {"appid": self.app_id, "secret": self.app_secret}
        for name, value in (("code", code), ("anonymous_code", anonymous_code), ("refresh", refresh)):
            if value is not None:
                body[name] = value
        response = self._request("POST", self.api_uri + "/apps/v2/jscode2session", body=body)
        return response.get("data", response)

    def code2Session(self, code=None, anonymous_code=None):
        return self.code2_session(code=code, anonymous_code=anonymous_code)

    def _subscription_notify(self, body):
        domain = "https://open.douyin.com"
        if self.environment == "sandbox":
            raise ByteDanceError("Subscription notifications do not document sandbox support")
        return self._request("POST", self.api_domains.get(domain, domain)
                             + "/api/notification/v2/subscription/notify_user/", body=body,
                             headers={"access-token": self.client_token})

    def signed_order(self, data, timestamp=None, nonce=None):
        if not self.private_key:
            raise ByteDanceError("private_key is required to sign order parameters")
        return signed_order(data, self.app_id, self.private_key, self.key_version, timestamp, nonce)

    def fetch(self, method, url, params=None, data=None, headers=None):
        """Existing low-level entry point; non-JSON responses stay raw."""
        return self._request(method, url, query=params, raw=data, headers=headers, binary=True)

    def get(self, path, params=None, token=True, prefix="/apps"):
        params = dict(params or {})
        if token and "access_token" not in params:
            params["access_token"] = self.access_token
        return self.fetch("GET", self.api_uri + prefix + path, params=params)

    def post(self, path, data, params=None, headers=None, prefix="/apps", token=True):
        params, headers = dict(params or {}), CaseInsensitiveDict(headers or {})
        if token and "access_token" not in params:
            params["access_token"] = self.access_token
        headers["Content-Type"] = "application/json"
        return self.fetch("POST", self.api_uri + prefix + path, params=params,
                          data=json_bytes(data), headers=headers)

    def call(self, name, body=None, query=None, headers=None, files=None, path_params=None, token=None):
        """Dispatch a checked-in contract. Prefer its generated named method."""
        from .generated import CONTRACTS
        try:
            spec = CONTRACTS[name]
        except KeyError as exc:
            raise ByteDanceError("Unknown API: " + name) from exc
        body = copy.deepcopy(body) if body is not None else {}
        query = copy.deepcopy(query) if query is not None else {}
        headers = CaseInsensitiveDict(headers or {})
        if not isinstance(body, dict) or not isinstance(query, dict):
            raise ByteDanceError("body and query must be dictionaries")
        buckets = {"body": body, "query": query, "header": headers}
        for location, fields in spec.get("defaults", {}).items():
            for field, source in fields.items():
                buckets[location].setdefault(field, {"app_id": self.app_id,
                    "app_secret": self.app_secret, "client_credential": "client_credential"}[source])
        auth = spec.get("auth")
        if auth:
            bucket = buckets[auth["in"]]
            field = auth["name"]
            if token is not None:
                bucket[field] = token_string(token)
            elif not bucket.get(field):
                bucket[field] = self._application_credential(auth["kind"])
        elif token is not None:
            raise ByteDanceError("This API has no token parameter")
        domain = spec["domain"]
        if self.environment == "sandbox":
            if not spec.get("sandbox"):
                raise ByteDanceError("Sandbox support is not documented for " + name)
            domain = "https://open-sandbox.douyin.com"
        domain = self.api_domains.get(domain, domain)
        path = spec["path"]
        for key, value in (path_params or {}).items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
            path = re.sub(r":" + re.escape(key) + r"(?=/|$)", quote(str(value), safe=""), path)
        if "{" in path or re.search(r"/:[a-zA-Z_]", path):
            raise ByteDanceError("Missing path parameters for " + name)
        for key, value in list(query.items()):
            if isinstance(value, (dict, list, bool)):
                query[key] = json_bytes(value).decode("utf-8")
        signing = spec.get("signing")
        if spec.get("encoding", "json") == "json":
            headers.setdefault("Content-Type", "application/json")
        if signing == "ecpay":
            target = query if spec["method"] == "GET" else body
            if "sign" not in target:
                if not self.payment_salt:
                    raise ByteDanceError("payment_salt is required for " + name)
                target["sign"] = ecpay_signature(target, self.payment_salt)
        return self._request(spec["method"], domain.rstrip("/") + path, body=body,
                             query=query, headers=headers, files=files,
                             encoding=spec.get("encoding", "json"),
                             rsa=signing == "rsa", binary=spec.get("binary", False),
                             error_paths=spec.get("error_paths"))

    def _request(self, method, url, body=None, query=None, headers=None, files=None,
                 encoding="json", raw=None, rsa=False, binary=False, error_paths=None):
        headers = CaseInsensitiveDict(headers or {})
        data = raw
        if encoding == "multipart" and not files:
            raise ByteDanceError("This API requires multipart files; pass files={field: (filename, bytes, content_type)}")
        if raw is None and (body or method.upper() not in ("GET", "HEAD")):
            if encoding == "json" and files is None:
                data = json_bytes({} if body is None else body)
                headers.setdefault("Content-Type", "application/json")
            else:
                data = {} if body is None else body
                if files is not None or encoding == "multipart":
                    # requests must generate the boundary matching its payload.
                    headers.pop("Content-Type", None)
                else:
                    headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        request = requests.Request(method, url, params=query, data=data, headers=headers, files=files)
        try:
            prepared = self.session.prepare_request(request)
            if rsa and "Byte-Authorization" not in prepared.headers:
                if not self.private_key:
                    raise ByteDanceError("private_key is required for this signed API")
                prepared.headers["Byte-Authorization"] = authorization(
                    self.app_id, self.private_key, self.key_version, prepared.method,
                    prepared.path_url, prepared.body or b"")
            response = self.session.send(prepared, timeout=self.timeout, allow_redirects=False)
        except requests.RequestException as exc:
            # Do not include URLs/query strings (which can contain secrets).
            raise ByteDanceError("HTTP transport failed: " + type(exc).__name__) from exc
        if self.platform_public_key and (rsa or response.headers.get("Byte-Signature")) and 200 <= response.status_code < 300:
            verify_platform(response.content, response.headers, self.platform_public_key)
        try:
            payload = response.json()
        except ValueError:
            if response.status_code >= 300:
                raise ByteDanceError("HTTP {}".format(response.status_code),
                                    response=response, status_code=response.status_code)
            if binary:
                return response
            raise ByteDanceError("Expected a JSON response", response=response,
                                status_code=response.status_code)
        if response.status_code >= 300:
            raise self._error(payload, response, "HTTP {}".format(response.status_code))
        paths = error_paths if error_paths is not None else [
            "err_no", "error_no", "error", "errcode", "error_code", "code",
            "data.error_code", "extra.error_code", "extra.sub_error_code"]
        if isinstance(payload, dict):
            for path in paths:
                current = payload
                for part in path.split("."):
                    current = current.get(part) if isinstance(current, dict) else None
                if current is not None and not isinstance(current, (dict, list)) and current not in (0, "0", ""):
                    raise self._error(payload, response, "API request failed", current, path)
            return Map(payload)
        return Map._convert(payload)

    @staticmethod
    def _error(payload, response, default, code=None, error_path=None):
        message, log_id = default, None
        if isinstance(payload, dict):
            preferred = payload
            if error_path and "." in error_path:
                for part in error_path.split(".")[:-1]:
                    preferred = preferred.get(part) if isinstance(preferred, dict) else None
            found_message = False
            for obj in (preferred, payload, payload.get("extra"), payload.get("data")):
                if not isinstance(obj, dict):
                    continue
                if not found_message:
                    candidate = next((obj[k] for k in ("err_tips", "err_msg", "error_tips", "errmsg",
                        "message", "description", "msg") if obj.get(k)), None)
                    if candidate is not None:
                        message, found_message = candidate, True
                if log_id is None:
                    log_id = next((obj[k] for k in ("log_id", "logid", "request_id") if obj.get(k)), None)
        return ByteDanceError(str(message), code=code, log_id=log_id, response=response,
                             status_code=response.status_code, payload=payload)
