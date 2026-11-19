"""Create the initial PostgreSQL storage schema."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_outbox_events_attempts_nonnegative")
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["created_at", "event_id"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_table(
        "processed_events",
        sa.Column("consumer_name", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "consumer_name", "event_id", name=op.f("pk_processed_events")
        ),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("asr_model", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('created', 'live', 'stopping', 'completed', 'interrupted', 'failed')",
            name=op.f("ck_sessions_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
    )
    op.create_table(
        "session_summaries",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_session_summaries_session_id_sessions"),
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_session_summaries")),
    )
    op.create_table(
        "utterances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence > 0", name=op.f("ck_utterances_positive_sequence")
        ),
        sa.CheckConstraint(
            "start_ms >= 0 AND end_ms > start_ms",
            name=op.f("ck_utterances_audio_window"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_utterances_session_id_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_utterances")),
        sa.UniqueConstraint("session_id", "id", name="uq_utterances_session_id"),
        sa.UniqueConstraint(
            "session_id", "sequence", name="uq_utterances_session_sequence"
        ),
    )
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("utterance_id", sa.Uuid(), nullable=False),
        sa.Column("context_version", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("faq_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(faq_ids) = 'array'",
            name=op.f("ck_recommendations_faq_ids_array"),
        ),
        sa.CheckConstraint(
            "context_version > 0",
            name=op.f("ck_recommendations_positive_context_version"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "utterance_id"],
            ["utterances.session_id", "utterances.id"],
            name=op.f("fk_recommendations_session_id_utterances"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
        sa.UniqueConstraint(
            "utterance_id",
            "context_version",
            name="uq_recommendations_utterance_context_version",
        ),
    )


def downgrade() -> None:
    op.drop_table("recommendations")
    op.drop_table("utterances")
    op.drop_table("session_summaries")
    op.drop_table("sessions")
    op.drop_table("processed_events")
    op.drop_index(
        "ix_outbox_events_pending",
        table_name="outbox_events",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.drop_table("outbox_events")
