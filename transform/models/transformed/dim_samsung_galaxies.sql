{{ config(materialized='table') }}

SELECT *
FROM {{ ref('dim_classified_listings') }}
WHERE category_key = 'samsung_galaxy'
