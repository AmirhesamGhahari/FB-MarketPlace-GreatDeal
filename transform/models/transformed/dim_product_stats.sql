{{
    config(
        materialized='table'
    )
}}

WITH stats AS (
    SELECT
        product_model,
        COUNT(*)                                                                        AS total_listings,
        FLOOR(AVG(price))                                                               AS average_price,
        COUNT(CASE WHEN is_great_deal = TRUE THEN 1 END)                               AS great_deal_count,
        COUNT(CASE WHEN listed_at >= CURRENT_DATE - INTERVAL '7' DAY THEN 1 END)       AS listings_last_7_days,
        COUNT(CASE WHEN condition IN ('New', 'Like New', 'Good') THEN 1 END)           AS good_condition_count
    FROM {{ ref('dim_classified_listings') }}
    WHERE
        listing_type IN (
            'gaming_console', 'laptop', 'smartphone',
            'smartwatch', 'smart_ring', 'tablet', 'earbuds'
        )
        AND is_relevant_listing = TRUE
        AND product_model IS NOT NULL
    GROUP BY product_model
    HAVING COUNT(*) > 5
)

SELECT *
FROM stats
