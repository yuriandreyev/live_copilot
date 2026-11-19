import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData(
    naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
    }
)

sessions = sa.Table(
    "sessions",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("ended_at", sa.DateTime(timezone=True)),
    sa.Column("asr_model", sa.Text()),
    sa.Column("llm_model", sa.Text()),
    sa.CheckConstraint(
        "status IN ('created', 'live', 'stopping', 'completed', 'interrupted', 'failed')",
        name="status",
    ),
)

utterances = sa.Table(
    "utterances",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("session_id", sa.ForeignKey("sessions.id"), nullable=False),
    sa.Column("sequence", sa.BigInteger(), nullable=False),
    sa.Column("start_ms", sa.BigInteger(), nullable=False),
    sa.Column("end_ms", sa.BigInteger(), nullable=False),
    sa.Column("text", sa.Text(), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.UniqueConstraint(
        "session_id", "sequence", name="uq_utterances_session_sequence"
    ),
    sa.UniqueConstraint("session_id", "id", name="uq_utterances_session_id"),
    sa.CheckConstraint("sequence > 0", name="positive_sequence"),
    sa.CheckConstraint("start_ms >= 0 AND end_ms > start_ms", name="audio_window"),
)

recommendations = sa.Table(
    "recommendations",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("session_id", sa.Uuid(), nullable=False),
    sa.Column("utterance_id", sa.Uuid(), nullable=False),
    sa.Column("context_version", sa.BigInteger(), nullable=False),
    sa.Column("action", sa.Text(), nullable=False),
    sa.Column("rationale", sa.Text(), nullable=False),
    sa.Column("faq_ids", JSONB(), nullable=False),
    sa.Column("prompt_version", sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(
        ["session_id", "utterance_id"],
        ["utterances.session_id", "utterances.id"],
    ),
    sa.UniqueConstraint(
        "utterance_id",
        "context_version",
        name="uq_recommendations_utterance_context_version",
    ),
    sa.CheckConstraint("context_version > 0", name="positive_context_version"),
    sa.CheckConstraint("jsonb_typeof(faq_ids) = 'array'", name="faq_ids_array"),
)

outbox_events = sa.Table(
    "outbox_events",
    metadata,
    sa.Column("event_id", sa.Uuid(), primary_key=True),
    sa.Column("type", sa.Text(), nullable=False),
    sa.Column("payload", JSONB(), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("published_at", sa.DateTime(timezone=True)),
    sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    sa.CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
)
sa.Index(
    "ix_outbox_events_pending",
    outbox_events.c.created_at,
    outbox_events.c.event_id,
    postgresql_where=outbox_events.c.published_at.is_(None),
)

processed_events = sa.Table(
    "processed_events",
    metadata,
    sa.Column("consumer_name", sa.Text(), primary_key=True),
    sa.Column("event_id", sa.Uuid(), primary_key=True),
    sa.Column(
        "processed_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)

session_summaries = sa.Table(
    "session_summaries",
    metadata,
    sa.Column("session_id", sa.ForeignKey("sessions.id"), primary_key=True),
    sa.Column("summary", sa.Text(), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)
