# -*- coding: utf-8 -*-
"""Offline protocol/compatibility tests. No platform credentials are used."""
import ast
import concurrent.futures
import copy
import hashlib
import io
import json
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import requests

from bytedance import ByteDance, ByteDanceError, Map
from bytedance.generated import CONTRACTS
from bytedance import security, tokens

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = json.loads((ROOT / 'tests/fixtures/official_rsa.json').read_text(encoding='utf-8'))


class RecordingSession(requests.Session):
    def __init__(self, payload=None, status=200, content=None, headers=None):
        super(RecordingSession, self).__init__()
        self.payload = {'err_no': 0} if payload is None else payload
        self.status = status
        self.content = content
        self.response_headers = headers or {}
        self.sent = []
        self.options = []

    def send(self, request, **kwargs):
        self.sent.append(request)
        self.options.append(kwargs)
        response = requests.Response()
        response.status_code = self.status
        response._content = (json.dumps(self.payload).encode('utf-8')
                             if self.content is None else self.content)
        response.headers.update(self.response_headers)
        response.request = request
        return response


def client(session=None, **kwargs):
    config = dict(app_id='tt-test', app_secret='secret', access_token_type='file',
                  session=session or RecordingSession(),
                  token_provider=lambda kind: {'mini_app': 'mini-token', 'client': 'clt.token'}[kind])
    config.update(kwargs)
    return ByteDance(**config)


class TransportTests(unittest.TestCase):
    def test_login_uses_official_v2_contract_and_keeps_flat_result(self):
        session = RecordingSession({'err_no': 0, 'data': {'openid': 'open', 'session_key': 'key'}})
        app = client(session)
        self.assertEqual(app.code2Session(code='code').openid, 'open')
        request = session.sent[-1]
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.url, 'https://developer.toutiao.com/api/apps/v2/jscode2session')
        self.assertEqual(json.loads(request.body), {'appid': 'tt-test', 'secret': 'secret', 'code': 'code'})
        app.code2_session(anonymous_code='anon', refresh=False)
        self.assertIs(json.loads(session.sent[-1].body)['refresh'], False)
        with self.assertRaises(ByteDanceError):
            app.code2Session()

    def test_module_login_keeps_envelope_and_defaults(self):
        session = RecordingSession({'err_no': 0, 'data': {'openid': 'open'}})
        app = client(session)
        body = {'code': 'code', 'refresh': False}
        result = app.basic.log_in.code_2_session(body=body)
        self.assertEqual(result.data.openid, 'open')
        self.assertEqual(body, {'code': 'code', 'refresh': False})
        self.assertEqual(json.loads(session.sent[-1].body)['appid'], 'tt-test')

    def test_subscription_legacy_adapts_to_current_protocol(self):
        session = RecordingSession()
        app = client(session)
        app.subscribe_send('tpl', 'open', {'姓名': '张三'}, page='pages/index')
        request = session.sent[-1]
        self.assertEqual(request.url, 'https://open.douyin.com/api/notification/v2/subscription/notify_user/')
        self.assertEqual(request.headers['access-token'], 'clt.token')
        self.assertEqual(json.loads(request.body), {'msg_id': 'tpl', 'open_id': 'open',
            'data': {'姓名': '张三'}, 'page': 'pages/index'})
        self.assertNotIn('access_token', parse_qs(urlsplit(request.url).query))

    def test_qrcode_preserves_false_zero_and_raw_response(self):
        session = RecordingSession(content=b'\x89PNG\r\n', headers={'Content-Type': 'image/png'})
        result = client(session).create_qrcode(set_icon=False, width=0, path='')
        self.assertIsInstance(result, requests.Response)
        body = json.loads(session.sent[-1].body)
        self.assertIs(body['set_icon'], False)
        self.assertEqual(body['width'], 0)
        self.assertEqual(body['path'], '')

    def test_storage_hmac_matches_transmitted_body(self):
        session = RecordingSession()
        app = client(session)
        app.set_user_storage('open', 'session', {'昵称': '张三', '积分': 0})
        request = session.sent[-1]
        import hmac
        expected = hmac.new(b'session', request.body, hashlib.sha256).hexdigest()
        self.assertEqual(parse_qs(urlsplit(request.url).query)['signature'], [expected])
        app.remove_user_storage('open', 'session', [])
        self.assertEqual(json.loads(session.sent[-1].body), {'key': []})

    def test_text_request_wraps_tasks(self):
        session = RecordingSession()
        client(session).text_antidirt([{'content': '文本'}])
        self.assertEqual(json.loads(session.sent[-1].body), {'tasks': [{'content': '文本'}]})

    def test_user_credential_is_explicit_and_case_insensitive(self):
        app = client()
        name = next(n for n, s in CONTRACTS.items() if (s.get('auth') or {}).get('kind') == 'user')
        with self.assertRaisesRegex(ByteDanceError, 'explicit user'):
            app.call(name)
        app.call(name, headers={'Access-Token': 'user.token'})
        self.assertEqual(app.session.sent[-1].headers['access-token'], 'user.token')
        app.call(name, headers={'Access-Token': 'old'}, token='new')
        self.assertEqual(app.session.sent[-1].headers['access-token'], 'new')

    def test_multipart_uses_boundary_and_original_bytes(self):
        session = RecordingSession()
        app = client(session)
        app.other.upload_material(body={'material_type': 1}, files={'material_file': ('x.png', b'png-bytes', 'image/png')})
        request = session.sent[-1]
        self.assertIn('multipart/form-data; boundary=', request.headers['Content-Type'])
        self.assertIn(b'png-bytes', request.body)
        self.assertIn(b'name="material_type"', request.body)
        self.assertEqual(request.headers['access-token'], 'clt.token')

    def test_form_encoding_from_official_oauth_contract(self):
        session = RecordingSession()
        app = client(session)
        name = next(n for n, spec in CONTRACTS.items() if spec['encoding'] == 'form')
        app.call(name, body={'code': 'a+b 中文'})
        self.assertEqual(session.sent[-1].headers['Content-Type'], 'application/x-www-form-urlencoded')
        self.assertEqual(parse_qs(session.sent[-1].body)['code'], ['a+b 中文'])

    def test_query_lists_and_booleans_are_json_encoded(self):
        app = client()
        app.call('basic.aweme_bind.get_aweme_relation_bind_qrcode',
                 query={'capacity_list': ['live_self_mount'], 'co_subject': False}, token='isv.token')
        query = parse_qs(urlsplit(app.session.sent[-1].url).query)
        self.assertEqual(query['capacity_list'], ['["live_self_mount"]'])
        self.assertEqual(query['co_subject'], ['false'])

    def test_session_headers_cookies_timeout_and_no_redirects(self):
        session = RecordingSession()
        session.headers['X-Integration'] = 'test'
        session.cookies.set('example', 'cookie')
        client(session, timeout=(2, 7)).code2Session(code='code')
        self.assertEqual(session.sent[-1].headers['X-Integration'], 'test')
        self.assertIn('example=cookie', session.sent[-1].headers['Cookie'])
        self.assertEqual(session.options[-1]['timeout'], (2, 7))
        self.assertIs(session.options[-1]['allow_redirects'], False)

    def test_error_formats_include_trace_and_original_response(self):
        payloads = [({'err_no': 40018, 'err_tips': 'bad code', 'log_id': 'trace'}, 40018),
                    ({'data': {'error_code': 10003, 'description': 'bad key'}, 'extra': {'logid': 'trace'}}, 10003),
                    ({'code': 401, 'message': 'bad token'}, 401),
                    ({'err_no': 200, 'err_tips': 'nonzero business error'}, 200),
                    ({'error_no': 2008, 'error_tips': 'bad sign'}, 2008)]
        for payload, code in payloads:
            with self.subTest(code=code):
                app = client(RecordingSession(payload))
                with self.assertRaises(ByteDanceError) as caught:
                    app.fetch('GET', 'https://example.test')
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.payload, payload)
                self.assertIsInstance(caught.exception.response, requests.Response)

    def test_nested_error_message_is_not_overwritten_by_success(self):
        session = RecordingSession({'message': 'success', 'data': {'error_code': 10003,
                                   'description': 'invalid key'}, 'extra': {'description': 'success'}})
        with self.assertRaisesRegex(ByteDanceError, 'invalid key'):
            client(session).fetch('GET', 'https://example.test')

    def test_http_errors_and_html_are_not_successful_api_calls(self):
        for status in (302, 400, 500):
            with self.subTest(status=status), self.assertRaises(ByteDanceError):
                client(RecordingSession(status=status, content=b'html')).code2Session(code='code')
        with self.assertRaisesRegex(ByteDanceError, 'Expected a JSON'):
            client(RecordingSession(content=b'<html>proxy</html>')).code2Session(code='code')

    def test_network_failure_does_not_leak_query_credentials(self):
        session = RecordingSession()
        session.send = mock.Mock(side_effect=requests.Timeout('https://x?secret=private'))
        with self.assertRaises(ByteDanceError) as caught:
            client(session).code2Session(code='code')
        self.assertNotIn('private', str(caught.exception))
        self.assertEqual(session.send.call_count, 1)

    def test_sandbox_routes_supported_apis_and_rejects_unsupported(self):
        app = client(environment='sandbox')
        app.basic.log_in.code_2_session(body={'code': 'code'})
        self.assertEqual(urlsplit(app.session.sent[-1].url).netloc, 'open-sandbox.douyin.com')
        with self.assertRaisesRegex(ByteDanceError, 'Sandbox support'):
            app.other.upload_material(body={'material_type': 1})

    def test_no_input_dictionaries_are_mutated(self):
        app = client()
        body, query, headers = {'data': {'name': '张三'}}, {'zero': 0}, {'X-Extra': 'test'}
        saved = copy.deepcopy((body, query, headers))
        app.call('marketing.subscribe_notification.notify_user_v2', body=body, query=query, headers=headers)
        self.assertEqual((body, query, headers), saved)


class MapTests(unittest.TestCase):
    def test_nested_arrays_and_missing_compatibility(self):
        result = Map({'data': [{'openid': 'open'}]})
        self.assertEqual(result.data[0].openid, 'open')
        self.assertEqual(result.missing, {})
        self.assertIn('missing', result)
        result.update(other=[{'id': 1}])
        self.assertEqual(result.other[0].id, 1)
        self.assertEqual(result.setdefault('third', {'id': 2}).id, 2)
        del result.third
        self.assertNotIn('third', result)

    def test_error_inspection_does_not_add_fields(self):
        payload = {'data': {'openid': 'open'}}
        result = client(RecordingSession(payload)).fetch('GET', 'https://example.test')
        self.assertEqual(result, payload)


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temporary.name, 'token')

    def tearDown(self):
        self.temporary.cleanup()

    def app(self, **kwargs):
        options = dict(ac_path=self.path, token_provider=None)
        options.update(kwargs)
        app = client(**options)
        app._get_access_token = mock.Mock(return_value=Map(access_token='cached', expires_in=7200))
        return app

    def test_no_redis_module_file_mode_works(self):
        with mock.patch.object(tokens, 'redis', None):
            app = self.app()
            self.assertEqual(app.access_token, 'cached')
            self.assertEqual(app.access_token, 'cached')
            self.assertEqual(app._get_access_token.call_count, 1)

    def test_v2_token_protocol(self):
        app = client(RecordingSession({'err_no': 0, 'data': {'access_token': 'mini', 'expires_in': 7200}}),
                     ac_path=self.path, token_provider=None)
        self.assertEqual(app.access_token, 'mini')
        self.assertEqual(app.session.sent[-1].url, 'https://developer.toutiao.com/api/apps/v2/token')
        self.assertEqual(json.loads(app.session.sent[-1].body)['grant_type'], 'client_credential')

    def test_expired_and_corrupt_cache_refreshes(self):
        for value in ('invalid', '{"token":"old","expires_at":1}', '[]'):
            app = self.app()
            Path(app._tokens._path('mini_app')).write_text(value)
            self.assertEqual(app.access_token, 'cached')
            self.assertEqual(app._get_access_token.call_count, 1)

    def test_legacy_unexpired_file_is_read(self):
        Path(self.path).write_text('legacy')
        os.utime(self.path, (time.time(), time.time() + 60))
        app = self.app()
        self.assertEqual(app.access_token, 'legacy')
        self.assertEqual(app._get_access_token.call_count, 0)

    def test_multiple_instances_refresh_once(self):
        calls = []
        lock = threading.Lock()
        def refresh():
            with lock:
                calls.append(1)
            time.sleep(0.01)
            return Map(access_token='shared', expires_in=7200)
        apps = [self.app() for _ in range(8)]
        for app in apps:
            app._get_access_token = refresh
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            values = list(executor.map(lambda a: a.access_token, apps))
        self.assertEqual(values, ['shared'] * 8)
        self.assertEqual(len(calls), 1)

    def test_types_environments_and_apps_are_isolated(self):
        app = self.app()
        app._fetch_application_token = mock.Mock(side_effect=lambda k: Map(access_token=k, expires_in=50))
        self.assertEqual(app.access_token, 'mini_app')
        self.assertEqual(app.client_token, 'client')
        sandbox = self.app(environment='sandbox')
        self.assertEqual(sandbox.access_token, 'cached')
        self.assertNotEqual(app._tokens._path('mini_app'), sandbox._tokens._path('mini_app'))
        other = self.app(app_id='tt-other')
        self.assertNotEqual(app._tokens.namespace, other._tokens.namespace)
        self.assertNotEqual(app._tokens._path('mini_app'), other._tokens._path('mini_app'))
        self.assertEqual(other.access_token, 'cached')
        self.assertEqual(app.access_token, 'mini_app')

    def test_short_ttl_stays_usable_and_tokens_are_strings(self):
        app = self.app()
        app._get_access_token.return_value = Map(access_token=b'token', expires_in=5)
        self.assertEqual(app.access_token, 'token')
        record = json.loads(Path(app._tokens._path('mini_app')).read_text())
        self.assertGreater(record['expires_at'], time.time())
        self.assertLess(record['expires_at'], time.time() + 5)

    def test_explicit_redis_without_dependency_fails(self):
        with mock.patch.object(tokens, 'redis', None), self.assertRaisesRegex(ByteDanceError, 'requires'):
            self.app(access_token_type='redis')

    def test_redis_failure_auto_falls_back_explicit_mode_errors(self):
        class RedisFailure(Exception):
            pass
        module = mock.Mock()
        module.exceptions.RedisError = RedisFailure
        module.Redis.return_value.get.side_effect = RedisFailure('offline')
        with mock.patch.object(tokens, 'redis', module):
            self.assertEqual(self.app(access_token_type='auto').access_token, 'cached')
            with self.assertRaisesRegex(ByteDanceError, 'Redis credential cache'):
                self.app(access_token_type='redis').access_token

    def test_redis_bytes_are_decoded(self):
        module = mock.Mock()
        module.Redis.return_value.get.return_value = b'from-redis'
        with mock.patch.object(tokens, 'redis', module):
            self.assertEqual(self.app(access_token_type='redis').access_token, 'from-redis')

    def test_redis_refresh_rechecks_under_lock_and_sets_ttl(self):
        module = mock.Mock()
        module.exceptions.RedisError = RuntimeError
        connection = module.Redis.return_value
        connection.get.side_effect = [None, None, b'cached']
        connection.lock.return_value = mock.MagicMock()
        with mock.patch.object(tokens, 'redis', module):
            app = self.app(access_token_type='redis')
            self.assertEqual(app.access_token, 'cached')
            self.assertEqual(app.access_token, 'cached')
            self.assertEqual(app._get_access_token.call_count, 1)
            connection.set.assert_called_once_with(app._tokens.namespace + ':mini_app', 'cached', ex=6600)

    def test_invalid_token_response_is_not_cached(self):
        for data in ({'access_token': '', 'expires_in': 7200},
                     {'access_token': 'token', 'expires_in': 0},
                     {'access_token': 'token'}):
            app = self.app()
            app._get_access_token.return_value = Map(data)
            with self.assertRaises(ByteDanceError):
                app.access_token
            self.assertFalse(Path(app._tokens._path('mini_app')).exists())


class SecurityTests(unittest.TestCase):
    def test_official_known_answer_rsa_vector(self):
        self.assertEqual(security.rsa_sign(OFFICIAL['message'], OFFICIAL['private_key']), OFFICIAL['signature'])
        self.assertTrue(security.rsa_verify(OFFICIAL['message'], OFFICIAL['signature'], OFFICIAL['public_key']))
        with self.assertRaises(ByteDanceError):
            security.rsa_verify(OFFICIAL['message'] + ' ', OFFICIAL['signature'], OFFICIAL['public_key'])

    def test_request_signs_exact_prepared_query_and_unicode_body(self):
        app = client(private_key=OFFICIAL['private_key'])
        name = next(n for n, s in CONTRACTS.items() if s.get('signing') == 'rsa')
        app.call(name, body={'name': '张三', 'number': 0}, query={'a': '空 格'})
        request = app.session.sent[-1]
        fields = dict(re.findall(r'(\w+)="([^"]*)"', request.headers['Byte-Authorization']))
        message = security.request_message(request.method, request.path_url, fields['timestamp'], fields['nonce_str'], request.body)
        self.assertTrue(security.rsa_verify(message, fields['signature'], OFFICIAL['public_key']))

    def test_frontend_request_order_format(self):
        result = security.signed_order({'skuList': [], 'outOrderNo': 'o1'}, 'tt-test', OFFICIAL['private_key'],
                                       timestamp=1680835692, nonce='nonce')
        self.assertIn('appid=tt-test,', result['byteAuthorization'])
        fields = dict(re.findall(r'(\w+)=([^,]+)', result['byteAuthorization']))
        message = security.request_message('POST', '/requestOrder', '1680835692', 'nonce', result['data'])
        self.assertTrue(security.rsa_verify(message, fields['signature'], OFFICIAL['public_key']))

    def test_response_verification_preserves_bytes(self):
        raw = b'{ "err_no":0, "data": {} }\n'
        signature = security.rsa_sign(b'123\nnonce\n' + raw + b'\n', OFFICIAL['private_key'])
        headers = {'Byte-Timestamp': '123', 'Byte-Nonce-Str': 'nonce', 'Byte-Signature': signature}
        app = client(RecordingSession(content=raw, headers=headers), platform_public_key=OFFICIAL['public_key'])
        self.assertEqual(app.callbacks.parse(raw, headers), {'err_no': 0, 'data': {}})
        self.assertEqual(app.code2Session(code='code'), {})
        with self.assertRaises(ByteDanceError):
            app.callbacks.parse(raw.strip(), headers)
        with self.assertRaises(ByteDanceError):
            app.callbacks.parse(raw, {})

    def test_ecpay_request_signature_vector_and_transport(self):
        data = {'app_id': 'tt-test', 'out_order_no': 'order', 'total_amount': 100, 'subject': '商品',
                'body': '商品', 'valid_time': 900, 'cp_extra': '', 'thirdparty_id': 'isv'}
        expected = hashlib.md5('&'.join(sorted(['order', '100', '商品', '商品', '900', 'salt'])).encode()).hexdigest()
        self.assertEqual(security.ecpay_signature(data, 'salt'), expected)
        app = client(payment_salt='salt')
        app.payment.ecpay.pay_list.pay(body=data)
        self.assertEqual(json.loads(app.session.sent[-1].body)['sign'], expected)
        app.payment.ecpay.bills.bill(query={'merchant_id': 'merchant', 'bill_date': '20261022', 'bill_type': 'settle'})
        self.assertIn('sign=', app.session.sent[-1].url)

    def test_ecpay_callback_tamper_and_acknowledgement(self):
        payload = {'timestamp': '123', 'nonce': 'n', 'msg': '{"status":"SUCCESS"}', 'type': 'payment'}
        joined = ''.join(sorted(['token', payload['timestamp'], payload['nonce'], payload['msg']]))
        payload['msg_signature'] = hashlib.sha1(joined.encode()).hexdigest()
        app = client(callback_token='token')
        result = app.callbacks.parse(json.dumps(payload), protocol='ecpay')
        self.assertEqual(result.parsed_msg.status, 'SUCCESS')
        self.assertIsInstance(result.msg, str)
        self.assertEqual(app.callbacks.acknowledgement('ecpay'), {'err_no': 0, 'err_tips': 'success'})
        payload['msg'] = '{"status":"FAIL"}'
        with self.assertRaises(ByteDanceError):
            app.callbacks.parse(json.dumps(payload), protocol='ecpay')

    def test_webhook_source_verification_and_challenge(self):
        body = b'{"event":"verify_webhook","content":{"challenge":12345}}'
        signature = hashlib.sha1(b'secret' + body).hexdigest()
        app = client()
        value = app.callbacks.parse(body, {'X-Douyin-Signature': signature}, protocol='webhook')
        self.assertEqual(app.callbacks.acknowledgement('webhook', value), {'challenge': 12345})
        with self.assertRaises(ByteDanceError):
            app.callbacks.parse(body + b' ', {'X-Douyin-Signature': signature}, protocol='webhook')

    def test_aes_decryption_rejects_wrong_watermark_and_padding(self):
        import base64
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        from cryptography.hazmat.backends import default_backend
        key, iv = b'1234567890123456', b'abcdefghijklmnop'
        pad = PKCS7(128).padder()
        data = pad.update(b'{"watermark":{"appid":"tt-test"},"phoneNumber":"123"}') + pad.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).encryptor()
        encrypted = base64.b64encode(encryptor.update(data) + encryptor.finalize())
        value = security.decrypt_user_data(encrypted, base64.b64encode(key), base64.b64encode(iv), 'tt-test')
        self.assertEqual(value.phoneNumber, '123')
        with self.assertRaises(ByteDanceError):
            security.decrypt_user_data(encrypted, base64.b64encode(key), base64.b64encode(iv), 'other')
        with self.assertRaises(ByteDanceError):
            security.decrypt_user_data(b'bad', base64.b64encode(key), base64.b64encode(iv))


class CoverageTests(unittest.TestCase):
    def test_independent_official_go_contracts(self):
        fixture = json.loads((ROOT / 'tests/fixtures/official_go_endpoints.json').read_text(encoding='utf-8'))
        lookup = {(entry['domain'], entry['path']): entry for entry in fixture['endpoints']}
        differences = json.loads((ROOT / 'docs/contract_overrides.json').read_text(encoding='utf-8'))
        matched = 0
        for name, spec in CONTRACTS.items():
            vector = lookup.get((spec['domain'], spec['path']))
            if vector is None:
                continue
            matched += 1
            with self.subTest(api=name, official_operation=vector['operation']):
                key = spec['url'].split('/server/', 1)[1]
                reviewed = differences.get(key, {}).get('official_sdk_method_difference')
                self.assertEqual(spec['method'], reviewed or vector['method'])
        self.assertGreaterEqual(matched, 300)

    def test_every_generated_method_dispatches_its_official_contract(self):
        app = client(private_key=OFFICIAL['private_key'], payment_salt='salt')
        for name, spec in CONTRACTS.items():
            with self.subTest(api=name):
                method = app
                for segment in name.split('.'):
                    method = getattr(method, segment)
                kwargs = {'body': {'test_unicode': '中文', 'false': False, 'zero': 0, 'empty': []}}
                if spec.get('auth'):
                    kwargs['token'] = 'explicit-token'
                if spec['encoding'] == 'multipart':
                    kwargs['files'] = {'file': ('test.png', b'bytes', 'image/png')}
                method(**kwargs)
                request = app.session.sent[-1]
                self.assertEqual(request.method, spec['method'])
                self.assertEqual(urlsplit(request.url).path, spec['path'])
                self.assertEqual(urlsplit(request.url).netloc, urlsplit(spec['domain']).netloc)

    def test_metadata_endpoints_match_source_independently(self):
        catalog = json.loads((ROOT / 'docs/official_catalog.json').read_text(encoding='utf-8'))
        for page in catalog['pages']:
            meta = page.get('openApiMeta') or page.get('unRegulatoryOpenApiMeta')
            if page['kind'] != 'api' or not meta:
                continue
            with self.subTest(page=page['title']):
                spec = CONTRACTS[page['sdk_method']]
                self.assertEqual(spec['path'], meta['path'])
                self.assertEqual(spec['method'], {1: 'GET', 2: 'POST', 5: 'DELETE'}[meta['method_code']])
                if meta['domain']:
                    self.assertEqual(spec['domain'], meta['domain'])

    def test_catalog_accounts_for_every_document_and_excludes_history(self):
        catalog = json.loads((ROOT / 'docs/official_catalog.json').read_text(encoding='utf-8'))
        self.assertGreater(len(catalog['pages']), 500)
        for page in catalog['pages']:
            self.assertIn(page['kind'], ('api', 'callback', 'guide', 'historical', 'unresolved'))
            if page['kind'] == 'api':
                self.assertIn(page['sdk_method'], CONTRACTS)
            elif page['kind'] in ('historical', 'unresolved'):
                self.assertNotIn(page.get('sdk_method'), CONTRACTS)

    def test_python36_syntax(self):
        # Runtime matrix is exercised by CI; local parser catches accidental
        # new-language syntax even when only the host interpreter is installed.
        import sys
        if sys.version_info >= (3, 8):
            for path in (ROOT / 'src/bytedance').glob('*.py'):
                ast.parse(path.read_text(encoding='utf-8'), feature_version=(3, 6))


if __name__ == '__main__':
    unittest.main()
