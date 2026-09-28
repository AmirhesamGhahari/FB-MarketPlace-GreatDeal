"""initial DB tables creation

Revision ID: 606a3a674b3d
Revises: 
Create Date: 2026-09-28 16:29:10.206436

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '606a3a674b3d'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS facebook;')
    op.create_table('categories',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('category_key', sa.String(length=64), nullable=False),
    sa.Column('category_name', sa.String(length=255), nullable=False),
    sa.Column('product_type', sa.Text(), nullable=True),
    sa.Column('brand', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('category_key')
    )
    op.create_table('pipeline_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('stage', sa.String(length=64), nullable=False),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('source_type', sa.String(length=32), nullable=True),
    sa.Column('mode', sa.String(length=16), nullable=True),
    sa.Column('category_key', sa.String(length=64), nullable=True),
    sa.Column('category_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('total_records', sa.BigInteger(), nullable=True),
    sa.Column('error_count', sa.BigInteger(), nullable=True),
    sa.Column('newly_added_count', sa.BigInteger(), nullable=True),
    sa.Column('change_added_count', sa.BigInteger(), nullable=True),
    sa.Column('skipped_count', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name='fk_pipeline_runs_category_id'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_pipeline_runs_category_id', 'pipeline_runs', ['category_id'], unique=False)
    op.create_index('idx_pipeline_runs_category_key', 'pipeline_runs', ['category_key'], unique=False)
    op.create_index('idx_pipeline_runs_created_at', 'pipeline_runs', ['created_at'], unique=False)
    op.create_index('idx_pipeline_runs_source_type', 'pipeline_runs', ['source_type'], unique=False)
    op.create_index('idx_pipeline_runs_started_at', 'pipeline_runs', ['started_at'], unique=False)
    op.create_table('fb_listings_raw',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('category_id', sa.UUID(), nullable=False),
    sa.Column('category_key', sa.String(length=64), nullable=False),
    sa.Column('pipeline_run_id', sa.UUID(), nullable=False),
    sa.Column('fb_listing_id', sa.Text(), nullable=False),
    sa.Column('listing_url', sa.Text(), nullable=False),
    sa.Column('seller_profile_id', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=10), nullable=True),
    sa.Column('location_city', sa.Text(), nullable=True),
    sa.Column('location_state', sa.Text(), nullable=True),
    sa.Column('image_urls', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('is_sold', sa.Boolean(), nullable=False),
    sa.Column('search_query', sa.Text(), nullable=True),
    sa.Column('fb_condition', sa.Text(), nullable=True),
    sa.Column('delivery_types', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('is_highly_rated_seller', sa.Boolean(), nullable=True),
    sa.Column('original_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('listed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('scraped_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name='fk_fb_listing_raw_category_id'),
    sa.ForeignKeyConstraint(['pipeline_run_id'], ['pipeline_runs.id'], name='fk_fb_listing_raw_run_id'),
    sa.PrimaryKeyConstraint('id'),
    schema='facebook'
    )
    op.create_index('idx_fb_listing_raw_category_listed_at', 'fb_listings_raw', ['category_id', 'listed_at'], unique=False, schema='facebook')
    op.create_index('idx_fb_listing_raw_category_listing', 'fb_listings_raw', ['category_id', 'fb_listing_id'], unique=False, schema='facebook')
    op.create_index('idx_fb_listing_raw_current', 'fb_listings_raw', ['category_id', 'fb_listing_id'], unique=True, schema='facebook', postgresql_where=sa.text('valid_to IS NULL'))
    op.create_index('idx_fb_listing_raw_run', 'fb_listings_raw', ['pipeline_run_id'], unique=False, schema='facebook')
    op.create_table('fb_listings_classified',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('raw_listing_id', sa.BigInteger(), nullable=False),
    sa.Column('category_id', sa.UUID(), nullable=False),
    sa.Column('fb_listing_id', sa.Text(), nullable=False),
    sa.Column('llm_model', sa.Text(), nullable=False),
    sa.Column('listing_type', sa.Text(), nullable=True),
    sa.Column('product_brand', sa.Text(), nullable=True),
    sa.Column('product_model', sa.Text(), nullable=True),
    sa.Column('product_variant', sa.Text(), nullable=True),
    sa.Column('condition', sa.Text(), nullable=True),
    sa.Column('storage_gb', sa.BigInteger(), nullable=True),
    sa.Column('color', sa.Text(), nullable=True),
    sa.Column('battery_health_pct', sa.SmallInteger(), nullable=True),
    sa.Column('cycle_count', sa.Integer(), nullable=True),
    sa.Column('is_unlocked', sa.Boolean(), nullable=True),
    sa.Column('warranty_notes', sa.Text(), nullable=True),
    sa.Column('includes_accessories', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('is_store_seller', sa.Boolean(), nullable=True),
    sa.Column('deal_score', sa.SmallInteger(), nullable=True),
    sa.Column('is_great_deal', sa.Boolean(), nullable=True),
    sa.Column('estimated_market_value', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('price_vs_market_pct', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('is_genuine_listing', sa.Boolean(), nullable=True),
    sa.Column('is_scam_risk', sa.Boolean(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('raw_llm_response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('classified_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name='fk_fb_classified_category_id'),
    sa.ForeignKeyConstraint(['raw_listing_id'], ['facebook.fb_listings_raw.id'], name='fk_fb_classified_raw_listing_id'),
    sa.PrimaryKeyConstraint('id'),
    schema='facebook'
    )
    op.create_index('idx_fb_classified_category_at', 'fb_listings_classified', ['category_id', 'classified_at'], unique=False, schema='facebook')
    op.create_index('idx_fb_classified_category_deals', 'fb_listings_classified', ['category_id', 'is_great_deal', 'deal_score'], unique=False, schema='facebook')
    op.create_index('idx_fb_classified_raw_listing', 'fb_listings_classified', ['raw_listing_id'], unique=True, schema='facebook')
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index('idx_fb_classified_raw_listing', table_name='fb_listings_classified', schema='facebook')
    op.drop_index('idx_fb_classified_category_deals', table_name='fb_listings_classified', schema='facebook')
    op.drop_index('idx_fb_classified_category_at', table_name='fb_listings_classified', schema='facebook')
    op.drop_table('fb_listings_classified', schema='facebook')
    op.drop_index('idx_fb_listing_raw_run', table_name='fb_listings_raw', schema='facebook')
    op.drop_index('idx_fb_listing_raw_current', table_name='fb_listings_raw', schema='facebook', postgresql_where=sa.text('valid_to IS NULL'))
    op.drop_index('idx_fb_listing_raw_category_listing', table_name='fb_listings_raw', schema='facebook')
    op.drop_index('idx_fb_listing_raw_category_listed_at', table_name='fb_listings_raw', schema='facebook')
    op.drop_table('fb_listings_raw', schema='facebook')
    op.drop_index('idx_pipeline_runs_started_at', table_name='pipeline_runs')
    op.drop_index('idx_pipeline_runs_source_type', table_name='pipeline_runs')
    op.drop_index('idx_pipeline_runs_created_at', table_name='pipeline_runs')
    op.drop_index('idx_pipeline_runs_category_key', table_name='pipeline_runs')
    op.drop_index('idx_pipeline_runs_category_id', table_name='pipeline_runs')
    op.drop_table('pipeline_runs')
    op.drop_table('categories')
    op.execute('DROP SCHEMA IF EXISTS facebook;')
    # ### end Alembic commands ###
