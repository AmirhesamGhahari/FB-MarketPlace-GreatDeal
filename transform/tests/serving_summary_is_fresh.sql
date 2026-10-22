-- the latest stat date should be no more than 2 days old
select slug, as_of_date
from {{ ref('mart_product_summary') }}
where as_of_date < current_date - 2
