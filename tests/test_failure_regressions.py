# -*- coding: utf-8 -*-
"""Regression coverage for defects found after the original 1.0.0 test pass.

Keep these normal behavior assertions enabled when changing the SDK.
No platform request or real application credential is used.
"""
import unittest
from unittest import mock

from bytedance import ByteDanceError
from test_sdk import RecordingSession, client


class FailureRegressionTests(unittest.TestCase):
    def test_control_upload_without_session_content_type_works(self):
        session = RecordingSession()
        app = client(session)
        app.other.upload_material(
            body={'material_type': 1},
            files={'material_file': ('example.png', b'image', 'image/png')},
        )
        self.assertTrue(session.sent[-1].headers['Content-Type'].startswith(
            'multipart/form-data; boundary='))

    def test_upload_overrides_session_json_content_type(self):
        # A shared Session commonly supplies JSON defaults for other APIs.
        # File uploads must still declare the boundary of their actual body.
        session = RecordingSession()
        session.headers['Content-Type'] = 'application/json'
        original_headers = dict(session.headers)
        app = client(session)
        app.other.upload_material(
            body={'material_type': 1},
            files={'material_file': ('example.png', b'image', 'image/png')},
        )
        request = session.sent[-1]
        self.assertIn(b'name="material_file"', request.body)
        self.assertTrue(
            request.headers['Content-Type'].startswith('multipart/form-data; boundary='),
            'Multipart body sent with the Session JSON Content-Type: {!r}'.format(
                request.headers['Content-Type']),
        )
        boundary = request.headers['Content-Type'].split('boundary=', 1)[1].encode('ascii')
        self.assertTrue(request.body.startswith(b'--' + boundary + b'\r\n'))
        self.assertTrue(request.body.endswith(b'--' + boundary + b'--\r\n'))
        self.assertEqual(dict(session.headers), original_headers)

    def test_unsupported_sandbox_api_rejects_before_requesting_credentials(self):
        provider = mock.Mock(return_value='test-client-token')
        session = RecordingSession()
        app = client(session, environment='sandbox', token_provider=provider)
        with self.assertRaisesRegex(ByteDanceError, 'Sandbox support is not documented'):
            app.other.upload_material(
                body={'material_type': 1},
                files={'material_file': ('example.png', b'image', 'image/png')},
            )
        self.assertEqual(session.sent, [])
        provider.assert_not_called()

    def test_unsupported_sandbox_does_not_refresh_token_when_cache_is_cold(self):
        app = client(environment='sandbox', token_provider=None)
        app._tokens.get = mock.Mock(side_effect=RuntimeError('credential network unavailable'))
        with self.assertRaisesRegex(ByteDanceError, 'Sandbox support is not documented'):
            app.other.upload_material(files={'material_file': ('example.png', b'image')})
        app._tokens.get.assert_not_called()
        self.assertEqual(app.session.sent, [])

    def test_control_module_login_honors_domain_override(self):
        session = RecordingSession({'err_no': 0, 'data': {'openid': 'test-openid'}})
        app = client(session, api_domains={
            'https://developer.toutiao.com': 'https://proxy.example.test',
        })
        app.basic.log_in.code_2_session(body={'code': 'test-login-code'})
        self.assertEqual(session.sent[-1].url,
                         'https://proxy.example.test/api/apps/v2/jscode2session')

    def test_legacy_login_also_honors_domain_override(self):
        session = RecordingSession({'err_no': 0, 'data': {'openid': 'test-openid'}})
        app = client(session, api_domains={
            'https://developer.toutiao.com': 'https://proxy.example.test',
        })
        app.code2Session(code='test-login-code')
        self.assertEqual(session.sent[-1].url,
                         'https://proxy.example.test/api/apps/v2/jscode2session')

    def test_domain_override_applies_once_to_credentials_and_legacy_requests(self):
        cases = [
            ('mini token', lambda app: app._get_access_token(), '/api/apps/v2/token'),
            ('client token', lambda app: app._fetch_application_token('client'), '/oauth/client_token/'),
            ('get', lambda app: app.get('/ping', token=False), '/api/apps/ping'),
            ('post', lambda app: app.post('/ping', data={}, token=False), '/api/apps/ping'),
            ('fetch', lambda app: app.fetch('GET', 'https://developer.toutiao.com/health'), '/health'),
        ]
        for label, invoke, path in cases:
            with self.subTest(entrypoint=label):
                session = RecordingSession({'err_no': 0, 'data': {'access_token': 'test', 'expires_in': 7200}})
                app = client(session, api_domains={
                    'https://developer.toutiao.com': 'https://proxy.example.test/forward/',
                    'https://open.douyin.com': 'https://proxy.example.test/forward/',
                    'https://proxy.example.test': 'https://must-not-chain.example.test',
                })
                invoke(app)
                self.assertEqual(session.sent[-1].url, 'https://proxy.example.test/forward' + path)

    def test_http_error_preserves_platform_business_error_code(self):
        session = RecordingSession({
            'err_no': 10020,
            'err_tips': 'rate limited',
            'log_id': 'test-trace-id',
        }, status=429)
        app = client(session)
        with self.assertRaises(ByteDanceError) as caught:
            app.code2Session(code='test-login-code')
        error = caught.exception
        self.assertEqual(error.status_code, 429)
        self.assertEqual(error.log_id, 'test-trace-id')
        self.assertEqual(error.code, 10020)

    def test_http_error_preserves_nested_business_error_and_message(self):
        payload = {'message': 'success', 'data': {'error_code': 13000, 'description': 'invalid order'},
                   'extra': {'error_code': 2191000, 'description': 'upstream error', 'logid': 'trace'}}
        app = client(RecordingSession(payload, status=503))
        with self.assertRaises(ByteDanceError) as caught:
            app.fetch('GET', 'https://example.test')
        self.assertEqual(caught.exception.code, 13000)
        self.assertEqual(str(caught.exception), 'invalid order')
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.log_id, 'trace')
        self.assertEqual(caught.exception.payload, payload)

    def test_http_gateway_error_preserves_code_outside_normal_response_schema(self):
        # OAuth normally reports data.error_code. An HTTP gateway rejection can
        # instead use the platform's root err_no before reaching that service.
        app = client(RecordingSession({'err_no': 10020, 'err_tips': 'rate limited'}, status=429))
        with self.assertRaises(ByteDanceError) as caught:
            app.basic.interface_request_credential.non_user_authorization.get_client_token()
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.code, 10020)

    def test_http_error_without_business_code_remains_failure(self):
        for payload in ({'err_no': 0}, [], 'gateway error'):
            with self.subTest(payload=payload):
                app = client(RecordingSession(payload, status=500))
                with self.assertRaises(ByteDanceError) as caught:
                    app.fetch('GET', 'https://example.test')
                self.assertEqual(caught.exception.status_code, 500)
                self.assertIsNone(caught.exception.code)


if __name__ == '__main__':
    unittest.main()
