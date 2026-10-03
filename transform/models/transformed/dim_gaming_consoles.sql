select *
from {{ ref('dim_classified_listings') }}
where category_key = 'gaming_console'
  --and is_relevant_listing = true

{{ config(materialized='view') }}
