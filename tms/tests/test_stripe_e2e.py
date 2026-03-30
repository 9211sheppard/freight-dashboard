import importlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import stripe

import tms.stripe_payments as stripe_payments


class StripeE2ETests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.required = {
            "ENABLE_STRIPE": "true",
            "STRIPE_SECRET_KEY": os.environ.get("STRIPE_SECRET_KEY", ""),
            "STRIPE_WEBHOOK_SECRET": os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
            "BASE_URL": os.environ.get("BASE_URL", "https://example.test"),
        }
        if not self.required["STRIPE_SECRET_KEY"] or not self.required["STRIPE_WEBHOOK_SECRET"]:
            self.skipTest("Stripe test-mode secrets are not configured.")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_real_test_mode_checkout_and_webhook_round_trip(self):
        invoice_number = f"INV-E2E-{int(time.time())}"
        amount_cents = 2199
        description = "Stripe E2E invoice"

        with mock.patch.dict(os.environ, self.required, clear=False):
            importlib.reload(stripe_payments)
            stripe.api_key = self.required["STRIPE_SECRET_KEY"]

            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {"name": description},
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                success_url=f"{self.required['BASE_URL']}/tms/auto-invoices/{invoice_number}?paid=1",
                cancel_url=f"{self.required['BASE_URL']}/tms/auto-invoices/{invoice_number}",
                metadata={"invoice_number": invoice_number},
            )

            self.assertTrue(session.url.startswith("https://checkout.stripe.com/"))
            self.assertTrue(session.id.startswith("cs_test_"))
            self.assertEqual(session.metadata["invoice_number"], invoice_number)

            payload = json.dumps(
                {
                    "id": f"evt_{invoice_number}",
                    "object": "event",
                    "type": "checkout.session.completed",
                    "data": {
                        "object": {
                            "id": session.id,
                            "metadata": {
                                "invoice_number": invoice_number,
                            },
                        }
                    },
                }
            ).encode("utf-8")
            timestamp = int(time.time())
            signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
            signature = stripe.WebhookSignature._compute_signature(
                signed_payload, self.required["STRIPE_WEBHOOK_SECRET"]
            )
            header = f"t={timestamp},v1={signature}"

            result = stripe_payments.handle_stripe_webhook(payload, header)
            self.assertEqual(result["ok"], True)
            self.assertEqual(result["event"], "paid")
            self.assertEqual(result["invoice_number"], invoice_number)


if __name__ == "__main__":
    unittest.main()
