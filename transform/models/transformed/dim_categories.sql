{{
    config(materialized='table')
}}

SELECT
    category_key,
    category_name,
    product_type,
    brand
FROM {{ ref('categories') }}
