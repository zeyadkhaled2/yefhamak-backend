"""HTTP contracts and seller scoping with mocked persistence/model calls."""
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.routes import conversations
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models import Conversation, ConversationStatus, Message, MessageDirection, Order, OrderItem, OrderStatus, Product, Seller, Variant


class WorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.now = datetime.now(timezone.utc)
        self.seller = Seller(id=uuid4(), name='Demo Store')
        self.conversation = Conversation(id=uuid4(), seller_id=self.seller.id, customer_id=uuid4(),
                                         status=ConversationStatus.BOT, state={}, created_at=self.now)
        self.db.scalar.side_effect = lambda *args: self.seller
        self.db.scalars.return_value.all.return_value = []
        app.dependency_overrides[get_db] = lambda: self.db
        self.key_patch = patch.object(settings, 'demo_api_key', 'offline-test-key')
        self.live_patch = patch.object(settings, 'live_chat_enabled', False)
        self.key_patch.start()
        self.live_patch.start()
        self.client = TestClient(app, raise_server_exceptions=False)
        self.headers = {'Authorization': 'Bearer offline-test-key'}

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.live_patch.stop()
        self.key_patch.stop()

    @property
    def chat_url(self):
        return f'/api/demo/conversations/{self.conversation.id}/messages'

    def use_conversation(self):
        self.db.scalar.side_effect = [self.seller, self.conversation]

    def test_private_routes_require_key_before_querying_database(self):
        for url in ['/api/demo/orders', f'/api/demo/conversations/{uuid4()}']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 401)
                self.assertEqual(self.client.get(url, headers={'Authorization': 'Bearer wrong'}).status_code, 401)
        self.db.scalar.assert_not_called()

    def test_api_is_disabled_without_configured_key(self):
        with patch.object(settings, 'demo_api_key', None):
            response = self.client.get('/api/demo/orders', headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail'], 'demo_api_key_not_configured')
        self.db.scalar.assert_not_called()

    def test_missing_demo_store_is_actionable(self):
        self.db.scalar.side_effect = [None]
        response = self.client.post('/api/demo/conversations', headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail'], 'demo_store_not_seeded')

    def test_create_conversation_returns_only_public_fields(self):
        def generated_values(obj):
            obj.id = uuid4()
            obj.created_at = self.now
        self.db.add.side_effect = generated_values
        response = self.client.post('/api/demo/conversations', headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(set(response.json()), {'id', 'status', 'created_at'})
        self.assertEqual(response.json()['status'], 'BOT')
        customer, conversation = [call.args[0] for call in self.db.add.call_args_list]
        self.assertEqual(conversation.customer_id, customer.id)
        self.assertEqual(conversation.seller_id, self.seller.id)
        self.db.commit.assert_called_once()

    def test_create_failure_rolls_back(self):
        self.db.flush.side_effect = RuntimeError('simulated failure')
        response = self.client.post('/api/demo/conversations', headers=self.headers)
        self.assertEqual(response.status_code, 500)
        self.db.rollback.assert_called_once()

    def test_conversation_read_is_seller_scoped(self):
        self.use_conversation()
        response = self.client.get(f'/api/demo/conversations/{self.conversation.id}', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        query = self.db.scalar.call_args.args[0].compile()
        self.assertIn(self.seller.id, query.params.values())
        self.assertIn(self.conversation.id, query.params.values())
        self.assertNotIn('state', response.json())

    def test_unknown_or_other_seller_conversation_returns_404(self):
        self.db.scalar.side_effect = [self.seller, None]
        response = self.client.get(self.chat_url, headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.db.scalars.assert_not_called()

    def test_paginated_history_has_public_messages(self):
        self.use_conversation()
        self.db.scalars.return_value.all.return_value = [Message(id=uuid4(), conversation_id=self.conversation.id,
            body='hello', direction=MessageDirection.IN, created_at=self.now, model='private-model')]
        response = self.client.get(self.chat_url + '?limit=5&offset=10', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['items'][0]['body'], 'hello')
        self.assertNotIn('model', response.json()['items'][0])
        params = self.db.scalars.call_args.args[0].compile().params.values()
        self.assertIn(self.conversation.id, params)
        self.assertIn(5, params)
        self.assertIn(10, params)

    def test_live_send_is_disabled_without_using_model(self):
        with patch.object(conversations, 'handle_message') as handle:
            response = self.client.post(self.chat_url, json={'text': 'hello'}, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail'], 'live_chat_disabled')
        handle.assert_not_called()

    def test_send_calls_existing_agent_with_trimmed_text(self):
        self.use_conversation()
        with patch.object(settings, 'live_chat_enabled', True), patch.object(conversations, 'handle_message', return_value='أهلاً') as handle:
            response = self.client.post(self.chat_url, json={'text': ' hello '}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['reply'], 'أهلاً')
        self.assertEqual(response.json()['outcome'], 'reply')
        self.assertEqual(handle.call_args.args[3], 'hello')

    def test_invalid_messages_and_pagination_never_call_agent(self):
        with patch.object(settings, 'live_chat_enabled', True), patch.object(conversations, 'handle_message') as handle:
            for body in [{'text': ''}, {'text': '  '}, {'text': 'x' * 601}, {'text': 'hi', 'seller_id': str(uuid4())}]:
                with self.subTest(body_size=len(str(body))):
                    self.assertEqual(self.client.post(self.chat_url, json=body, headers=self.headers).status_code, 422)
            self.assertEqual(self.client.get(self.chat_url + '?limit=101', headers=self.headers).status_code, 422)
            self.assertEqual(self.client.get('/api/demo/orders?offset=-1', headers=self.headers).status_code, 422)
        handle.assert_not_called()

    def test_closed_conversation_rejects_sending(self):
        self.use_conversation()
        self.conversation.status = ConversationStatus.CLOSED
        with patch.object(settings, 'live_chat_enabled', True), patch.object(conversations, 'handle_message') as handle:
            self.assertEqual(self.client.post(self.chat_url, json={'text': 'hi'}, headers=self.headers).status_code, 409)
        handle.assert_not_called()

    def test_handoff_returns_silence_without_claiming_a_reply(self):
        self.use_conversation()
        self.conversation.status = ConversationStatus.HANDOFF
        with patch.object(settings, 'live_chat_enabled', True), patch.object(conversations, 'handle_message', return_value=''):
            response = self.client.post(self.chat_url, json={'text': 'hi'}, headers=self.headers)
        self.assertEqual(response.json()['outcome'], 'handoff')
        self.assertIsNone(response.json()['reply'])

    def test_quota_failure_has_machine_readable_outcome_without_raw_trace(self):
        self.use_conversation()
        def fail(*args, trace):
            trace.append({'type': 'error', 'error': 'RateLimitError: secret-provider-details'})
            return 'Temporary problem'
        with patch.object(settings, 'live_chat_enabled', True), patch.object(conversations, 'handle_message', side_effect=fail):
            response = self.client.post(self.chat_url, json={'text': 'hi'}, headers=self.headers)
        self.assertTrue(response.json()['rate_limited'])
        self.assertEqual(response.json()['outcome'], 'provider_error')
        self.assertNotIn('secret-provider', response.text)

    def test_overlapping_send_returns_conflict_and_releases_lock(self):
        lock = conversations.conversation_lock(self.conversation.id)
        lock.acquire()
        try:
            with patch.object(settings, 'live_chat_enabled', True), patch.object(conversations, 'handle_message') as handle:
                response = self.client.post(self.chat_url, json={'text': 'hi'}, headers=self.headers)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['detail'], 'conversation_busy')
            handle.assert_not_called()
        finally:
            lock.release()

    def test_orders_filter_and_count_are_seller_scoped(self):
        self.db.scalar.side_effect = [self.seller, 0]
        response = self.client.get('/api/demo/orders?status=PENDING&q=Ahmed&limit=5&offset=1', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'items': [], 'total': 0, 'limit': 5, 'offset': 1})
        for statement in [self.db.scalar.call_args.args[0], self.db.scalars.call_args.args[0]]:
            params = statement.compile().params.values()
            self.assertIn(self.seller.id, params)
            self.assertIn(OrderStatus.PENDING, params)
            self.assertIn('Ahmed', params)

    def test_unknown_order_returns_404(self):
        self.db.scalar.side_effect = [self.seller, None]
        response = self.client.get(f'/api/demo/orders/{uuid4()}', headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.db.execute.assert_not_called()

    def test_order_details_preserve_decimal_prices(self):
        order = Order(id=uuid4(), seller_id=self.seller.id, conversation_id=self.conversation.id,
                      status=OrderStatus.PENDING, customer_name='Demo', phone='01000000000', address='Sample address',
                      area='Cairo', delivery_fee=Decimal('50.00'), total=Decimal('500.00'), created_at=self.now)
        self.db.scalar.side_effect = [self.seller, order]
        self.db.execute.return_value.all.return_value = [(OrderItem(quantity=1, unit_price=Decimal('450.00')),
            Variant(color='brown', size='M'), Product(name='Demo hoodie', code='H-014'))]
        response = self.client.get(f'/api/demo/orders/{order.id}', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['total'], '500.00')
        self.assertEqual(response.json()['items'][0]['unit_price'], '450.00')
        self.assertIn(self.seller.id, self.db.execute.call_args.args[0].compile().params.values())

    def test_cors_allows_known_frontends_but_not_arbitrary_origins(self):
        headers = {'Origin': 'https://yefhamak.vercel.app', 'Access-Control-Request-Method': 'POST',
                   'Access-Control-Request-Headers': 'Authorization,Content-Type'}
        response = self.client.options('/api/demo/conversations', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], headers['Origin'])
        headers['Origin'] = 'https://untrusted.example'
        self.assertEqual(self.client.options('/api/demo/conversations', headers=headers).status_code, 400)
