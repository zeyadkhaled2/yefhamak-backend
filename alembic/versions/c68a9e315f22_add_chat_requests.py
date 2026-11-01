"""Durable web chat request deduplication.

Revision ID: c68a9e315f22
Revises: b2344f33dfe3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c68a9e315f22"
down_revision = "b2344f33dfe3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("chat_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("response", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_chat_requests_conversation_id", "chat_requests", ["conversation_id"])
    op.create_index("uq_chat_request_inflight", "chat_requests", ["conversation_id"], unique=True,
                    postgresql_where=sa.text("response IS NULL"))


def downgrade():
    op.drop_table("chat_requests")
