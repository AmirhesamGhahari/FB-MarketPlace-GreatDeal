with latest as (
    select distinct on (f.product_model)
        f.*,
        p.slug,
        p.display_name,
        p.category_key
    from {{ ref('dim_products') }} as p
    inner join {{ ref('fct_products_daily') }} as f on f.product_model = p.product_model
    order by f.product_model, f.stat_date desc
)
select
    slug,
    display_name,
    category_key,
    stat_date as as_of_date,
    listings_30d,
    avg_price_30d,
    listings_7d,
    avg_price_7d,
    deal8_listings_30d,
    deal8_avg_price_30d,
    deal8_listings_7d,
    deal8_avg_price_7d,
    lowest_5_deals_30d,
    lowest_5_deals_7d,
    deal8_lowest_5_deals_30d,
    deal8_lowest_5_deals_7d,
    cutoff_price_cheapest_25pct_30d,
    cutoff_price_cheapest_25pct_7d,
    current_timestamp as updated_at
from latest

{{
    config(
        indexes=[
            {'columns': ['slug'], 'unique': True},
            {'columns': ['category_key']},
        ]
    )
}}
