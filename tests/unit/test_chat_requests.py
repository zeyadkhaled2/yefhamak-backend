"""Real local SQLite persistence tests; no PostgreSQL or model access."""
import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import ChatRequest
from app.services.chat_requests import RequestConflict, claim, finish


class ChatRequestTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        # The isolated table is enough to verify claims and uniqueness. Other
        # domain tables remain PostgreSQL-specific and aren't exercised here.
        ChatRequest.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.conversation = uuid4()
        self.request = uuid4()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_completed_request_replays_after_new_session(self):
        self.assertIsNone(claim(self.db, self.request, self.conversation, 'hello'))
        finish(self.db, self.request, {'reply': 'saved result'})
        self.db.close()
        self.db = Session(self.engine)
        self.assertEqual(claim(self.db, self.request, self.conversation, 'hello'), {'reply': 'saved result'})

    def test_pending_request_is_not_executed_again(self):
        claim(self.db, self.request, self.conversation, 'hello')
        with self.assertRaisesRegex(RequestConflict, 'request_in_progress'):
            claim(self.db, self.request, self.conversation, 'hello')

    def test_id_reuse_with_different_text_or_conversation_is_rejected(self):
        claim(self.db, self.request, self.conversation, 'hello')
        finish(self.db, self.request, {'reply': 'ok'})
        for conversation, text in [(self.conversation, 'different'), (uuid4(), 'hello')]:
            with self.assertRaisesRegex(RequestConflict, 'request_id_reused'):
                claim(self.db, self.request, conversation, text)

    def test_only_one_pending_request_per_conversation(self):
        claim(self.db, self.request, self.conversation, 'first')
        with self.assertRaisesRegex(RequestConflict, 'conversation_busy'):
            claim(self.db, uuid4(), self.conversation, 'second')
        finish(self.db, self.request, {'reply': 'done'})
        self.assertIsNone(claim(self.db, uuid4(), self.conversation, 'second'))
