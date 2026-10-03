select *
from {{ ref('dim_classified_listings') }}
where category_key = 'samsung_galaxy'
  --and is_relevant_listing = true

{{ config(materialized='view') }}

