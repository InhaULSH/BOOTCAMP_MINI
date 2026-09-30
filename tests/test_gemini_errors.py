import io
import json
import unittest
from urllib.error import HTTPError
from snapdart.llm import gemini_http_message


class GeminiErrorsTest(unittest.TestCase):
    def error(self, message):
        return HTTPError('https://example.invalid', 403, 'Forbidden', {},
                         io.BytesIO(json.dumps({'error': {'message': message}}).encode()))

    def test_project_denied_is_not_quota_error(self):
        result = gemini_http_message(self.error('Your project has been denied access. Please contact support.'), 'secret')
        self.assertIn('프로젝트 접근을 차단', result)
        self.assertIn('대기로 해결되지 않습니다', result)

    def test_redacts_key(self):
        result = gemini_http_message(self.error('Denied secret-key AIzaOtherKey123'), 'secret-key')
        self.assertNotIn('secret-key', result)
        self.assertNotIn('AIzaOtherKey123', result)

    def test_non_json_response(self):
        error = HTTPError('https://example.invalid', 403, 'Forbidden', {}, io.BytesIO(b'<html>Forbidden</html>'))
        self.assertIn('상세 메시지 없음', gemini_http_message(error, 'secret'))
