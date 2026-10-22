-- a product page needs at least 10 listings in the 30d window (also what the 25th-percentile cutoff requires)
select slug, listings_30d
from {{ ref('mart_product_summary') }}
where listings_30d < 10
