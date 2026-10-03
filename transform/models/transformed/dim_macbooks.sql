select *
from {{ ref('dim_classified_listings') }}
where category_key = 'macbook'
  --and is_relevant_listing = true

{{ config(materialized='view') }}
