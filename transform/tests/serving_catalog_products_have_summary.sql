-- every enabled catalog product must have a summary row; a misspelled product_model gives an empty page
select p.slug
from {{ ref('dim_products') }} as p
left join {{ ref('mart_product_summary') }} as s on s.slug = p.slug
where s.slug is null
