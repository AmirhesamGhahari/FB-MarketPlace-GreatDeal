-- prices must be positive and at most 10,000
select slug, 'listing_price' as source, price as value
from {{ ref('mart_product_listings') }}
where price <= 0 or price > 10000
union all
select slug, 'avg_price_30d', avg_price_30d
from {{ ref('mart_product_summary') }}
where avg_price_30d <= 0 or avg_price_30d > 10000
