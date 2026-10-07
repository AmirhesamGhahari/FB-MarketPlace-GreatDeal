WITH stats AS (
    SELECT
        product_model,
        category_key,
        COUNT(*) AS total_listings,
        FLOOR(AVG(price) FILTER (WHERE price IS NOT NULL)) AS average_price,
        COUNT(*) FILTER (WHERE is_great_deal = TRUE) AS great_deal_count,
        COUNT(*) FILTER (WHERE listed_at >= CURRENT_DATE - 7) AS listings_last_7_days,
        COUNT(*) FILTER (WHERE condition IN ('New', 'Like New', 'Good')) AS good_condition_count
    FROM {{ ref('dim_classified_listings') }}
    WHERE listing_type IN ('gaming_console', 'laptop', 'smartphone', 'smartwatch', 'smart_ring', 'tablet', 'earbuds')
        AND is_relevant_listing IS TRUE
        AND product_model IS NOT NULL
    GROUP BY product_model, category_key
    HAVING COUNT(*) > 5
)
SELECT *
FROM stats

{{
    config(
        materialized='table',
        indexes=[
            {'columns': ['product_model']}
        ]
    )
}}
