"""Protocol-specific signing and verification; no network or framework dependency.

Specifications: /mini-app/develop/server/signature-algorithm and
/mini-app/open-capacity/business-monetization/guaranteed-payment/TE.
"""
import base64
import hashlib
import hmac
import json
import time
import uuid

from .base import ByteDanceError, Map


def as_bytes(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise ByteDanceError("Expected original bytes or UTF-8 string")


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _crypto():
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
    except ImportError as exc:
        raise ByteDanceError("Signing/decryption requires pip install bytedance[crypto]") from exc
    return hashes, serialization, padding, default_backend()


def _key(value, private):
    _, serialization, _, backend = _crypto()
    raw = as_bytes(value)
    try:
        if b"-----BEGIN" in raw:
            key = (serialization.load_pem_private_key(raw, password=None, backend=backend)
                   if private else serialization.load_pem_public_key(raw, backend=backend))
        else:
            decoded = base64.b64decode(raw, validate=True)
            key = (serialization.load_der_private_key(decoded, password=None, backend=backend)
                   if private else serialization.load_der_public_key(decoded, backend=backend))
        from cryptography.hazmat.primitives.asymmetric import rsa
        if not isinstance(key, rsa.RSAPrivateKey if private else rsa.RSAPublicKey) or key.key_size != 2048:
            raise ValueError("SHA256-RSA2048 requires a 2048-bit RSA key")
        return key
    except (ValueError, TypeError) as exc:
        raise ByteDanceError("Invalid RSA key: {}".format(exc)) from exc


def rsa_sign(message, private_key):
    hashes, _, padding, _ = _crypto()
    result = _key(private_key, True).sign(as_bytes(message), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(result).decode("ascii")


def rsa_verify(message, signature, public_key):
    hashes, _, padding, _ = _crypto()
    from cryptography.exceptions import InvalidSignature
    try:
        decoded = base64.b64decode(as_bytes(signature), validate=True)
        _key(public_key, False).verify(decoded, as_bytes(message), padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ByteDanceError("Invalid platform signature") from exc
    return True


def request_message(method, uri, timestamp, nonce, body=b""):
    if not uri.startswith("/"):
        raise ByteDanceError("Signing URI must begin with / and exclude the domain")
    return ("{}\n{}\n{}\n{}\n".format(method.upper(), uri, timestamp, nonce).encode("utf-8")
            + as_bytes(body) + b"\n")


def authorization(app_id, private_key, key_version, method, uri, body=b"",
                  timestamp=None, nonce=None, quoted=True):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    nonce = uuid.uuid4().hex if nonce is None else str(nonce)
    signature = rsa_sign(request_message(method, uri, timestamp, nonce, body), private_key)
    fields = (("appid", app_id), ("nonce_str", nonce), ("timestamp", timestamp),
              ("key_version", key_version), ("signature", signature))
    if any(any(char in str(value) for char in ('"', '\r', '\n', ',')) for _, value in fields):
        raise ByteDanceError("Invalid authorization field")
    pattern = '{}="{}"' if quoted else '{}={}'
    return "SHA256-RSA2048 " + ",".join(pattern.format(k, v) for k, v in fields)


def signed_order(data, app_id, private_key, key_version="1", timestamp=None, nonce=None):
    """Build tt.requestOrder arguments (its authorization has unquoted fields)."""
    body = json_bytes(data) if isinstance(data, dict) else as_bytes(data)
    json.loads(body.decode("utf-8"))
    return {"data": body.decode("utf-8"), "byteAuthorization": authorization(
        app_id, private_key, key_version, "POST", "/requestOrder", body,
        timestamp=timestamp, nonce=nonce, quoted=False)}


def verify_platform(body, headers, public_key):
    """Verify a signed response or trade callback using the original body."""
    headers = {k.lower(): v for k, v in headers.items()}
    try:
        message = ("{}\n{}\n".format(headers["byte-timestamp"], headers["byte-nonce-str"])
                   .encode("utf-8") + as_bytes(body) + b"\n")
        signature = headers["byte-signature"]
    except KeyError as exc:
        raise ByteDanceError("Missing platform signature header: {}".format(exc)) from exc
    return rsa_verify(message, signature, public_key)


def session_signature(session_key, body):
    return hmac.new(as_bytes(session_key), json_bytes(body), hashlib.sha256).hexdigest()


def ecpay_signature(parameters, salt):
    """MD5(sorted(values + SALT)); excludes identity and empty values.

    Objects/lists use exactly the same compact JSON serialization as transport.
    other_settle_params is explicitly excluded by the official signing demo.
    """
    values = []
    for name, value in parameters.items():
        if name in ("sign", "app_id", "thirdparty_id", "prod_id", "other_settle_params") or value is None:
            continue
        if isinstance(value, (dict, list, bool)):
            value = json_bytes(value).decode("utf-8")
        else:
            value = str(value).strip()
        if value and value != "null":
            values.append(value)
    values.append(str(salt))
    return hashlib.md5("&".join(sorted(values)).encode("utf-8")).hexdigest()


def verify_ecpay(payload, token):
    signature = payload.get("msg_signature") or payload.get("signature")
    values = [str(token)]
    for name, value in payload.items():
        if name in ("msg_signature", "signature", "type") or value is None or value == "":
            continue
        if not isinstance(value, (str, int, float)):
            raise ByteDanceError("Invalid payment callback field: " + name)
        values.append(str(value))
    expected = hashlib.sha1("".join(sorted(values)).encode("utf-8")).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
        raise ByteDanceError("Invalid payment callback signature")
    return True


def verify_webhook(body, headers, client_secret):
    headers = {k.lower(): v for k, v in headers.items()}
    expected = hashlib.sha1(as_bytes(client_secret) + as_bytes(body)).hexdigest()
    signature = headers.get("x-douyin-signature", "")
    if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
        raise ByteDanceError("Invalid webhook signature")
    return True


def decrypt_user_data(encrypted_data, session_key, iv, app_id=None):
    """AES-128-CBC + strict PKCS7; optionally check the embedded watermark."""
    _crypto()
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    from cryptography.hazmat.backends import default_backend
    try:
        key = base64.b64decode(as_bytes(session_key), validate=True)
        vector = base64.b64decode(as_bytes(iv), validate=True)
        ciphertext = base64.b64decode(as_bytes(encrypted_data), validate=True)
        if len(key) != 16 or len(vector) != 16:
            raise ValueError("AES-128 key and IV must each be 16 bytes")
        decryptor = Cipher(algorithms.AES(key), modes.CBC(vector), backend=default_backend()).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = PKCS7(128).unpadder()
        value = json.loads((unpadder.update(padded) + unpadder.finalize()).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Decrypted data must be an object")
        if app_id is not None and value.get("watermark", {}).get("appid") != app_id:
            raise ValueError("Watermark appid does not match")
        return Map(value)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ByteDanceError("Unable to decrypt user data") from exc


class CallbackTools(object):
    """Verify before parsing business payloads; retain envelope and raw msg."""
    def __init__(self, client):
        self.client = client

    def parse(self, body, headers=None, protocol="trade"):
        raw = as_bytes(body)
        headers = {} if headers is None else headers
        if protocol == "trade":
            if not self.client.platform_public_key:
                raise ByteDanceError("platform_public_key is required")
            verify_platform(raw, headers, self.client.platform_public_key)
        elif protocol == "webhook":
            verify_webhook(raw, headers, self.client.app_secret)
        elif protocol != "ecpay":
            raise ByteDanceError("Unknown callback protocol: " + protocol)
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Callback must be a JSON object")
            if protocol == "ecpay":
                if not self.client.callback_token:
                    raise ByteDanceError("callback_token is required")
                verify_ecpay(payload, self.client.callback_token)
            result = Map(payload)
            if isinstance(payload.get("msg"), str):
                result["parsed_msg"] = json.loads(payload["msg"])
            if isinstance(payload.get("content"), str):
                result["parsed_content"] = json.loads(payload["content"])
            return result
        except (ValueError, UnicodeError) as exc:
            raise ByteDanceError("Invalid callback JSON") from exc

    @staticmethod
    def acknowledgement(protocol="trade", data=None):
        if protocol == "ecpay":
            return {"err_no": 0, "err_tips": "success"}
        if protocol == "trade":
            result = {"err_no": 0, "err_tips": "success"}
            if data is not None:
                result["data"] = data
            return result
        if protocol == "webhook":
            if data is not None and data.get("event") == "verify_webhook":
                return {"challenge": data["content"]["challenge"]}
            return {}
        raise ByteDanceError("Unknown callback protocol: " + protocol)
