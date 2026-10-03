select *
from {{ ref('dim_classified_listings') }}
where category_key = 'smart_rings'
  --and is_relevant_listing = true

{{ config(materialized='view') }}

