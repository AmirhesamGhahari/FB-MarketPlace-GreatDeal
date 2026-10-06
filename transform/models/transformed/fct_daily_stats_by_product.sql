{{
    config(materialized='table')
}}

SELECT
    CAST(listed_at AS DATE)                                                         AS listing_date,
    category_key,
    product_model,
    condition,
    listing_type,
    COUNT(*)                                                                        AS total_listings,
    COUNT(CASE WHEN is_great_deal = TRUE THEN 1 END)                               AS great_deals_count,
    ROUND(CAST(AVG(price) AS DECIMAL(12, 2)), 2)                                   AS avg_price_cad,
    MIN(price)                                                                      AS min_price_cad,
    MAX(price)                                                                      AS max_price_cad,
    ROUND(CAST(AVG(deal_score) AS DECIMAL(5, 1)), 1)                               AS avg_deal_score,
    ROUND(CAST(AVG(estimated_market_value) AS DECIMAL(12, 2)), 2)                  AS avg_market_value_cad,
    ROUND(CAST(AVG(price_vs_market_pct) AS DECIMAL(5, 1)), 1)                      AS avg_price_vs_market_pct
FROM {{ ref('dim_classified_listings') }}
WHERE
    is_relevant_listing = TRUE
    AND listed_at IS NOT NULL
GROUP BY 1, 2, 3, 4, 5
