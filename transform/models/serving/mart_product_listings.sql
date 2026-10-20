select
    p.slug,
    b.fb_listing_id,
    b.listing_url,
    b.title,
    b.price,
    b.condition,
    b.storage_gb,
    b.color,
    b.location_city,
    b.listed_at,
    current_date - b.listed_date as days_ago,
    s.avg_price_30d,
    s.avg_price_7d,
    round(b.price - s.avg_price_30d, 2) as price_diff_30d,
    round(b.price - s.avg_price_7d, 2) as price_diff_7d
from {{ ref('dim_products') }} as p
inner join {{ ref('benchmark_listings') }} as b on b.product_model = p.product_model
left join {{ ref('mart_product_summary') }} as s on s.slug = p.slug
where b.listed_date > current_date - {{ var('listings_days') }}

{{
    config(
        indexes=[
            {'columns': ['fb_listing_id'], 'unique': True},
            {'columns': ['slug', 'price']},
            {'columns': ['slug', 'listed_at']},
        ]
    )
}}
