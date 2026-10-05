select
    listed_at::date as listing_date,
    category_key,
    product_model,
    condition,
    listing_type,
    count(*)                                             as total_listings,
    count(*) filter (where is_great_deal = true)        as great_deals_count,
    round(avg(price)::numeric, 2)                       as avg_price_cad,
    min(price)                                          as min_price_cad,
    max(price)                                          as max_price_cad,
    round(avg(deal_score)::numeric, 1)                  as avg_deal_score,
    round(avg(estimated_market_value)::numeric, 2)      as avg_market_value_cad,
    round(avg(price_vs_market_pct)::numeric, 1)         as avg_price_vs_market_pct
from {{ ref('dim_classified_listings') }}
where is_relevant_listing = true
  and listed_at is not null
group by 1, 2, 3, 4, 5

{{
    config(
        materialized='table',
        indexes=[
            {'columns': ['listing_date', 'category_key']},
            {'columns': ['listing_date']},
            {'columns': ['category_key', 'product_model', 'listing_date']},
            {'columns': ['category_key']},
        ]
    )
}}
