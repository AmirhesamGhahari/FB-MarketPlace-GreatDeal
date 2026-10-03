select *
from {{ ref('dim_classified_listings') }}
where category_key = 'apple_watch'
  --and is_relevant_listing = true

{{ config(materialized='view') }}
