"""Assertions against migrated PostgreSQL, opt-in through python -m tests.integration.

No application imports at module scope: ordinary unit discovery cannot load a
production connection and accidentally reset it. All sessions/threads use the
guarded test engine; each test starts with isolated seeded data.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.orm import sessionmaker

from tests.integration.database import test_database_url


class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('YEFHAMAK_RUN_DB_TESTS') != '1':
            raise unittest.SkipTest('Use python -m tests.integration with TEST_DATABASE_URL for database checks')
        url = test_database_url(os.environ.get('TEST_DATABASE_URL'))
        from app.core.config import settings
        if test_database_url(settings.database_url) != url or test_database_url(settings.direct_url) != url:
            raise RuntimeError('Application settings do not match the explicitly selected test database')
        cls.engine = create_engine(url, connect_args={'prepare_threshold': None,
            'options': '-c statement_timeout=10000 -c lock_timeout=5000'})
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False, autoflush=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        from app.db.base import Base
        from app.demo import seed
        from app.demo.fixtures import make_conversation
        from app.models import DeliveryZone, Product, Seller, Variant
        # This code is only reachable after the loopback/name/opt-in checks above.
        tables = ', '.join(f'"{name}"' for name in Base.metadata.tables)
        with self.engine.begin() as connection:
            connection.execute(text(f'TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE'))
        with patch.object(seed, 'SessionLocal', self.sessions):
            seed.seed(quiet=True)
        self.db = self.sessions()
        self.addCleanup(self.db.close)
        self.seller = self.db.scalar(select(Seller).where(Seller.name == seed.DEMO_NAME))
        self.last = self.db.scalar(select(Variant).join(Product).where(Product.code == 'H-022', Variant.size == 'M'))
        self.classic = self.db.scalar(select(Variant).join(Product).where(Product.code == 'H-014', Variant.size == 'M'))
        self.zone = self.db.scalar(select(DeliveryZone).where(DeliveryZone.seller_id == self.seller.id, DeliveryZone.area == 'Cairo'))
        self.a = make_conversation(self.db, self.seller.id)
        self.b = make_conversation(self.db, self.seller.id)

    def count(self, model):
        return self.db.scalar(select(func.count()).select_from(model))

    def race(self, fn):
        barrier = Barrier(2, timeout=10)
        def attempt(index):
            with self.sessions() as db:
                barrier.wait()
                return fn(db, index)
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(attempt, [0, 1]))

    def other_seller(self):
        from app.demo.fixtures import make_conversation
        from app.models import Product, Seller, Variant
        seller = Seller(name='Other Store')
        self.db.add(seller)
        self.db.flush()
        product = Product(seller_id=seller.id, code='H-022', name='Oversized Hoodie', price=Decimal('9999'), nicknames=[])
        self.db.add(product)
        self.db.flush()
        variant = Variant(seller_id=seller.id, product_id=product.id, color='brown', size='M', stock=1, reserved=0)
        self.db.add(variant)
        self.db.commit()
        conversation = make_conversation(self.db, seller.id)
        return seller, variant, conversation

    def test_catalog_ambiguity_and_franco_search(self):
        from app.services.catalog import search_products
        result = search_products(self.db, self.seller.id, 'عندكم الهودي البني مقاس M؟')
        self.assertEqual({p['code'] for p in result['matches']}, {'H-014', 'H-022'})
        self.assertTrue(result['needs_clarification'])
        self.assertEqual([p['code'] for p in search_products(self.db, self.seller.id, 'hodi aswad')['matches']], ['H-031'])

    def test_two_customers_compete_for_last_item(self):
        from app.models import Reservation, ReservationStatus
        from app.services.inventory import release_reservation, reserve_item
        for run in range(3):
            with self.subTest(race=run):
                winners = self.race(lambda db, i: reserve_item(db, self.seller.id, self.last.id, [self.a.id, self.b.id][i]) is not None)
                self.assertEqual(sum(winners), 1)
                self.db.refresh(self.last)
                self.assertEqual(self.last.reserved, 1)
                held = self.db.scalars(select(Reservation).where(Reservation.status == ReservationStatus.ACTIVE)).all()
                self.assertEqual(len(held), 1)
                self.assertTrue(release_reservation(self.db, held[0].id))

    def test_concurrent_release_is_idempotent(self):
        from app.services.inventory import release_reservation, reserve_item
        hold = reserve_item(self.db, self.seller.id, self.last.id, self.a.id)
        released = self.race(lambda db, _: release_reservation(db, hold.id))
        self.assertEqual(sum(released), 1)
        self.assertFalse(release_reservation(self.db, hold.id))
        self.db.refresh(self.last)
        self.assertEqual(self.last.reserved, 0)

    def test_expiry_only_releases_expired_holds_once(self):
        from app.models import ReservationStatus
        from app.services.inventory import expire_reservations, reserve_item
        expired = reserve_item(self.db, self.seller.id, self.last.id, self.a.id, minutes=-1)
        active = reserve_item(self.db, self.seller.id, self.classic.id, self.b.id)
        self.assertEqual(expire_reservations(self.db), 1)
        self.assertEqual(expire_reservations(self.db), 0)
        self.db.refresh(expired)
        self.db.refresh(active)
        self.db.refresh(self.last)
        self.db.refresh(self.classic)
        self.assertEqual(expired.status, ReservationStatus.EXPIRED)
        self.assertEqual(active.status, ReservationStatus.ACTIVE)
        self.assertEqual(self.last.reserved, 0)
        self.assertEqual(self.classic.reserved, 1)

    def test_invalid_quantity_never_changes_stock(self):
        from app.models import Reservation
        from app.services.inventory import reserve_item
        for quantity in [0, -1, 2]:
            with self.subTest(quantity=quantity):
                self.assertIsNone(reserve_item(self.db, self.seller.id, self.last.id, self.a.id, quantity=quantity))
        self.db.refresh(self.last)
        self.assertEqual(self.last.reserved, 0)
        self.assertEqual(self.count(Reservation), 0)

    def test_cannot_reserve_another_sellers_variant(self):
        from app.services.inventory import available_quantity, reserve_item
        other, variant, _ = self.other_seller()
        self.assertEqual(available_quantity(self.db, self.seller.id, variant.id), 0)
        self.assertIsNone(reserve_item(self.db, self.seller.id, variant.id, self.a.id))
        self.db.refresh(variant)
        self.assertEqual(variant.reserved, 0)

    def test_cannot_attach_reservation_to_another_sellers_conversation(self):
        from app.models import Reservation
        from app.services.inventory import reserve_item
        _, _, conversation = self.other_seller()
        self.assertIsNone(reserve_item(self.db, self.seller.id, self.last.id, conversation.id))
        self.db.refresh(self.last)
        self.assertEqual(self.last.reserved, 0)
        self.assertEqual(self.count(Reservation), 0)

    def test_catalog_and_conversation_queries_are_seller_isolated(self):
        from app.services.catalog import search_products
        from app.services.workspace import WorkspaceNotFound, get_conversation
        other, _, conversation = self.other_seller()
        result = search_products(self.db, self.seller.id, 'هودي بني')
        self.assertNotIn(9999, [p['price'] for p in result['matches']])
        with self.assertRaises(WorkspaceNotFound):
            get_conversation(self.db, self.seller.id, conversation.id)
        with self.assertRaises(WorkspaceNotFound):
            get_conversation(self.db, other.id, self.a.id)

    def test_orders_are_seller_isolated_and_search_escapes_wildcards(self):
        from app.models import Order
        from app.services.workspace import WorkspaceNotFound, get_order, list_orders
        other, _, conversation = self.other_seller()
        orders = [Order(seller_id=seller.id, customer_id=conv.customer_id, conversation_id=conv.id,
                        customer_name=name, phone='01000000000', address='Sample address', total=Decimal('10'))
                  for seller, conv, name in [(self.seller, self.a, 'Alice'), (other, conversation, 'Other')]]
        self.db.add_all(orders)
        self.db.commit()
        rows, total = list_orders(self.db, self.seller.id, None, None, 25, 0)
        self.assertEqual(total, 1)
        self.assertEqual([row.id for row in rows], [orders[0].id])
        self.assertEqual(list_orders(self.db, self.seller.id, None, '%', 25, 0)[1], 0)
        with self.assertRaises(WorkspaceNotFound):
            get_order(self.db, self.seller.id, orders[1].id)

    def test_multi_item_order_confirmation_and_duplicate_protection(self):
        from app.agent.tools import run_tool
        from app.models import Message, MessageDirection, Order, OrderItem, Reservation, ReservationStatus
        from app.services.inventory import expire_reservations, reserve_item
        from app.services.workspace import get_order
        reserve_item(self.db, self.seller.id, self.classic.id, self.a.id, quantity=2)
        reserve_item(self.db, self.seller.id, self.last.id, self.a.id)
        details = dict(customer_name='Integration Demo', phone='01000000000', address='12 Sample Street', area='Cairo')
        def call(confirmed):
            return run_tool(self.db, self.seller, self.a, 'create_order', json.dumps({**details, 'confirmed': confirmed}))
        self.assertEqual(call(True)['reason'], 'details_not_previewed')
        self.assertEqual(call(False)['total_egp'], 1470)
        self.assertEqual(call(True)['reason'], 'customer_has_not_confirmed_yet')
        self.db.add(Message(conversation_id=self.a.id, direction=MessageDirection.IN, body='ايوه اكد'))
        self.db.commit()
        self.assertTrue(call(True)['ok'])
        self.assertTrue(call(True)['already_created'])
        self.assertEqual(self.count(Order), 1)
        self.assertEqual(self.count(OrderItem), 2)
        order = self.db.scalar(select(Order))
        saved, items = get_order(self.db, self.seller.id, order.id)
        self.assertEqual(saved.total, Decimal('1470.00'))
        self.assertEqual(len(items), 2)
        self.assertEqual({row[0].quantity for row in items}, {1, 2})
        # Even past their deadline, confirmed holds must not be released as expired.
        self.db.execute(update(Reservation).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        self.db.commit()
        self.assertEqual(expire_reservations(self.db), 0)
        self.assertEqual(set(self.db.scalars(select(Reservation.status))), {ReservationStatus.CONFIRMED})

    def test_expired_hold_rolls_back_order_and_items(self):
        from app.models import Order, OrderItem, Reservation
        from app.services.inventory import reserve_item
        from app.services.orders import create_order, order_summary
        hold = reserve_item(self.db, self.seller.id, self.classic.id, self.a.id)
        summary = order_summary(self.db, self.a, self.zone)
        self.db.execute(update(Reservation).where(Reservation.id == hold.id).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        self.db.commit()
        order = create_order(self.db, self.seller, self.a, {'name': 'Demo', 'phone': '01000000000',
                                                         'address': 'Sample address', 'area': 'Cairo'}, summary)
        self.assertIsNone(order)
        self.assertEqual(self.count(Order), 0)
        self.assertEqual(self.count(OrderItem), 0)

    def test_request_replay_survives_new_session_and_rejects_changed_text(self):
        from app.models import ChatRequest
        from app.services.chat_requests import RequestConflict, claim, finish
        request_id = uuid4()
        self.assertIsNone(claim(self.db, request_id, self.a.id, 'sample'))
        finish(self.db, request_id, {'reply': 'persisted response'})
        with self.sessions() as other:
            self.assertEqual(claim(other, request_id, self.a.id, 'sample'), {'reply': 'persisted response'})
            with self.assertRaisesRegex(RequestConflict, 'request_id_reused'):
                claim(other, request_id, self.a.id, 'different')
        self.assertEqual(self.count(ChatRequest), 1)

    def make_review_order(self):
        from app.services.inventory import reserve_item
        from app.services.orders import create_order, order_summary
        reserve_item(self.db, self.seller.id, self.classic.id, self.a.id, quantity=2)
        reserve_item(self.db, self.seller.id, self.last.id, self.a.id)
        return create_order(self.db, self.seller, self.a,
                            dict(name='Review Test', phone='01000000000', address='Sample address', area='Cairo'),
                            order_summary(self.db, self.a, self.zone))

    def inventory_snapshot(self):
        from app.models import Variant
        self.db.expire_all()
        return {row.id: (row.stock, row.reserved) for row in self.db.scalars(select(Variant))}

    def test_seller_confirm_consumes_multi_item_stock_once(self):
        from app.models import OrderItem, OrderStatus, Reservation, ReservationStatus
        from app.services.seller_orders import review_order
        baseline = self.inventory_snapshot()
        order = self.make_review_order()
        for _ in range(2):
            self.assertEqual(review_order(self.db, self.seller.id, order.id, OrderStatus.CONFIRMED).status, OrderStatus.CONFIRMED)
        expected = dict(baseline)
        expected[self.classic.id] = (baseline[self.classic.id][0] - 2, 0)
        expected[self.last.id] = (baseline[self.last.id][0] - 1, 0)
        self.assertEqual(self.inventory_snapshot(), expected)
        self.assertEqual(order.total, Decimal('1470.00'))
        self.assertEqual(self.count(OrderItem), 2)
        self.assertEqual(set(self.db.scalars(select(Reservation.status))), {ReservationStatus.CONFIRMED})

    def test_seller_cancel_pending_releases_all_holds_once(self):
        from app.models import OrderStatus, Reservation, ReservationStatus
        from app.services.inventory import expire_reservations, reserve_item
        from app.services.seller_orders import review_order
        baseline = self.inventory_snapshot()
        order = self.make_review_order()
        for _ in range(2):
            self.assertEqual(review_order(self.db, self.seller.id, order.id, OrderStatus.CANCELLED).status, OrderStatus.CANCELLED)
        self.assertEqual(self.inventory_snapshot(), baseline)
        self.assertEqual(set(self.db.scalars(select(Reservation.status))), {ReservationStatus.RELEASED})
        self.assertEqual(expire_reservations(self.db), 0)
        self.assertIsNotNone(reserve_item(self.db, self.seller.id, self.last.id, self.b.id))

    def test_seller_cancel_confirmed_restocks_once_preserving_other_holds(self):
        from app.models import OrderStatus
        from app.services.inventory import reserve_item
        from app.services.seller_orders import review_order
        baseline = self.inventory_snapshot()
        order = self.make_review_order()
        reserve_item(self.db, self.seller.id, self.classic.id, self.b.id)
        review_order(self.db, self.seller.id, order.id, OrderStatus.CONFIRMED)
        for _ in range(2):
            review_order(self.db, self.seller.id, order.id, OrderStatus.CANCELLED)
        expected = dict(baseline)
        expected[self.classic.id] = (baseline[self.classic.id][0], 1)
        self.assertEqual(self.inventory_snapshot(), expected)

    def test_cancelled_order_cannot_be_confirmed_or_reopened(self):
        from app.models import OrderStatus
        from app.services.seller_orders import OrderConflict, review_order
        order = self.make_review_order()
        review_order(self.db, self.seller.id, order.id, OrderStatus.CANCELLED)
        before = self.inventory_snapshot()
        for target in [OrderStatus.CONFIRMED, OrderStatus.PENDING]:
            with self.assertRaisesRegex(OrderConflict, 'invalid_order_transition'):
                review_order(self.db, self.seller.id, order.id, target)
        self.assertEqual(self.inventory_snapshot(), before)

    def test_review_rejects_other_seller_and_missing_orders(self):
        from app.models import OrderStatus
        from app.services.seller_orders import review_order
        from app.services.workspace import WorkspaceNotFound
        order = self.make_review_order()
        other, _, _ = self.other_seller()
        before = self.inventory_snapshot()
        for target in [OrderStatus.CONFIRMED, OrderStatus.CANCELLED]:
            for seller_id, order_id in [(other.id, order.id), (self.seller.id, uuid4())]:
                with self.assertRaises(WorkspaceNotFound):
                    review_order(self.db, seller_id, order_id, target)
        self.assertEqual(self.inventory_snapshot(), before)

    def test_concurrent_seller_confirmation_consumes_stock_once(self):
        from app.models import OrderStatus
        from app.services.seller_orders import review_order
        order = self.make_review_order()
        before = self.inventory_snapshot()
        self.assertEqual(self.race(lambda db, _: review_order(db, self.seller.id, order.id, OrderStatus.CONFIRMED).status),
                         [OrderStatus.CONFIRMED, OrderStatus.CONFIRMED])
        expected = dict(before)
        expected[self.classic.id] = (before[self.classic.id][0] - 2, 0)
        expected[self.last.id] = (before[self.last.id][0] - 1, 0)
        self.assertEqual(self.inventory_snapshot(), expected)

    def test_concurrent_seller_cancellation_returns_stock_once(self):
        from app.models import OrderStatus
        from app.services.seller_orders import review_order
        baseline = self.inventory_snapshot()
        order = self.make_review_order()
        review_order(self.db, self.seller.id, order.id, OrderStatus.CONFIRMED)
        self.assertEqual(self.race(lambda db, _: review_order(db, self.seller.id, order.id, OrderStatus.CANCELLED).status),
                         [OrderStatus.CANCELLED, OrderStatus.CANCELLED])
        self.assertEqual(self.inventory_snapshot(), baseline)

    def test_concurrent_confirm_and_cancel_leave_cancelled_stock_available(self):
        from app.models import Order, OrderStatus
        from app.services.seller_orders import OrderConflict, review_order
        baseline = self.inventory_snapshot()
        order = self.make_review_order()
        def attempt(db, index):
            try:
                return review_order(db, self.seller.id, order.id,
                                    [OrderStatus.CONFIRMED, OrderStatus.CANCELLED][index]).status
            except OrderConflict as error:
                return str(error)
        results = self.race(attempt)
        self.assertIn(results[0], [OrderStatus.CONFIRMED, 'invalid_order_transition'])
        self.assertEqual(results[1], OrderStatus.CANCELLED)
        self.assertEqual(self.inventory_snapshot(), baseline)
        self.assertEqual(self.db.get(Order, order.id).status, OrderStatus.CANCELLED)

    def test_review_inventory_failure_rolls_back_every_item_and_status(self):
        from app.models import Order, OrderStatus, Reservation, ReservationStatus, Variant
        from app.services.seller_orders import OrderConflict, review_order
        order = self.make_review_order()
        # Corrupt the last-updated variant to force failure after the first update.
        last_id = sorted([self.classic.id, self.last.id], key=str)[-1]
        self.db.execute(update(Variant).where(Variant.id == last_id).values(reserved=0))
        self.db.commit()
        before = self.inventory_snapshot()
        for target in [OrderStatus.CONFIRMED, OrderStatus.CANCELLED]:
            with self.assertRaisesRegex(OrderConflict, 'order_inventory_conflict'):
                review_order(self.db, self.seller.id, order.id, target)
            self.assertEqual(self.inventory_snapshot(), before)
            self.assertEqual(self.db.get(Order, order.id).status, OrderStatus.PENDING)
            self.assertEqual(set(self.db.scalars(select(Reservation.status))), {ReservationStatus.CONFIRMED})

    def test_review_refuses_missing_or_mismatched_linked_holds(self):
        from app.models import OrderStatus, Reservation
        from app.services.seller_orders import OrderConflict, review_order
        order = self.make_review_order()
        hold = self.db.scalar(select(Reservation).where(Reservation.order_id == order.id))
        hold.order_id = None
        self.db.commit()
        before = self.inventory_snapshot()
        with self.assertRaisesRegex(OrderConflict, 'order_inventory_conflict'):
            review_order(self.db, self.seller.id, order.id, OrderStatus.CONFIRMED)
        self.assertEqual(self.inventory_snapshot(), before)

    def test_review_http_auth_status_codes_and_persistence(self):
        from fastapi.testclient import TestClient
        from app.core.config import settings
        from app.db.session import get_db
        from app.main import app
        from app.models import Order, OrderStatus
        order = self.make_review_order()
        def test_session():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = test_session
        self.addCleanup(app.dependency_overrides.clear)
        with patch.object(settings, 'demo_api_key', 'database-review-test'), TestClient(app) as client:
            url = f'/api/demo/orders/{order.id}'
            headers = {'Authorization': 'Bearer database-review-test'}
            for action in ['confirm', 'cancel']:
                self.assertEqual(client.post(f'{url}/{action}').status_code, 401)
                self.assertEqual(client.post(f'{url}/{action}', headers={'Authorization': 'Bearer wrong'}).status_code, 401)
            response = client.post(f'{url}/confirm', headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'CONFIRMED')
            self.assertEqual(response.json()['total'], '1470.00')
            self.assertEqual(client.post(f'{url}/confirm', headers=headers).status_code, 200)
            self.assertEqual(client.post(f'{url}/cancel', headers=headers).json()['status'], 'CANCELLED')
            self.assertEqual(client.post(f'{url}/cancel', headers=headers).status_code, 200)
            self.assertEqual(client.post(f'{url}/confirm', headers=headers).status_code, 409)
            self.assertEqual(client.post(f'/api/demo/orders/{uuid4()}/cancel', headers=headers).status_code, 404)
            self.assertEqual(client.post('/api/demo/orders/not-a-uuid/confirm', headers=headers).status_code, 422)
        self.db.expire_all()
        self.assertEqual(self.db.get(Order, order.id).status, OrderStatus.CANCELLED)

    def test_concurrent_duplicate_request_is_claimed_once(self):
        from app.models import ChatRequest
        from app.services.chat_requests import RequestConflict, claim
        request_id = uuid4()
        def attempt(db, _):
            try:
                claim(db, request_id, self.a.id, 'sample')
                return 'claimed'
            except RequestConflict as error:
                return str(error)
        self.assertCountEqual(self.race(attempt), ['claimed', 'request_in_progress'])
        self.assertEqual(self.count(ChatRequest), 1)

    def test_concurrent_different_requests_share_one_inflight_slot(self):
        from app.models import ChatRequest
        from app.services.chat_requests import RequestConflict, claim
        def attempt(db, _):
            try:
                claim(db, uuid4(), self.a.id, 'sample')
                return 'claimed'
            except RequestConflict as error:
                return str(error)
        self.assertCountEqual(self.race(attempt), ['claimed', 'conversation_busy'])
        self.assertEqual(self.count(ChatRequest), 1)

    def test_knowledge_retrieval_is_seller_scoped_and_reimport_replaces(self):
        from app.services.knowledge import import_document, search_knowledge
        from app.models import KnowledgeChunk
        other, _, _ = self.other_seller()
        import_document(self.db, other.id, 'care.md', 'Private care', 'wash SECRET OTHER STORE')
        import_document(self.db, self.seller.id, 'care.md', 'Care guide', 'wash inside out with similar colours')
        result = search_knowledge(self.db, self.seller.id, 'ازاي اغسل الهودي؟')
        self.assertEqual(len(result['matches']), 1)
        self.assertNotIn('SECRET', str(result))
        self.assertEqual(result['matches'][0]['source'], 'care.md')
        import_document(self.db, self.seller.id, 'care.md', 'Updated care', 'wash gently and air dry')
        result = search_knowledge(self.db, self.seller.id, 'washing')
        self.assertEqual(len(result['matches']), 1)
        self.assertEqual(result['matches'][0]['text'], 'wash gently and air dry')
        self.assertEqual(self.count(KnowledgeChunk), 2)

    def test_knowledge_no_match_and_bounded_results(self):
        from app.services.knowledge import import_document, search_knowledge
        self.assertEqual(search_knowledge(self.db, self.seller.id, 'washing')['matches'], [])
        import_document(self.db, self.seller.id, 'guide.md', 'Guide', '\n\n'.join('wash passage ' + str(i) for i in range(8)))
        self.assertEqual(len(search_knowledge(self.db, self.seller.id, 'washing')['matches']), 3)
        self.assertEqual(search_knowledge(self.db, self.seller.id, 'quantum physics')['matches'], [])

    def test_knowledge_invalid_import_preserves_existing_document(self):
        from app.services.knowledge import import_document, search_knowledge
        import_document(self.db, self.seller.id, 'care.md', 'Care', 'wash gently')
        with self.assertRaises(ValueError):
            import_document(self.db, self.seller.id, 'care.md', 'Care', '')
        self.assertEqual(search_knowledge(self.db, self.seller.id, 'wash')['matches'][0]['text'], 'wash gently')

    def test_knowledge_agent_roundtrip_with_mock_model(self):
        from types import SimpleNamespace as NS
        from app.agent.loop import handle_message
        from app.services.knowledge import import_document
        from app.models import Message, MessageDirection
        import_document(self.db, self.seller.id, 'care.md', 'Care guide', 'Wash inside out. اغسل القطعة على ظهرها.')
        call = NS(id='care-call', function=NS(name='search_store_knowledge', arguments='{"query":"washing"}'))
        replies = [NS(usage=None, choices=[NS(message=NS(content='', tool_calls=[call]))]),
                   NS(usage=None, choices=[NS(message=NS(content='اغسل القطعة على ظهرها.', tool_calls=[]))])]
        trace = []
        with patch('app.agent.loop._chat', side_effect=replies):
            reply = handle_message(self.db, self.seller, self.a, 'ازاي اغسل القطعة؟', trace=trace)
        self.assertIn('care.md', reply)
        self.assertIn('Care guide', reply)
        self.assertEqual(trace[0]['name'], 'search_store_knowledge')
        saved = self.db.scalar(select(Message).where(Message.conversation_id == self.a.id, Message.direction == MessageDirection.OUT))
        self.assertEqual(saved.body, reply)
