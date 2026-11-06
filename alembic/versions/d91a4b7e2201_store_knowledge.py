"""Seller-scoped knowledge passages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "d91a4b7e2201"
down_revision = "c68a9e315f22"
branch_labels = depends_on = None

def upgrade():
    op.create_table("knowledge_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("seller_id", sa.Uuid(), sa.ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("terms", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("seller_id", "source", "position", name="uq_knowledge_source_position"))
    op.create_index("ix_knowledge_chunks_seller_id", "knowledge_chunks", ["seller_id"])
    op.create_index("ix_knowledge_terms", "knowledge_chunks", ["terms"], postgresql_using="gin")

def downgrade():
    op.drop_table("knowledge_chunks")
