"""InsufficientCreditsError (#120, #124): detection, hints, and no-retry behavior.

Fixtures cite the page they were taken from. Bodies marked as shaped from a
documented code, rather than copied from a published JSON example, say so.
No live key was available to recapture these responses.
"""

import unittest

from llm_ai_api import (
    APIStatusError,
    BadRequestError,
    InsufficientCreditsError,
    OpenAIClient,
    PermissionDeniedError,
    RateLimitError,
    set_cache,
    set_log,
)
from llm_ai_api._async_clients import _AsyncOpenAIClient
from llm_ai_api.errors import is_insufficient_credits, status_error_class

from .helpers import Recorder, json_response, sse_response

XAI_NO_CREDITS = {
    "code": "permission-denied",
    "error": (
        "Your team doesn't have any credits or licenses. "
        "Please purchase credits at https://console.x.ai."
    ),
}
XAI_NO_CREDITS_NESTED = {
    "error": {
        "code": "permission-denied",
        "message": "The team does not have any credits or licenses.",
    }
}
MUSE_BILLING = {
    "error": {
        "type": "billing_error",
        "code": "billing_not_configured",
        "message": "Billing is not configured for this workspace.",
    }
}
OPENAI_QUOTA = {
    "error": {
        "message": "You exceeded your current quota, please check your plan and billing details.",
        "type": "insufficient_quota",
        "code": "insufficient_quota",
    }
}
NORMAL_403 = {
    "error": {
        "code": "permission-denied",
        "message": "This API key cannot use this model.",
    }
}
NORMAL_429 = {
    "error": {
        "message": "Rate limit reached for requests.",
        "type": "rate_limit_exceeded",
        "code": "rate_limit_exceeded",
    }
}
# OpenAI error codes (2026-11-21):
# https://developers.openai.com/api/docs/guides/error-codes
# The page names error.code and says the broader error.type can still be
# insufficient_quota. It does not print a full JSON body, so the envelope
# follows the insufficient_quota shape above. Message text is the page's
# "Cause" line, not a captured response.
OPENAI_CREDIT_BALANCE = {
    "error": {
        "message": "Your organization has no prepaid credits remaining.",
        "type": "insufficient_quota",
        "code": "credit_balance_exhausted",
    }
}
OPENAI_ORG_SPEND = {
    "error": {
        "message": "Your organization reached its enforced spend limit.",
        "type": "insufficient_quota",
        "code": "organization_spend_limit_exceeded",
    }
}
OPENAI_PROJECT_SPEND = {
    "error": {
        "message": "Your project reached its enforced spend limit.",
        "code": "project_spend_limit_exceeded",
    }
}
OPENAI_ORG_USAGE = {
    "error": {
        "message": "Your organization reached its OpenAI-assigned usage limit.",
        "code": "organization_usage_limit_exceeded",
    }
}
OPENAI_SLOW_DOWN = {
    "error": {
        "message": "Your request rate increased too quickly.",
        "type": "rate_limit_error",
        "code": "slow_down",
    }
}
# Anthropic credit sentence, quoted on the API-credits page:
# https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers
# HTTP 400 + invalid_request_error was reproduced on 2026-09-17 in
# https://github.com/anthropics/anthropic-sdk-typescript/issues/618
# (not recaptured with a key here). The errors page still lists 402
# billing_error for payment problems and does not show this sentence.
ANTHROPIC_CREDIT_BALANCE = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": (
            "Your credit balance is too low to access the Anthropic API. "
            "Please go to Plans & Billing to upgrade or purchase credits."
        ),
    },
    "request_id": "req_011Cf75wfCXCbniKKrP6wSut",
}
# Shorter form quoted on the same page for Claude Code, not confirmed as the
# HTTP body.
ANTHROPIC_CREDIT_BALANCE_SHORT = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "Credit balance too low",
    },
}
ANTHROPIC_BAD_REQUEST = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "max_tokens: Field required",
    },
}
# Official example: https://platform.claude.com/docs/en/api/rate-limits
# "Reaching your spend cap". Same error.type as a rate limit; the code is
# error.details.error_code.
ANTHROPIC_SPEND_CAP = {
    "type": "error",
    "error": {
        "type": "rate_limit_error",
        "message": (
            "You have reached your API usage limits: your organization has "
            "crossed its monthly API usage threshold, set based on your "
            "organization's API tier. You will regain access on 2026-09-01 "
            "at 00:00 UTC."
        ),
        "details": {"error_code": "enforced_spend_limit_reached"},
    },
    "request_id": "req_018EeWyXxfu5pfWkrYcMdjWG",
}
ANTHROPIC_RATE_LIMIT = {
    "type": "error",
    "error": {
        "type": "rate_limit_error",
        "message": "Number of request tokens has exceeded your per-minute rate limit.",
    },
}
# The same page says a caller-set spend limit is HTTP 400 invalid_request_error
# and that the message starts with these sentences. Text after the prefix is
# not from the page.
ANTHROPIC_USER_SPEND_LIMIT = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": (
            "You have reached your specified API usage limits. "
            "You will regain access on 2026-09-01 at 00:00 UTC."
        ),
    },
}
ANTHROPIC_WORKSPACE_SPEND_LIMIT = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": (
            "You have reached your specified workspace API usage limits. "
            "Raise or remove the limit to restore access."
        ),
    },
}
# Google prepay depletion, posted by a Google employee on 2026-09-18.
# HTTP status changed from 429 to 402; status inside the body stays
# RESOURCE_EXHAUSTED. Other rate limits stay 429.
# https://discuss.ai.google.dev/t/api-update-depleted-prepay-credits-now-return-http-402-instead-of-429/183654
GOOGLE_PREPAY = {
    "error": {
        "code": 402,
        "message": (
            "Your prepayment credits are depleted. Please go to AI Studio at "
            "https://ai.studio/projects to manage your project and billing. "
            "Learn more at https://ai.google.dev/gemini-api/docs/billing#prepay."
        ),
        "status": "RESOURCE_EXHAUSTED",
    }
}
# Not a published JSON sample. The rate-limits page says a 429
# RESOURCE_EXHAUSTED (including a spend-based limit) should be retried:
# https://ai.google.dev/gemini-api/docs/rate-limits
# The message mentions "quota" on purpose. That word is not enough.
GOOGLE_RESOURCE_EXHAUSTED = {
    "error": {
        "code": 429,
        "message": "Resource has been exhausted (e.g. check quota).",
        "status": "RESOURCE_EXHAUSTED",
    }
}
# Interactions API codes and the error envelope:
# https://ai.google.dev/gemini-api/docs/api-errors
# The page's table describes each code. It does not print these messages, so
# the message text is that description.
GOOGLE_QUOTA_EXCEEDED = {
    "error": {
        "code": "quota_exceeded",
        "message": "You have exceeded your daily quota.",
    }
}
GOOGLE_RATE_LIMIT = {
    "error": {
        "code": "rate_limit_exceeded",
        "message": "You have exceeded the per-minute or per-second request or token limit.",
    }
}
GOOGLE_TOO_MANY = {
    "error": {
        "code": "too_many_requests",
        "message": "You have made too many requests in a short period of time.",
    }
}
GOOGLE_FAILED_PRECONDITION = {
    "error": {
        "code": "failed_precondition",
        "message": (
            "The request cannot be processed because a prerequisite is not met "
            "(for example, disabled billing)."
        ),
    }
}
# OpenRouter SDK example (numeric error.code, HTTP 402):
# https://openrouter.ai/docs/client-sdks/typescript/models/paymentrequiredresponseerrordata
OPENROUTER_CREDITS = {
    "error": {
        "code": 402,
        "message": "Insufficient credits. Add more using https://openrouter.ai/credits",
    }
}
# Official 403 budget example:
# https://openrouter.ai/docs/api_reference/errors-and-debugging
# The page lists openrouter_workspace_budget and openrouter_key_limit in the
# same table and prints this one JSON body.
OPENROUTER_GUARDRAIL_BUDGET = {
    "error": {
        "code": 403,
        "message": (
            "Budget limit exceeded (weekly limit). Contact your org admin. "
            "$52.00 of $50.00 used; resets 2026-10-12T00:00:00.000Z."
        ),
        "metadata": {
            "limit_source": "openrouter_guardrail_budget",
            "remedy_hint": (
                "Wait for the budget window to reset (see metadata.resets_at), "
                "or ask your org admin to raise the guardrail budget."
            ),
            "scope": "workspace_default_member",
            "limit_usd": 50,
            "spend_usd": 52,
            "resets_at": "2026-10-12T00:00:00.000Z",
        },
    }
}
OPENROUTER_CONTENT_BLOCK = {
    "error": {
        "code": 403,
        "message": "Request blocked: prompt injection patterns detected",
        "metadata": {"patterns": ["ignore all previous instructions"]},
    }
}
# In-flight budget is HTTP 402 and transient. Documented at
# https://openrouter.ai/docs/api_reference/limits
# 402 stays InsufficientCreditsError; this library does not retry 402.
OPENROUTER_IN_FLIGHT = {
    "error": {
        "code": 402,
        "message": (
            "This request would exceed your available credits given your "
            "current in-flight requests. Retry after in-flight requests settle, "
            "or add credits."
        ),
        "metadata": {
            "reason": "in_flight_budget_exhausted",
            "limit_source": "openrouter_in_flight_budget",
        },
    }
}
# Meta's published 402 body: https://dev.meta.ai/docs/error-handling
MUSE_OFFICIAL = {
    "error": {
        "message": "Billing account issue. Please check your account status.",
        "type": "billing_error",
        "param": None,
        "code": "billing_not_configured",
    }
}


def make_sync(rec, **kw):
    # Pin the message language so the tests do not depend on the locale.
    kw.setdefault("lang", "en")
    c = OpenAIClient(api_key="k", transport=rec.transport, **kw)
    c.sleeps = []
    c._sleep = c.sleeps.append
    return c


class DetectTest(unittest.TestCase):
    def test_http_402_always_matches(self):
        bodies = (
            None,
            {},
            "plain",
            MUSE_BILLING,
            MUSE_OFFICIAL,
            OPENROUTER_CREDITS,
            GOOGLE_PREPAY,
            OPENROUTER_IN_FLIGHT,
        )
        for body in bodies:
            self.assertTrue(is_insufficient_credits(402, body))
            self.assertIs(status_error_class(402, body), InsufficientCreditsError)

    def test_xai_403_credits_message(self):
        # Reported live wording, not an official JSON sample: "403
        # permission-denied: Your newly created team doesn't have any credits
        # or licenses yet." The last body is a synthetic rewording that still
        # contains the word "credit".
        reworded = {
            "code": "permission-denied",
            "error": "The team has no remaining credit.",
        }
        newly_created = {
            "code": "permission-denied",
            "error": "Your newly created team doesn't have any credits or licenses yet.",
        }
        used_all = {
            "code": "permission-denied",
            "error": "This team has used all available credits.",
        }
        zero = {
            "code": "permission-denied",
            "error": "This team has 0 credits.",
        }
        for body in (
            XAI_NO_CREDITS,
            XAI_NO_CREDITS_NESTED,
            newly_created,
            reworded,
            used_all,
            zero,
        ):
            self.assertTrue(is_insufficient_credits(403, body))
            self.assertIs(status_error_class(403, body), InsufficientCreditsError)
        upper = {
            "code": "PERMISSION_DENIED",
            "error": "Your team doesn't have any credits or licenses.",
        }
        self.assertTrue(is_insufficient_credits(403, upper))

    def test_openai_429_insufficient_quota(self):
        self.assertTrue(is_insufficient_credits(429, OPENAI_QUOTA))
        self.assertIs(status_error_class(429, OPENAI_QUOTA), InsufficientCreditsError)
        # The code/type alone is enough, even on an unusual status.
        self.assertTrue(
            is_insufficient_credits(403, {"error": {"code": "insufficient_quota"}})
        )

    def test_normal_403_and_429_are_unchanged(self):
        self.assertFalse(is_insufficient_credits(403, NORMAL_403))
        self.assertIs(status_error_class(403, NORMAL_403), PermissionDeniedError)
        self.assertFalse(is_insufficient_credits(429, NORMAL_429))
        self.assertIs(status_error_class(429, NORMAL_429), RateLimitError)
        self.assertFalse(is_insufficient_credits(429, {}))
        self.assertIs(status_error_class(429), RateLimitError)

    def test_403_needs_both_code_and_credit_word(self):
        only_code = {"code": "permission-denied", "error": "Access denied."}
        only_phrase = {
            "error": "Your team doesn't have any credits or licenses."
        }
        self.assertFalse(is_insufficient_credits(403, only_code))
        self.assertFalse(is_insufficient_credits(403, only_phrase))
        # The word has to stand alone. A URL path, "non-credit", and a longer
        # word that merely contains "credit" stay permission errors.
        for message in (
            "The model is not accredited for this key.",
            "See https://console.x.ai/credits before retrying.",
            "This key is limited to non-credit operations.",
            "This key cannot use credit-based billing.",
            "Credits are available only for another model.",
        ):
            body = {"code": "permission-denied", "error": message}
            self.assertFalse(is_insufficient_credits(403, body), message)
            self.assertIs(status_error_class(403, body), PermissionDeniedError)

    def test_credit_word_on_429_is_not_enough(self):
        body = {"error": {"message": "out of credits", "code": "rate_limit_exceeded"}}
        self.assertFalse(is_insufficient_credits(429, body))
        self.assertIs(status_error_class(429, body), RateLimitError)

    def test_unrelated_status_does_not_match_on_message_alone(self):
        body = {"error": {"message": "out of credits"}}
        self.assertFalse(is_insufficient_credits(400, body))
        self.assertFalse(is_insufficient_credits(500, body))
        # A 5xx that quotes a billing sentence is still retried.
        quoted = {
            "error": {
                "message": "upstream said: Your credit balance is too low to access the Anthropic API."
            }
        }
        quoted["error"]["type"] = "invalid_request_error"
        self.assertFalse(is_insufficient_credits(400, quoted))
        self.assertIs(status_error_class(400, quoted), BadRequestError)
        self.assertFalse(is_insufficient_credits(500, quoted))
        self.assertFalse(is_insufficient_credits(503, quoted))
        for body in (OPENAI_CREDIT_BALANCE, ANTHROPIC_SPEND_CAP):
            self.assertFalse(is_insufficient_credits(500, body))

    def test_openai_billing_codes_match_and_slow_down_does_not(self):
        for body in (
            OPENAI_CREDIT_BALANCE,
            OPENAI_ORG_SPEND,
            OPENAI_PROJECT_SPEND,
            OPENAI_ORG_USAGE,
        ):
            self.assertTrue(is_insufficient_credits(429, body))
            self.assertIs(status_error_class(429, body), InsufficientCreditsError)
        self.assertFalse(is_insufficient_credits(429, OPENAI_SLOW_DOWN))
        self.assertIs(status_error_class(429, OPENAI_SLOW_DOWN), RateLimitError)
        # The specific code is enough when type is not insufficient_quota.
        code_only = {
            "error": {
                "message": "Add credits to continue using the API.",
                "type": "invalid_request_error",
                "code": "credit_balance_exhausted",
            }
        }
        self.assertTrue(is_insufficient_credits(429, code_only))

    def test_anthropic_credit_message_and_spend_cap(self):
        for body in (
            ANTHROPIC_CREDIT_BALANCE,
            ANTHROPIC_CREDIT_BALANCE_SHORT,
            ANTHROPIC_USER_SPEND_LIMIT,
            ANTHROPIC_WORKSPACE_SPEND_LIMIT,
        ):
            self.assertTrue(is_insufficient_credits(400, body), body)
            self.assertIs(status_error_class(400, body), InsufficientCreditsError)
        self.assertFalse(is_insufficient_credits(400, ANTHROPIC_BAD_REQUEST))
        self.assertIs(status_error_class(400, ANTHROPIC_BAD_REQUEST), BadRequestError)
        self.assertTrue(is_insufficient_credits(429, ANTHROPIC_SPEND_CAP))
        self.assertIs(status_error_class(429, ANTHROPIC_SPEND_CAP), InsufficientCreditsError)
        # Same error.type as the spend cap, without the details code.
        self.assertFalse(is_insufficient_credits(429, ANTHROPIC_RATE_LIMIT))
        self.assertIs(status_error_class(429, ANTHROPIC_RATE_LIMIT), RateLimitError)
        # The spend-cap sentence without details.error_code shares
        # "You have reached your API usage limits" but not the "specified"
        # prefix used for a caller-set limit. It stays a rate limit.
        without_code = {
            "type": "error",
            "error": {
                "type": "rate_limit_error",
                "message": ANTHROPIC_SPEND_CAP["error"]["message"],
            },
        }
        self.assertFalse(is_insufficient_credits(429, without_code))
        self.assertIs(status_error_class(429, without_code), RateLimitError)

    def test_google_resource_exhausted_stays_rate_limit(self):
        self.assertTrue(is_insufficient_credits(402, GOOGLE_PREPAY))
        # The prepay sentence on a 429 is not classified. Google split that
        # case out as HTTP 402; a 429 with this status is a rate limit.
        self.assertFalse(is_insufficient_credits(429, GOOGLE_PREPAY))
        self.assertIs(status_error_class(429, GOOGLE_PREPAY), RateLimitError)
        self.assertFalse(is_insufficient_credits(429, GOOGLE_RESOURCE_EXHAUSTED))
        self.assertIs(
            status_error_class(429, GOOGLE_RESOURCE_EXHAUSTED), RateLimitError
        )
        self.assertTrue(is_insufficient_credits(429, GOOGLE_QUOTA_EXCEEDED))
        self.assertIs(
            status_error_class(429, GOOGLE_QUOTA_EXCEEDED), InsufficientCreditsError
        )
        for body in (GOOGLE_RATE_LIMIT, GOOGLE_TOO_MANY):
            self.assertFalse(is_insufficient_credits(429, body))
            self.assertIs(status_error_class(429, body), RateLimitError)
        # "disabled billing" is only an example of failed_precondition.
        self.assertFalse(is_insufficient_credits(400, GOOGLE_FAILED_PRECONDITION))
        self.assertIs(
            status_error_class(400, GOOGLE_FAILED_PRECONDITION), BadRequestError
        )

    def test_openrouter_budget_limit_source(self):
        for source in (
            "openrouter_guardrail_budget",
            "openrouter_workspace_budget",
            "openrouter_key_limit",
        ):
            body = {
                "error": {
                    "code": 403,
                    "message": "Budget limit exceeded.",
                    "metadata": {"limit_source": source},
                }
            }
            self.assertTrue(is_insufficient_credits(403, body), source)
            self.assertIs(status_error_class(403, body), InsufficientCreditsError)
        self.assertTrue(is_insufficient_credits(403, OPENROUTER_GUARDRAIL_BUDGET))
        self.assertFalse(is_insufficient_credits(403, OPENROUTER_CONTENT_BLOCK))
        self.assertIs(
            status_error_class(403, OPENROUTER_CONTENT_BLOCK), PermissionDeniedError
        )
        # In-flight on a 403 (the documented status is 402) is not a budget hit.
        inflight_403 = {
            "error": {
                "code": 403,
                "message": OPENROUTER_IN_FLIGHT["error"]["message"],
                "metadata": {"limit_source": "openrouter_in_flight_budget"},
            }
        }
        self.assertFalse(is_insufficient_credits(403, inflight_403))
        self.assertIs(status_error_class(403, inflight_403), PermissionDeniedError)
        credits_403 = {
            "error": {
                "code": 403,
                "message": "Credit metadata from an upstream response.",
                "metadata": {"limit_source": "openrouter_credits"},
            }
        }
        self.assertFalse(is_insufficient_credits(403, credits_403))
        self.assertIs(status_error_class(403, credits_403), PermissionDeniedError)
        server_error = {
            "error": {
                "code": 500,
                "message": "Failed while reading budget metadata.",
                "metadata": {"limit_source": "openrouter_guardrail_budget"},
            }
        }
        self.assertFalse(is_insufficient_credits(500, server_error))


class SyncRequestTest(unittest.TestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)

    def _assert_credits_error(self, rec, status, body, lang="en"):
        c = make_sync(rec, max_retries=2, lang=lang)
        with self.assertRaises(InsufficientCreditsError) as cm:
            c.request("/x", {})
        e = cm.exception
        self.assertIsInstance(e, APIStatusError)
        self.assertEqual(e.status_code, status)
        self.assertEqual(e.body, body)
        self.assertEqual(e.code, "api_error")
        self.assertEqual(e.retries, 0)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(c.sleeps, [])
        self.assertIs(type(e), InsufficientCreditsError)
        return e

    def test_http_402(self):
        rec = Recorder(json_response(MUSE_BILLING, 402))
        e = self._assert_credits_error(rec, 402, MUSE_BILLING)
        self.assertIn("Billing is not configured", str(e))
        self.assertIn("Hint: check your billing and credit settings.", str(e))
        self.assertNotIn("rate limit", str(e).lower())

    def test_http_402_japanese_hint(self):
        rec = Recorder(json_response(MUSE_BILLING, 402))
        e = self._assert_credits_error(rec, 402, MUSE_BILLING, lang="ja")
        self.assertIn("ヒント: 課金・クレジット設定を確認してください。", str(e))

    def test_xai_403_credits(self):
        rec = Recorder(json_response(XAI_NO_CREDITS, 403))
        e = self._assert_credits_error(rec, 403, XAI_NO_CREDITS)
        self.assertIn("doesn't have any credits or licenses", str(e))
        self.assertIn("Hint: check your billing and credit settings.", str(e))
        self.assertNotIn("may not have permission", str(e))

    def test_openai_429_insufficient_quota_is_not_retried(self):
        rec = Recorder(json_response(OPENAI_QUOTA, 429, {"retry-after": "3"}))
        e = self._assert_credits_error(rec, 429, OPENAI_QUOTA)
        self.assertIn("exceeded your current quota", str(e))
        self.assertIn("Hint: check your billing and credit settings.", str(e))
        self.assertNotIn("Wait a while and retry", str(e))

    def test_normal_403_stays_permission_denied(self):
        rec = Recorder(json_response(NORMAL_403, 403))
        c = make_sync(rec, max_retries=2)
        with self.assertRaises(PermissionDeniedError) as cm:
            c.request("/x", {})
        self.assertNotIsInstance(cm.exception, InsufficientCreditsError)
        self.assertEqual(len(rec.requests), 1)
        self.assertIn("may not have permission", str(cm.exception))
        self.assertNotIn("billing and credit settings", str(cm.exception))

    def test_normal_429_is_still_retried(self):
        rec = Recorder(
            json_response(NORMAL_429, 429, {"retry-after": "3"}),
            json_response({"ok": True}),
        )
        c = make_sync(rec, max_retries=2)
        self.assertEqual(c.request("/x", {}), {"ok": True})
        self.assertEqual(len(rec.requests), 2)
        self.assertEqual(c.sleeps, [3.0])

    def test_normal_429_exhausted_stays_rate_limit_error(self):
        rec = Recorder(json_response(NORMAL_429, 429))
        c = make_sync(rec, max_retries=1)
        with self.assertRaises(RateLimitError) as cm:
            c.request("/x", {})
        self.assertNotIsInstance(cm.exception, InsufficientCreditsError)
        self.assertEqual(len(rec.requests), 2)
        self.assertIn("Wait a while and retry", str(cm.exception))

    def test_documented_credit_429s_are_not_retried(self):
        for body in (
            OPENAI_CREDIT_BALANCE,
            OPENAI_ORG_SPEND,
            OPENAI_PROJECT_SPEND,
            OPENAI_ORG_USAGE,
            ANTHROPIC_SPEND_CAP,
            GOOGLE_QUOTA_EXCEEDED,
        ):
            with self.subTest(code=body["error"].get("code") or body["error"].get("details")):
                rec = Recorder(json_response(body, 429, {"retry-after": "3"}))
                e = self._assert_credits_error(rec, 429, body)
                self.assertIn("billing and credit settings", str(e))
                self.assertNotIn("Wait a while and retry", str(e))

    def test_anthropic_400_credit_message_uses_credits_hint(self):
        rec = Recorder(json_response(ANTHROPIC_CREDIT_BALANCE, 400))
        e = self._assert_credits_error(rec, 400, ANTHROPIC_CREDIT_BALANCE)
        self.assertIn("credit balance is too low", str(e))
        self.assertIn("billing and credit settings", str(e))
        self.assertNotIn("check the request", str(e))

    def test_anthropic_400_validation_stays_bad_request(self):
        rec = Recorder(json_response(ANTHROPIC_BAD_REQUEST, 400))
        c = make_sync(rec, max_retries=2)
        with self.assertRaises(BadRequestError) as cm:
            c.request("/x", {})
        self.assertNotIsInstance(cm.exception, InsufficientCreditsError)
        self.assertEqual(len(rec.requests), 1)
        self.assertIn("check the request", str(cm.exception))
        self.assertNotIn("billing and credit settings", str(cm.exception))

    def test_openrouter_403_budget_is_credits_error(self):
        rec = Recorder(json_response(OPENROUTER_GUARDRAIL_BUDGET, 403))
        e = self._assert_credits_error(rec, 403, OPENROUTER_GUARDRAIL_BUDGET)
        self.assertIn("Budget limit exceeded", str(e))
        self.assertIn("billing and credit settings", str(e))
        self.assertNotIn("may not have permission", str(e))

    def test_openrouter_403_content_block_stays_permission_denied(self):
        rec = Recorder(json_response(OPENROUTER_CONTENT_BLOCK, 403))
        c = make_sync(rec, max_retries=2)
        with self.assertRaises(PermissionDeniedError) as cm:
            c.request("/x", {})
        self.assertNotIsInstance(cm.exception, InsufficientCreditsError)
        self.assertEqual(len(rec.requests), 1)
        self.assertIn("may not have permission", str(cm.exception))

    def test_ordinary_429s_are_still_retried(self):
        for body in (
            GOOGLE_RESOURCE_EXHAUSTED,
            GOOGLE_RATE_LIMIT,
            GOOGLE_TOO_MANY,
            OPENAI_SLOW_DOWN,
            ANTHROPIC_RATE_LIMIT,
        ):
            with self.subTest(body=body["error"].get("code") or body["error"].get("status")):
                rec = Recorder(
                    json_response(body, 429, {"retry-after": "3"}),
                    json_response({"ok": True}),
                )
                c = make_sync(rec, max_retries=2)
                self.assertEqual(c.request("/x", {}), {"ok": True})
                self.assertEqual(len(rec.requests), 2)
                self.assertEqual(c.sleeps, [3.0])

    def test_500_with_embedded_credit_code_is_still_retried(self):
        rec = Recorder(
            json_response(OPENAI_CREDIT_BALANCE, 500, {"retry-after": "3"}),
            json_response({"ok": True}),
        )
        c = make_sync(rec, max_retries=2)
        self.assertEqual(c.request("/x", {}), {"ok": True})
        self.assertEqual(len(rec.requests), 2)
        self.assertEqual(c.sleeps, [3.0])

    def test_stream_open_raises_credits_error(self):
        cases = (
            (402, MUSE_BILLING),
            (403, XAI_NO_CREDITS),
            (429, OPENAI_QUOTA),
            (429, ANTHROPIC_SPEND_CAP),
            (400, ANTHROPIC_CREDIT_BALANCE),
        )
        for status, body in cases:
            with self.subTest(status=status):
                rec = Recorder(json_response(body, status))
                c = make_sync(rec, max_retries=2)
                with self.assertRaises(InsufficientCreditsError) as cm:
                    c.request_stream("/x", {})
                self.assertEqual(cm.exception.status_code, status)
                self.assertEqual(len(rec.requests), 1)
                self.assertEqual(c.sleeps, [])

    def test_stream_open_normal_429_is_retried(self):
        rec = Recorder(
            json_response(NORMAL_429, 429),
            sse_response("data: ok\n\n"),
        )
        c = make_sync(rec, max_retries=2)
        events = list(c.request_stream("/x", {}))
        self.assertEqual([e.data for e in events], ["ok"])
        self.assertEqual(len(rec.requests), 2)


class AsyncRequestTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)
        self.sleeps = []

    def make(self, rec, **kw):
        kw.setdefault("lang", "en")
        c = _AsyncOpenAIClient(api_key="k", transport=rec.transport, **kw)

        async def record_sleep(seconds):
            self.sleeps.append(seconds)

        c._sleep = record_sleep
        self.addAsyncCleanup(c.aclose)
        return c

    async def test_http_402(self):
        rec = Recorder(json_response(MUSE_BILLING, 402))
        c = self.make(rec, max_retries=2)
        with self.assertRaises(InsufficientCreditsError) as cm:
            await c.request("/x", {})
        self.assertEqual(cm.exception.status_code, 402)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(self.sleeps, [])
        self.assertIn("billing and credit settings", str(cm.exception))

    async def test_xai_403_credits(self):
        rec = Recorder(json_response(XAI_NO_CREDITS, 403))
        c = self.make(rec, max_retries=2)
        with self.assertRaises(InsufficientCreditsError) as cm:
            await c.request("/x", {})
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(self.sleeps, [])

    async def test_openai_429_insufficient_quota_is_not_retried(self):
        rec = Recorder(json_response(OPENAI_QUOTA, 429, {"retry-after": "3"}))
        c = self.make(rec, max_retries=2)
        with self.assertRaises(InsufficientCreditsError) as cm:
            await c.request("/x", {})
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(self.sleeps, [])

    async def test_spend_cap_429_is_not_retried(self):
        rec = Recorder(json_response(ANTHROPIC_SPEND_CAP, 429, {"retry-after": "3"}))
        c = self.make(rec, max_retries=2)
        with self.assertRaises(InsufficientCreditsError) as cm:
            await c.request("/x", {})
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(self.sleeps, [])

    async def test_google_resource_exhausted_is_still_retried(self):
        rec = Recorder(
            json_response(GOOGLE_RESOURCE_EXHAUSTED, 429, {"retry-after": "3"}),
            json_response({"ok": True}),
        )
        c = self.make(rec, max_retries=2)
        self.assertEqual(await c.request("/x", {}), {"ok": True})
        self.assertEqual(len(rec.requests), 2)
        self.assertEqual(self.sleeps, [3.0])

    async def test_normal_429_is_still_retried(self):
        rec = Recorder(
            json_response(NORMAL_429, 429, {"retry-after": "3"}),
            json_response({"ok": True}),
        )
        c = self.make(rec, max_retries=2)
        self.assertEqual(await c.request("/x", {}), {"ok": True})
        self.assertEqual(len(rec.requests), 2)
        self.assertEqual(self.sleeps, [3.0])

    async def test_stream_open_raises_credits_error(self):
        rec = Recorder(json_response(OPENAI_QUOTA, 429))
        c = self.make(rec, max_retries=2)
        with self.assertRaises(InsufficientCreditsError):
            await c.request_stream("/x", {})
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(self.sleeps, [])


class ExportTest(unittest.TestCase):
    def test_exported_from_package(self):
        import llm_ai_api

        self.assertIs(llm_ai_api.InsufficientCreditsError, InsufficientCreditsError)
        self.assertIn("InsufficientCreditsError", llm_ai_api.__all__)
        self.assertTrue(issubclass(InsufficientCreditsError, APIStatusError))


if __name__ == "__main__":
    unittest.main()
