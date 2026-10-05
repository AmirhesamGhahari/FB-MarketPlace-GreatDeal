select
    product_key,
    category_key,
    product_brand,
    product_model,
    product_variant,
    storage_gb,
    count(*)                                             as total_listings_seen,
    count(*) filter (where is_great_deal = true)        as great_deals_count,
    round(avg(deal_score)::numeric, 1)                  as avg_deal_score,
    round(avg(estimated_market_value)::numeric, 2)      as avg_market_value_cad,
    min(estimated_market_value)                          as min_market_value_cad,
    max(estimated_market_value)                          as max_market_value_cad,
    round(avg(price_vs_market_pct)::numeric, 1)         as avg_price_vs_market_pct
from {{ ref('dim_classified_listings') }}
where product_brand is not null
  and product_model is not null
  and is_relevant_listing = true
group by 1, 2, 3, 4, 5, 6

{{
    config(
        materialized='table',
        indexes=[
            {'columns': ['product_key'], 'unique': True},
            {'columns': ['category_key', 'product_model']},
            {'columns': ['category_key']},
        ]
    )
}}
