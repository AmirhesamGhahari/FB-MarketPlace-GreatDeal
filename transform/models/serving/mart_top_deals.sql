with ranked as (
    select
        l.slug,
        l.fb_listing_id,
        s.display_name,
        s.category_key,
        l.title,
        l.price,
        l.listing_url,
        l.location_city,
        l.listed_at,
        l.condition,
        l.avg_price_30d,
        l.price_diff_30d,
        s.cutoff_price_cheapest_25pct_30d,
        row_number() over (
            partition by l.slug
            -- biggest gap below the 25th-percentile cutoff first
            order by (s.cutoff_price_cheapest_25pct_30d - l.price) desc, l.listed_at desc, l.fb_listing_id
        ) as deal_rank
    from {{ ref('mart_product_listings') }} as l
    inner join {{ ref('mart_product_summary') }} as s on s.slug = l.slug
    where l.days_ago < 30
        -- the cutoff is null when the product has fewer than 10 listings in the window
        and s.cutoff_price_cheapest_25pct_30d is not null
)
select
    slug,
    fb_listing_id,
    display_name,
    category_key,
    deal_rank,
    title,
    price,
    listing_url,
    location_city,
    listed_at,
    condition,
    avg_price_30d,
    price_diff_30d,
    cutoff_price_cheapest_25pct_30d,
    current_timestamp as updated_at
from ranked
where deal_rank <= {{ var('top_deals_per_product') }}

{{
    config(
        indexes=[
            {'columns': ['slug', 'deal_rank'], 'unique': True},
            {'columns': ['category_key']},
            {'columns': ['fb_listing_id']},
        ]
    )
}}
