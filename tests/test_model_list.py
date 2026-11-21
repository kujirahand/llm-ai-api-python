import unittest
from unittest.mock import patch

from llm_ai_api import llm
from llm_ai_api._model_list import ModelPages
from llm_ai_api.errors import LLMConfigError, LLMError
from tests.helpers import FreshRecorder, json_response


class ModelListTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, spec, responses, *, raw=False, **options):
        rec = FreshRecorder(*(lambda x=x: json_response(x) for x in responses))
        m = llm(spec, transport=rec.transport, **options)
        try:
            sync = m.models(raw=raw, timeout=12)
            requests = list(rec.requests)
        finally:
            await m.aclose()
        rec2 = FreshRecorder(*(lambda x=x: json_response(x) for x in responses))
        m = llm(spec, transport=rec2.transport, **options)
        try:
            asynchronous = await m.amodels(raw=raw, timeout=12)
        finally:
            await m.aclose()
        self.assertEqual(sync, asynchronous)
        for req in requests + rec2.requests:
            self.assertEqual(req.method, 'GET')
            self.assertEqual(req.content, b'')
            self.assertEqual(req.extensions['timeout']['read'], 12)
        return sync, requests, rec2.requests

    async def test_compatible_pages_and_raw(self):
        pages = [{'data': [{'id': 'a', 'other': 1}, {}, {'id': 4}], 'has_more': True, 'last_id': 'a +'}, {'data': [{'id': 'b'}]}]
        for raw, expected in [(False, ['a', 'b']), (True, pages[0]['data'] + pages[1]['data'])]:
            result, sync, async_requests = await self.exercise('openai:x', pages, raw=raw, api_key='k')
            self.assertEqual(result, expected)
            for reqs in (sync, async_requests):
                self.assertEqual(len(reqs), 2)
                self.assertEqual(reqs[1].url.params['after_id'], 'a +')
                self.assertEqual(reqs[0].url.path, '/v1/models')

    async def test_anthropic(self):
        result, sync, asynchronous = await self.exercise('anthropic:x', [{'data': [{'id': 'c'}]}], api_key='k')
        self.assertEqual(result, ['c'])
        for req in sync + asynchronous:
            self.assertEqual(req.url.path, '/v1/models')
            self.assertEqual(req.headers['x-api-key'], 'k')
            self.assertIn('anthropic-version', req.headers)
            self.assertNotIn('authorization', req.headers)

    async def test_google_native_and_proxy(self):
        pages = [{'models': [{'name': 'models/gemini-x', 'x': 1}], 'nextPageToken': 'a+b'}, {'models': [{'name': 'other'}]}]
        for raw, expected in [(False, ['gemini-x', 'other']), (True, pages[0]['models'] + pages[1]['models'])]:
            result, sync, asynchronous = await self.exercise('google:x', pages, api_key='k', raw=raw)
            self.assertEqual(result, expected)
            for reqs in (sync, asynchronous):
                self.assertEqual(reqs[0].url.path, '/v1beta/models')
                self.assertEqual(reqs[0].headers['x-goog-api-key'], 'k')
                self.assertEqual(reqs[1].url.params['pageToken'], 'a+b')
        result, sync, _ = await self.exercise('google:x', [{'data': [{'id': 'proxy'}]}], api_key='k', base_url='https://proxy.test/v1')
        self.assertEqual(result, ['proxy'])
        self.assertEqual(sync[0].url.path, '/v1/models')
        self.assertNotIn('x-goog-api-key', sync[0].headers)

    async def test_openrouter_optional_key(self):
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': ''}):
            for key in (None, 'secret'):
                result, sync, asynchronous = await self.exercise('openrouter:x', [{'data': [{'id': 'a'}]}], api_key=key)
                self.assertEqual(result, ['a'])
                for req in sync + asynchronous:
                    self.assertEqual(req.headers.get('authorization'), 'Bearer secret' if key else None)

    async def test_local_providers(self):
        for provider in ('lmstudio', 'ollama', 'strata'):
            _, sync, asynchronous = await self.exercise(provider + ':x', [{'data': []}])
            for req in sync + asynchronous:
                self.assertEqual(req.url.path, '/v1/models')

    async def test_invalid_shape_and_limit(self):
        for async_mode in (False, True):
            for page, code in [({'data': {}}, 'invalid_json_response'), ({'data': [], 'has_more': True, 'last_id': 'x'}, 'models_pagination_limit')]:
                rec = FreshRecorder(lambda: json_response(page))
                m = llm('openai:x', api_key='k', transport=rec.transport)
                try:
                    with patch.object(ModelPages, "limit", 2):
                        with self.assertRaises(LLMError) as ctx:
                            if async_mode:
                                await m.amodels()
                            else:
                                m.models()
                    self.assertEqual(ctx.exception.code, code)
                finally:
                    await m.aclose()

    def test_unsupported(self):
        m = llm('openai:x', api_key='k')
        try:
            with self.assertRaises(LLMConfigError) as ctx:
                ModelPages('unknown', m.client, False)
            self.assertEqual(ctx.exception.code, 'unsupported_models')
        finally:
            m.close()
