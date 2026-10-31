import ssl
import unittest
from unittest.mock import patch

import httpx

from llm_ai_api import get_connection, llm, set_connection
from llm_ai_api._connection import (
    DEFAULT_CONNECTION,
    build_httpx_kwargs,
    resolve_connection,
)
from llm_ai_api.errors import LLMConfigError
from llm_ai_api.openai import OpenAIClient


COMPLETION_PAYLOAD = {
    "id": "x",
    "object": "chat.completion",
    "created": 0,
    "model": "gpt-6-luna",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
    },
}


def completion_handler(request):
    return httpx.Response(200, json=COMPLETION_PAYLOAD)


class ConnectionSettingsTestCase(unittest.TestCase):
    def setUp(self):
        set_connection()
        self.addCleanup(set_connection)

    def test_defaults_are_used_by_clients_and_global_settings(self):
        with llm(
            "openai:gpt-6-luna",
            api_key="test-key",
            transport=httpx.MockTransport(completion_handler),
        ) as model:
            self.assertEqual(model.client.connection, DEFAULT_CONNECTION)

        self.assertEqual(get_connection(), DEFAULT_CONNECTION)

    def test_set_connection_replaces_previous_values_and_resets(self):
        set_connection(max_connections=50)
        self.assertEqual(get_connection()["max_connections"], 50)

        set_connection(keepalive_expiry=9)
        connection = get_connection()
        self.assertEqual(connection["max_connections"], 100)
        self.assertEqual(connection["keepalive_expiry"], 9.0)

        set_connection(verify=False)
        self.assertIs(get_connection()["verify"], False)

        set_connection()
        self.assertEqual(get_connection(), DEFAULT_CONNECTION)

    def test_global_connection_settings_apply_to_new_clients(self):
        set_connection(max_connections=50, keepalive_expiry=2)

        with llm(
            "openai:gpt-6-luna",
            api_key="test-key",
            transport=httpx.MockTransport(completion_handler),
        ) as model:
            self.assertEqual(model.client.connection["max_connections"], 50)
            self.assertEqual(model.client.connection["keepalive_expiry"], 2.0)

    def test_instance_connection_settings_apply_to_client(self):
        with llm(
            "openai:gpt-6-luna",
            api_key="test-key",
            transport=httpx.MockTransport(completion_handler),
            connection={"max_connections": 5},
        ) as model:
            self.assertEqual(model.client.connection["max_connections"], 5)
            self.assertEqual(
                model.client.connection["keepalive_expiry"],
                DEFAULT_CONNECTION["keepalive_expiry"],
            )

    def test_instance_settings_merge_per_key_with_global_settings(self):
        set_connection(max_connections=50)

        with llm(
            "openai:gpt-6-luna",
            api_key="test-key",
            transport=httpx.MockTransport(completion_handler),
            connection={"keepalive_expiry": 1},
        ) as model:
            self.assertEqual(model.client.connection["max_connections"], 50)
            self.assertEqual(model.client.connection["keepalive_expiry"], 1.0)

    def test_instance_none_resets_a_global_setting_to_default(self):
        set_connection(max_connections=50)

        with llm(
            "openai:gpt-6-luna",
            api_key="test-key",
            transport=httpx.MockTransport(completion_handler),
            connection={"max_connections": None},
        ) as model:
            self.assertEqual(
                model.client.connection["max_connections"],
                DEFAULT_CONNECTION["max_connections"],
            )

    def test_existing_client_connection_is_not_changed_by_later_global_change(self):
        with llm(
            "openai:gpt-6-luna",
            api_key="test-key",
            transport=httpx.MockTransport(completion_handler),
            connection={"max_connections": 5},
        ) as model:
            set_connection(max_connections=50)
            self.assertEqual(model.client.connection["max_connections"], 5)

    def test_build_httpx_kwargs(self):
        resolved = resolve_connection(
            {"max_connections": 7, "max_keepalive_connections": 3, "proxy": "http://proxy.example:8080"}
        )
        kwargs = build_httpx_kwargs(resolved)

        self.assertEqual(kwargs["limits"].max_connections, 7)
        self.assertEqual(kwargs["limits"].max_keepalive_connections, 3)
        self.assertEqual(kwargs["proxy"], "http://proxy.example:8080")
        self.assertIs(kwargs["verify"], True)

    def test_httpx_client_receives_connection_kwargs_without_transport(self):
        captured = {}
        real_client = httpx.Client

        def fake_client(*args, **kwargs):
            captured.update(kwargs)
            return real_client(
                transport=httpx.MockTransport(completion_handler),
                *args,
                **{key: value for key, value in kwargs.items() if key != "proxy"},
            )

        with patch("llm_ai_api._http.httpx.Client", side_effect=fake_client):
            client = OpenAIClient(
                api_key="test-key",
                connection={
                    "max_connections": 7,
                    "proxy": "http://proxy.example:8080",
                },
            )
            self.addCleanup(client.close)

            self.assertEqual(captured["limits"].max_connections, 7)
            self.assertEqual(captured["proxy"], "http://proxy.example:8080")

    def test_transport_validates_connection_but_does_not_apply_proxy(self):
        with self.assertRaises(LLMConfigError) as context:
            OpenAIClient(
                api_key="test-key",
                transport=httpx.MockTransport(completion_handler),
                connection={"max_connections": 0},
            )
        self.assertEqual(context.exception.code, "invalid_connection")

        set_connection(proxy="http://proxy.example:8080")
        with OpenAIClient(
            api_key="test-key",
            transport=httpx.MockTransport(completion_handler),
        ) as client:
            result = client.chat("gpt-6-luna", [{"role": "user", "content": "hi"}])
            self.assertEqual(result.text, "ok")

    def test_invalid_connection_values(self):
        invalid_values = [
            {"unknown": "value"},
            {"max_connections": 0},
            {"max_connections": True},
            {"max_connections": "10"},
            {"max_keepalive_connections": -1},
            {"keepalive_expiry": -1},
            {"connect_timeout": 0},
            {"verify": "/nonexistent/ca.pem"},
            {"cert": "/nonexistent/cert.pem"},
            {"cert": ("/nonexistent/cert.pem", "/nonexistent/key.pem")},
            {"proxy": "ftp://x"},
            {"proxy": "http://"},
        ]

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(LLMConfigError) as context:
                    resolve_connection(value)
                self.assertEqual(context.exception.code, "invalid_connection")

                if "unknown" in value:
                    with self.assertRaises(TypeError):
                        set_connection(**value)
                else:
                    with self.assertRaises(LLMConfigError) as context:
                        set_connection(**value)
                    self.assertEqual(context.exception.code, "invalid_connection")

    def test_invalid_proxy_does_not_expose_password(self):
        with self.assertRaises(LLMConfigError) as context:
            resolve_connection({"proxy": "ftp://user:secretpw@proxy.example:8080"})

        self.assertEqual(context.exception.code, "invalid_connection")
        self.assertNotIn("secretpw", str(context.exception))

    def test_existing_verify_path_is_valid_for_resolution(self):
        resolved = resolve_connection({"verify": __file__})
        self.assertEqual(resolved["verify"], __file__)

    def test_valid_system_ca_file_builds_tls_context_when_available(self):
        cafile = ssl.get_default_verify_paths().cafile
        if cafile is None:
            self.skipTest("No system CA file is available")

        kwargs = build_httpx_kwargs(resolve_connection({"verify": cafile}))
        self.assertIsInstance(kwargs["verify"], ssl.SSLContext)

    def test_verify_false_builds_unverified_tls_context(self):
        kwargs = build_httpx_kwargs(resolve_connection({"verify": False}))
        context = kwargs["verify"]

        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        self.assertFalse(context.check_hostname)

    def test_scheme_less_proxy_password_is_masked(self):
        with self.assertRaises(LLMConfigError) as context:
            resolve_connection({"proxy": "user:secretpw@proxy.example:8080"})

        self.assertNotIn("secretpw", str(context.exception))

    def test_proxy_without_hostname_raises_config_error(self):
        with self.assertRaises(LLMConfigError):
            resolve_connection({"proxy": "http://user:secretpw@"})

    def test_proxy_bad_port_raises_config_error(self):
        with self.assertRaises(LLMConfigError):
            resolve_connection({"proxy": "http://proxy.example:badport"})

    def test_proxy_invalid_ipv6_raises_config_error(self):
        with self.assertRaises(LLMConfigError):
            resolve_connection({"proxy": "http://[::1"})

    def test_nan_connect_timeout_raises_config_error(self):
        with self.assertRaises(LLMConfigError):
            resolve_connection({"connect_timeout": float("nan")})

    def test_infinite_keepalive_expiry_raises_config_error(self):
        with self.assertRaises(LLMConfigError):
            resolve_connection({"keepalive_expiry": float("inf")})

    def test_cert_directory_raises_config_error(self):
        import shutil
        import tempfile

        directory = tempfile.mkdtemp()
        try:
            with self.assertRaises(LLMConfigError):
                resolve_connection({"cert": directory})
        finally:
            shutil.rmtree(directory)

    def test_cert_list_is_normalized_to_tuple(self):
        resolved = resolve_connection({"cert": [__file__, __file__]})

        self.assertEqual(resolved["cert"], (__file__, __file__))
        self.assertIsInstance(resolved["cert"], tuple)

class AsyncConnectionSettingsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_connection()
        self.addCleanup(set_connection)

    async def test_async_client_inherits_construction_time_connection(self):
        set_connection(max_connections=50)

        with llm(
            "openai:gpt-6-luna",
            api_key="test-key",
            transport=httpx.MockTransport(completion_handler),
            connection={"keepalive_expiry": 1},
        ) as model:
            set_connection(max_connections=99, keepalive_expiry=9)

            response = await model.aask("hi")
            self.assertEqual(response, "ok")

            async_client = model._get_async_client()
            self.assertEqual(async_client.connection["max_connections"], 50)
            self.assertEqual(async_client.connection["keepalive_expiry"], 1.0)


if __name__ == "__main__":
    unittest.main()
