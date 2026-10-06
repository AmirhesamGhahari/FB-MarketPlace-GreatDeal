{{
    config(
        materialized='incremental',
        incremental_strategy='insert_overwrite',
        unique_key='fb_listing_id',
        partitioned_by=['category_key'],
        s3_data_dir=var('s3_data_dir', target.s3_staging_dir ~ 'models/'),
        format='parquet'
    )
}}

WITH latest_raw AS (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY fb_listing_id ORDER BY scraped_at DESC) AS _rn
    FROM {{ source('fb_marketplace_greatdeals', 'fb_listings_raw') }}
),

latest_classified AS (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY fb_listing_id ORDER BY classified_at DESC) AS _rn
    FROM {{ source('fb_marketplace_greatdeals', 'fb_listings_classified') }}
    {% if is_incremental() %}
    WHERE classified_at > (SELECT MAX(classified_at) FROM {{ this }})
    {% endif %}
),

base AS (
    SELECT
        to_hex(md5(to_utf8(fr.fb_listing_id)))    AS listing_key,
        to_hex(md5(to_utf8(
            COALESCE(fc.product_brand, '') || '|' ||
            COALESCE(fc.product_model, '') || '|' ||
            COALESCE(fc.product_variant, '') || '|' ||
            COALESCE(CAST(fc.storage_gb AS varchar), '')
        )))                                        AS product_key,
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
    FROM latest_raw AS fr
    LEFT JOIN latest_classified AS fc
        ON fc.fb_listing_id = fr.fb_listing_id AND fc._rn = 1
    WHERE fr._rn = 1
)

SELECT *
FROM base
