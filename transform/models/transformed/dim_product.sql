select
    md5(
        coalesce(product_brand, '') || '|' ||
        coalesce(product_model, '') || '|' ||
        coalesce(product_variant, '') || '|' ||
        coalesce(cast(storage_gb as text), '')
    ) as product_key,
    product_brand,
    product_model,
    product_variant,
    count(*)                                    as total_listings_seen,
    round(avg(estimated_market_value), 2)       as avg_market_value_cad,
    min(estimated_market_value)                 as min_market_value_cad,
    max(estimated_market_value)                 as max_market_value_cad
from {{ source('facebook', 'fb_listings_classified') }}
where product_brand is not null
  and product_model is not null
group by 1, 2, 3, 4
