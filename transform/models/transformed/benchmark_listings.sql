-- Listings that count toward price benchmarks. Shared by fct_products_daily and the website serving models,
-- so every number is computed from the same set of listings.
with base_listings as (
    select
        l.fb_listing_id,
        l.listing_url,
        l.title,
        l.product_model,
        l.storage_gb,
        l.color,
        l.location_city,
        l.listed_at,
        l.listed_at::date as listed_date,
        l.price,
        l.deal_score,
        l.condition,
        l.estimated_market_value
    from {{ ref('dim_classified_listings') }} as l
    where l.listing_type in ('gaming_console', 'laptop', 'smartphone', 'smartwatch', 'smart_ring', 'tablet', 'earbuds')
        and l.is_relevant_listing is true
        and l.product_model is not null
        and l.listed_at is not null
        and l.listed_at::date >= '{{ var('benchmark_start_date') }}'::date
        and l.price > 0
        -- listings that can't be compared fairly are kept out of every benchmark
        and l.condition is distinct from 'Poor'
        and not l.has_defect_keyword
),
model_median as (
    select product_model, percentile_cont(0.5) within group (order by price) as median_price
    from base_listings
    group by product_model
)
select b.*
from base_listings as b
inner join model_median as m on m.product_model = b.product_model
where b.price between (0.3 * m.median_price) and (3.0 * m.median_price)

{{
    config(
        materialized='table',
        indexes=[
            {'columns': ['fb_listing_id'], 'unique': True},
            {'columns': ['product_model', 'listed_date']},
        ]
    )
}}
