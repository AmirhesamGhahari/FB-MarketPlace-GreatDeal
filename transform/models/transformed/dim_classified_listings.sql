with base as (
    select
        md5(fr.fb_listing_id) as listing_key,
        md5(
            coalesce(fc.product_brand, '') || '|' ||
            coalesce(fc.product_model, '') || '|' ||
            coalesce(fc.product_variant, '') || '|' ||
            coalesce(cast(fc.storage_gb as text), '')
        ) as product_key,
        fr.category_key,
        fr.search_query,
        fr.pipeline_run_id,
        fr.fb_listing_id,
        fr.listing_url,
        fr.title,
        fr.description,
        fr.price,
        fr.original_price,
        fr.fb_condition,
        fr.location_city,
        fr.location_state,
        fr.is_highly_rated_seller,
        fr.listed_at,
        fr.scraped_at,
        fc.listing_type,
        fc.product_brand,
        fc.product_model,
        fc.product_variant,
        fc.condition,
        fc.storage_gb,
        fc.color,
        fc.battery_health_pct,
        fc.cycle_count,
        fc.is_relevant_listing,
        fc.is_great_deal,
        fc.deal_score,
        fc.estimated_market_value,
        fc.price_vs_market_pct,
        fc.notes,
        fc.confidence,
        fc.classified_at
    from facebook.fb_listings_raw fr
    left join facebook.fb_listings_classified as fc on fc.raw_listing_id = fr.id
    where fr.valid_to is null
    {% if is_incremental() %}
      and fc.classified_at > (select max(classified_at) from {{ this }})
    {% endif %}
)
select * 
from base

{{
    config(
        materialized='incremental',
        unique_key='fb_listing_id',
        incremental_strategy='delete+insert',
        indexes=[
            {'columns': ['fb_listing_id'], 'unique': True},
            {'columns': ['classified_at']},
            {'columns': ['category_key']},
            {'columns': ['listing_type']},
            {'columns': ['product_model']},
            {'columns': ['category_key', 'is_relevant_listing']},
            {'columns': ['category_key', 'product_model']},
            {'columns': ['listed_at']},
        ]
    )
}}
