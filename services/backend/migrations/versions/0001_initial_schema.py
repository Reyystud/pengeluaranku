"""initial schema (PRD 12.2) and category seed (taxonomy-1)

Revision ID: 0001
Revises:

Category ids are deterministic UUIDv5 values so every environment shares the same ids.
The seed is a frozen copy of ``ml.taxonomy`` taxonomy-1; a test guards against drift. Later
taxonomy versions need a new migration, never an edit of this one.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CATEGORY_SEED = [
    # (id, slug, name, transaction_type, is_model_label, sort_order)
    (
        "3a294de2-84fa-5ec8-820f-ba2ed1b09a75",
        "food_beverage",
        "Food & Beverage",
        "expense",
        True,
        1,
    ),
    ("684b4e78-ed5e-5df3-a76e-f3dd9d4fedb8", "groceries", "Groceries", "expense", True, 2),
    (
        "9f90b7a2-d410-5478-b7ef-e2b506a92814",
        "transportation",
        "Transportation",
        "expense",
        True,
        3,
    ),
    ("d472833c-00d4-5094-97e6-956d3e0d164c", "utilities", "Utilities & Bills", "expense", True, 4),
    ("f14b8149-5443-5dd2-950d-4b0bbd72de7a", "housing", "Housing", "expense", True, 5),
    ("34f05db6-c67c-5502-82c4-1a2a55c06409", "shopping", "Shopping", "expense", True, 6),
    ("c931f544-e30a-5f11-96e3-627727858695", "entertainment", "Entertainment", "expense", True, 7),
    ("0344ee15-13a3-531a-a635-c22b24397423", "health", "Health", "expense", True, 8),
    ("f270b675-8e9e-596d-8062-f6a9738b5dac", "education", "Education", "expense", True, 9),
    ("2ecca2a5-edcd-52d4-adde-89189d14b92b", "personal_care", "Personal Care", "expense", True, 10),
    (
        "7b548db0-5a1f-5857-8e8c-bca33a91b6e2",
        "gifts_donations",
        "Gifts & Donations",
        "expense",
        True,
        11,
    ),
    ("0c7c3875-d90f-5ee9-bde8-278edf6b6400", "fees_charges", "Fees & Charges", "expense", True, 12),
    ("2f75bb42-0100-58b5-b35a-9488e4f90b50", "other_expense", "Other Expense", "expense", True, 13),
    ("e017af10-890a-5dbe-88c6-66e19901ee7a", "allowance", "Allowance", "income", True, 14),
    ("2f8700cb-9a72-59e6-bc9b-ccb8046866c4", "salary", "Salary", "income", True, 15),
    (
        "f8453aba-0dd0-5259-8643-86467de574b4",
        "freelance",
        "Freelance & Side Income",
        "income",
        True,
        16,
    ),
    ("6497771a-8fab-5515-a7f3-6db19ed2844f", "refund", "Refund & Cashback", "income", True, 17),
    ("a8edb4ca-8559-5c00-a576-dbc1b4f2eb25", "other_income", "Other Income", "income", True, 18),
    ("b7389f73-0382-5e32-a071-5a839761a82b", "transfer", "Transfer & Top-up", "transfer", True, 19),
    ("29efe9d5-4a27-56d6-843a-d1b997c74ae8", "uncategorized", "Uncategorized", "any", False, 20),
]


def _seed_categories() -> None:
    categories = sa.table(
        "categories",
        sa.column("id", sa.Uuid()),
        sa.column("slug", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("transaction_type", sa.Text()),
        sa.column("is_model_label", sa.Boolean()),
        sa.column("sort_order", sa.SmallInteger()),
    )
    op.bulk_insert(
        categories,
        [
            {
                "id": uuid.UUID(row[0]),
                "slug": row[1],
                "name": row[2],
                "transaction_type": row[3],
                "is_model_label": row[4],
                "sort_order": row[5],
            }
            for row in CATEGORY_SEED
        ],
    )


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("transaction_type", sa.Text(), nullable=False),
        sa.Column("is_model_label", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "transaction_type IN ('income', 'expense', 'transfer', 'any')",
            name=op.f("ck_categories_transaction_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("slug", name=op.f("uq_categories_slug")),
    )
    op.create_table(
        "deletion_requests",
        sa.Column("user_pseudo_id", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_pseudo_id", name=op.f("pk_deletion_requests")),
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_name", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name=op.f("ck_job_runs_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_events",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.Text(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "consumer", name=op.f("pk_processed_events")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), server_default="IDR", nullable=False),
        sa.Column("timezone", sa.Text(), server_default="Asia/Jakarta", nullable=False),
        sa.Column("locale", sa.Text(), server_default="en", nullable=False),
        sa.Column("budget_period_start_day", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("pending_period_start_day", sa.SmallInteger(), nullable=True),
        sa.Column("pending_period_start_effective", sa.Date(), nullable=True),
        sa.Column(
            "opening_balance", sa.Numeric(precision=15, scale=2), server_default="0", nullable=False
        ),
        sa.Column(
            "training_consent", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("currency = 'IDR'", name=op.f("ck_users_currency_idr")),
        sa.CheckConstraint("locale IN ('en', 'id')", name=op.f("ck_users_locale")),
        sa.CheckConstraint(
            "budget_period_start_day BETWEEN 1 AND 28", name=op.f("ck_users_period_start_day")
        ),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 60", name=op.f("ck_users_display_name_length")
        ),
        sa.CheckConstraint(
            "pending_period_start_day BETWEEN 1 AND 28",
            name=op.f("ck_users_pending_period_start_day"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index("ux_users_email", "users", [sa.literal_column("lower(email)")], unique=True)
    op.create_table(
        "anomaly_suppressions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_key", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_anomaly_suppressions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "merchant_key", name=op.f("pk_anomaly_suppressions")),
    )
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("limit_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column(
            "alert_thresholds",
            sa.ARRAY(sa.SmallInteger()),
            server_default=sa.text("'{80,100}'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("limit_amount > 0", name=op.f("ck_budgets_limit_positive")),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name=op.f("fk_budgets_category_id_categories")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_budgets_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budgets")),
    )
    op.create_index(
        "ux_budget_user_cat",
        "budgets",
        [
            "user_id",
            sa.literal_column(
                "COALESCE(category_id, '00000000-0000-0000-0000-000000000000'::uuid)"
            ),
        ],
        unique=True,
    )
    op.create_table(
        "forecast_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Date(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("forecast_day", sa.SmallInteger(), nullable=False),
        sa.Column("predicted_total", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("baseline_prediction", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("actual_total", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_forecast_outcomes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_outcomes")),
    )
    op.create_index(
        "ux_fc_outcome",
        "forecast_outcomes",
        [
            "user_id",
            "period_id",
            sa.literal_column(
                "COALESCE(category_id, '00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            "forecast_day",
        ],
        unique=True,
    )
    op.create_table(
        "forecasts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Date(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("spent_to_date", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("predicted_total", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("interval_low", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("interval_high", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("baseline_prediction", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column(
            "expected_recurring_remaining",
            sa.Numeric(precision=15, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("history_level", sa.Text(), nullable=False),
        sa.Column(
            "daily_curve",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "history_level IN ('personal', 'limited')", name=op.f("ck_forecasts_history_level")
        ),
        sa.CheckConstraint(
            "method IN ('run_rate', 'seasonal_naive', 'model')", name=op.f("ck_forecasts_method")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name=op.f("fk_forecasts_category_id_categories")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_forecasts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecasts")),
    )
    op.create_index(
        "ix_fc_lookup",
        "forecasts",
        ["user_id", "period_id", "category_id", sa.literal_column("as_of DESC")],
        unique=False,
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(key) BETWEEN 8 AND 128", name=op.f("ck_idempotency_keys_key_length")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_idempotency_keys_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name=op.f("pk_idempotency_keys")),
    )
    op.create_table(
        "insights",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("period_id", sa.Date(), nullable=False),
        sa.Column("subject_key", sa.Text(), server_default="", nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("priority", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("message_key", sa.Text(), nullable=False),
        sa.Column("message_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "severity IN ('info', 'positive', 'warning')", name=op.f("ck_insights_severity")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_insights_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_insights")),
        sa.UniqueConstraint(
            "user_id",
            "rule_id",
            "period_id",
            "subject_key",
            name="uq_insights_user_rule_period_subject",
        ),
    )
    op.create_table(
        "merchant_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_key", sa.Text(), nullable=False),
        sa.Column("merchant_display", sa.Text(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("times_applied", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "merchant_key <> ''", name=op.f("ck_merchant_rules_merchant_key_not_empty")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_merchant_rules_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_merchant_rules_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_merchant_rules")),
        sa.UniqueConstraint(
            "user_id", "merchant_key", name="uq_merchant_rules_user_id_merchant_key"
        ),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('budget_threshold', 'anomaly_alert', 'import_completed', 'recurring_due_soon', 'review_queue')",
            name=op.f("ck_notifications_type"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
    )
    op.create_index(
        "ix_notif_unread",
        "notifications",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_table(
        "recurring_series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_key", sa.Text(), nullable=False),
        sa.Column("merchant_display", sa.Text(), nullable=False),
        sa.Column("transaction_type", sa.Text(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("frequency", sa.Text(), nullable=False),
        sa.Column("median_interval_days", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("expected_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("amount_cv", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("last_date", sa.Date(), nullable=False),
        sa.Column("next_expected_date", sa.Date(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("user_expected_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "frequency IN ('weekly', 'biweekly', 'monthly', 'quarterly', 'yearly')",
            name=op.f("ck_recurring_series_frequency"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'ended', 'user_confirmed', 'user_rejected')",
            name=op.f("ck_recurring_series_status"),
        ),
        sa.CheckConstraint(
            "transaction_type IN ('income', 'expense')",
            name=op.f("ck_recurring_series_transaction_type"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_recurring_series_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_recurring_series_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recurring_series")),
        sa.UniqueConstraint(
            "user_id",
            "merchant_key",
            "transaction_type",
            name="uq_recurring_series_user_merchant_type",
        ),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("replaced_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent_hash", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index("ix_refresh_family", "refresh_tokens", ["family_id"], unique=False)
    op.create_index("ix_refresh_user", "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "transaction_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("valid_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("staged_rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("committed_count", sa.Integer(), nullable=True),
        sa.Column("commit_mode", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "commit_mode IN ('strict', 'skip_invalid')",
            name=op.f("ck_transaction_imports_commit_mode"),
        ),
        sa.CheckConstraint(
            "status IN ('previewed', 'committed', 'failed', 'expired')",
            name=op.f("ck_transaction_imports_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_transaction_imports_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_imports")),
    )
    op.create_index(
        "ix_imports_sha", "transaction_imports", ["user_id", "file_sha256"], unique=False
    )
    op.create_index(
        "ix_imports_user",
        "transaction_imports",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "user_segments",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.Text(), nullable=False),
        sa.Column("traits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_segments_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_segments")),
    )
    op.create_table(
        "budget_period_snapshots",
        sa.Column("budget_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Date(), nullable=False),
        sa.Column("limit_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("spent", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("utilization", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["budget_id"],
            ["budgets.id"],
            name=op.f("fk_budget_period_snapshots_budget_id_budgets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_budget_period_snapshots_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("budget_id", "period_id", name=op.f("pk_budget_period_snapshots")),
    )
    op.create_index(
        "ix_bps_user_period", "budget_period_snapshots", ["user_id", "period_id"], unique=False
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_type", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("merchant", sa.Text(), nullable=True),
        sa.Column("merchant_key", sa.Text(), server_default="", nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("has_time", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("payment_method", sa.Text(), server_default="other", nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("category_status", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=True),
        sa.Column("possible_duplicate_of", sa.Uuid(), nullable=True),
        sa.Column(
            "duplicate_dismissed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category_status IN ('auto', 'suggested', 'needs_review', 'rule', 'user_set', 'user_confirmed')",
            name=op.f("ck_transactions_category_status"),
        ),
        sa.CheckConstraint(
            "payment_method IN ('cash', 'bank_transfer', 'debit_card', 'credit_card', 'e_wallet', 'qris', 'other')",
            name=op.f("ck_transactions_payment_method"),
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'csv', 'demo_seed')", name=op.f("ck_transactions_source")
        ),
        sa.CheckConstraint(
            "transaction_type IN ('income', 'expense', 'transfer')",
            name=op.f("ck_transactions_transaction_type"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_transactions_amount_positive")),
        sa.CheckConstraint(
            "char_length(description) BETWEEN 1 AND 200",
            name=op.f("ck_transactions_description_length"),
        ),
        sa.CheckConstraint(
            "char_length(merchant) <= 100", name=op.f("ck_transactions_merchant_length")
        ),
        sa.CheckConstraint("char_length(notes) <= 500", name=op.f("ck_transactions_notes_length")),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name=op.f("fk_transactions_category_id_categories")
        ),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["transaction_imports.id"],
            name=op.f("fk_transactions_import_id_transaction_imports"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["possible_duplicate_of"],
            ["transactions.id"],
            name=op.f("fk_transactions_possible_duplicate_of_transactions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_transactions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index(
        "ix_tx_dup_lookup",
        "transactions",
        ["user_id", "transaction_type", "amount", "merchant_key", "transaction_date"],
        unique=False,
    )
    op.create_index(
        "ix_tx_user_cat_date",
        "transactions",
        ["user_id", "category_id", sa.literal_column("transaction_date DESC")],
        unique=False,
    )
    op.create_index(
        "ix_tx_user_date",
        "transactions",
        ["user_id", sa.literal_column("transaction_date DESC"), sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_tx_user_merchant",
        "transactions",
        ["user_id", "merchant_key", sa.literal_column("transaction_date DESC")],
        unique=False,
    )
    op.create_index(
        "ix_tx_user_status",
        "transactions",
        ["user_id", "category_status"],
        unique=False,
        postgresql_where=sa.text("category_status IN ('suggested','needs_review')"),
    )
    op.create_table(
        "anomalies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("anomaly_type", sa.Text(), nullable=False),
        sa.Column("anomaly_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("is_alert", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("history_level", sa.Text(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("feature_version", sa.Text(), nullable=False),
        sa.Column("period_id", sa.Date(), nullable=False),
        sa.Column("transaction_version", sa.Integer(), nullable=True),
        sa.Column("feedback_reason", sa.Text(), nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "anomaly_type IN ('amount_spike', 'frequency_burst', 'new_merchant_high_value', 'category_surge', 'amount_low')",
            name=op.f("ck_anomalies_anomaly_type"),
        ),
        sa.CheckConstraint(
            "feedback_reason IN ('expected_purchase', 'wrong_amount', 'not_mine', 'other')",
            name=op.f("ck_anomalies_feedback_reason"),
        ),
        sa.CheckConstraint(
            "history_level IN ('personal', 'limited')", name=op.f("ck_anomalies_history_level")
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high')", name=op.f("ck_anomalies_severity")
        ),
        sa.CheckConstraint(
            "status IN ('open', 'confirmed', 'dismissed', 'historical', 'superseded')",
            name=op.f("ck_anomalies_status"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name=op.f("fk_anomalies_category_id_categories")
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_anomalies_transaction_id_transactions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_anomalies_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_anomalies")),
    )
    op.create_index(
        "ix_anom_alerts",
        "anomalies",
        ["user_id", "period_id"],
        unique=False,
        postgresql_where=sa.text("is_alert"),
    )
    op.create_index(
        "ix_anom_user", "anomalies", ["user_id", sa.literal_column("created_at DESC")], unique=False
    )
    op.create_index(
        "ux_anom_surge_open",
        "anomalies",
        ["user_id", "category_id"],
        unique=True,
        postgresql_where=sa.text("anomaly_type = 'category_surge' AND status = 'open'"),
    )
    op.create_index(
        "ux_anom_tx_type",
        "anomalies",
        ["transaction_id", "anomaly_type"],
        unique=True,
        postgresql_where=sa.text("transaction_id IS NOT NULL AND status <> 'superseded'"),
    )
    op.create_table(
        "category_predictions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("predicted_category_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column(
            "alternatives",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("feature_version", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("ml_error", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('auto_apply', 'suggest', 'needs_review')",
            name=op.f("ck_category_predictions_decision"),
        ),
        sa.CheckConstraint(
            "source IN ('model', 'user_rule', 'fallback')",
            name=op.f("ck_category_predictions_source"),
        ),
        sa.ForeignKeyConstraint(
            ["predicted_category_id"],
            ["categories.id"],
            name=op.f("fk_category_predictions_predicted_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_category_predictions_transaction_id_transactions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_category_predictions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_predictions")),
    )
    op.create_index(
        "ix_pred_tx",
        "category_predictions",
        ["transaction_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_pred_user",
        "category_predictions",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "recurring_series_transactions",
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["recurring_series.id"],
            name=op.f("fk_recurring_series_transactions_series_id_recurring_series"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_recurring_series_transactions_transaction_id_transactions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "series_id", "transaction_id", name=op.f("pk_recurring_series_transactions")
        ),
    )
    op.create_table(
        "category_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("prediction_id", sa.Uuid(), nullable=True),
        sa.Column("previous_category_id", sa.Uuid(), nullable=False),
        sa.Column("new_category_id", sa.Uuid(), nullable=False),
        sa.Column("previous_status", sa.Text(), nullable=False),
        sa.Column("feedback_type", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("merchant_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "feedback_type IN ('correction', 'confirmation', 'quick_pick')",
            name=op.f("ck_category_feedback_feedback_type"),
        ),
        sa.ForeignKeyConstraint(
            ["new_category_id"],
            ["categories.id"],
            name=op.f("fk_category_feedback_new_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["category_predictions.id"],
            name=op.f("fk_category_feedback_prediction_id_category_predictions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["previous_category_id"],
            ["categories.id"],
            name=op.f("fk_category_feedback_previous_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_category_feedback_transaction_id_transactions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_category_feedback_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_feedback")),
    )
    op.create_index(
        "ix_cfb_tx",
        "category_feedback",
        ["transaction_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_cfb_user",
        "category_feedback",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    _seed_categories()


def downgrade() -> None:
    op.drop_index("ix_cfb_user", table_name="category_feedback")
    op.drop_index("ix_cfb_tx", table_name="category_feedback")
    op.drop_table("category_feedback")
    op.drop_table("recurring_series_transactions")
    op.drop_index("ix_pred_user", table_name="category_predictions")
    op.drop_index("ix_pred_tx", table_name="category_predictions")
    op.drop_table("category_predictions")
    op.drop_index(
        "ux_anom_tx_type",
        table_name="anomalies",
        postgresql_where=sa.text("transaction_id IS NOT NULL AND status <> 'superseded'"),
    )
    op.drop_index(
        "ux_anom_surge_open",
        table_name="anomalies",
        postgresql_where=sa.text("anomaly_type = 'category_surge' AND status = 'open'"),
    )
    op.drop_index("ix_anom_user", table_name="anomalies")
    op.drop_index("ix_anom_alerts", table_name="anomalies", postgresql_where=sa.text("is_alert"))
    op.drop_table("anomalies")
    op.drop_index(
        "ix_tx_user_status",
        table_name="transactions",
        postgresql_where=sa.text("category_status IN ('suggested','needs_review')"),
    )
    op.drop_index("ix_tx_user_merchant", table_name="transactions")
    op.drop_index("ix_tx_user_date", table_name="transactions")
    op.drop_index("ix_tx_user_cat_date", table_name="transactions")
    op.drop_index("ix_tx_dup_lookup", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_bps_user_period", table_name="budget_period_snapshots")
    op.drop_table("budget_period_snapshots")
    op.drop_table("user_segments")
    op.drop_index("ix_imports_user", table_name="transaction_imports")
    op.drop_index("ix_imports_sha", table_name="transaction_imports")
    op.drop_table("transaction_imports")
    op.drop_index("ix_refresh_user", table_name="refresh_tokens")
    op.drop_index("ix_refresh_family", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("recurring_series")
    op.drop_index(
        "ix_notif_unread", table_name="notifications", postgresql_where=sa.text("read_at IS NULL")
    )
    op.drop_table("notifications")
    op.drop_table("merchant_rules")
    op.drop_table("insights")
    op.drop_table("idempotency_keys")
    op.drop_index("ix_fc_lookup", table_name="forecasts")
    op.drop_table("forecasts")
    op.drop_index("ux_fc_outcome", table_name="forecast_outcomes")
    op.drop_table("forecast_outcomes")
    op.drop_index("ux_budget_user_cat", table_name="budgets")
    op.drop_table("budgets")
    op.drop_table("anomaly_suppressions")
    op.drop_index("ux_users_email", table_name="users")
    op.drop_table("users")
    op.drop_table("processed_events")
    op.drop_index(
        "ix_outbox_pending",
        table_name="outbox_events",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.drop_table("outbox_events")
    op.drop_table("job_runs")
    op.drop_table("deletion_requests")
    op.drop_table("categories")
