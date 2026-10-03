select
    id as category_id,
    category_key,
    category_name,
    product_type,
    brand,
    created_at
from {{ source('public', 'categories') }}

{{ config(materialized='view') }}
