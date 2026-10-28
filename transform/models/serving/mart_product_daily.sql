select
    p.slug,
    f.stat_date,
    f.listings_1d,
    f.avg_price_1d,
    -- chart b: average price over the last 3, 7 and 30 days, as of each day
    f.avg_price_3d,
    f.avg_price_7d,
    f.avg_price_30d,
    -- chart c: deal_score >= 8 listings per day, and their 7-day and 30-day average prices
    f.deal8_listings_1d,
    f.deal8_avg_price_7d,
    f.deal8_avg_price_30d,
    -- chart d: the 3 cheapest listings of the last 7 days as of each day (listing_id, url, price)
    (
        select jsonb_agg(e.item order by e.pos)
        from jsonb_array_elements(f.lowest_5_deals_7d) with ordinality as e(item, pos)
        where e.pos <= 3
    ) as lowest_3_deals_7d,
    -- chart e: price under which the cheapest 25% of listings fall, over 30 and 7 days
    f.cutoff_price_cheapest_25pct_30d,
    f.cutoff_price_cheapest_25pct_7d,
    current_timestamp as updated_at
from {{ ref('dim_products') }} as p
inner join {{ ref('fct_products_daily') }} as f on f.product_model = p.product_model
where f.stat_date > current_date - {{ var('chart_days') }}

{{
    config(
        indexes=[
            {'columns': ['slug', 'stat_date'], 'unique': True},
            {'columns': ['slug']},
            {'columns': ['stat_date']},
        ]
    )
}}
