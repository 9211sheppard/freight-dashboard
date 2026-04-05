"""Stripe payment integration — customers pay invoices online."""
import os

STRIPE_ENABLED = os.environ.get('ENABLE_STRIPE', 'false').lower() == 'true'

def get_stripe():
    if not STRIPE_ENABLED:
        return None
    try:
        import stripe
        stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
        return stripe
    except ImportError:
        return None

def create_payment_link(invoice_number: str, amount_cents: int, description: str) -> str:
    """Create a Stripe payment link for an invoice. Returns URL or ''."""
    stripe = get_stripe()
    if not stripe:
        return ''
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': description},
                    'unit_amount': amount_cents,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=os.environ.get('BASE_URL','') + f'/tms/auto-invoices/{invoice_number}?paid=1',
            cancel_url=os.environ.get('BASE_URL','') + f'/tms/auto-invoices/{invoice_number}',
            metadata={'invoice_number': invoice_number}
        )
        return session.url
    except Exception:
        return ''

def handle_stripe_webhook(payload: bytes, sig_header: str) -> dict:
    """Process Stripe webhook events."""
    stripe = get_stripe()
    if not stripe:
        return {'ok': False}
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.environ.get('STRIPE_WEBHOOK_SECRET','')
        )
        if event['type'] == 'checkout.session.completed':
            inv_num = event['data']['object']['metadata'].get('invoice_number','')
            return {'ok': True, 'event': 'paid', 'invoice_number': inv_num}
        return {'ok': True, 'event': event['type']}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
