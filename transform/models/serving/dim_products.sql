select
    c.slug,
    c.product_model,
    c.display_name,
    c.category_key,
    cat.category_name,
    cat.brand,
    current_timestamp as updated_at
from {{ ref('product_catalog') }} as c
inner join {{ ref('dim_categories') }} as cat on cat.category_key = c.category_key
where c.enabled

{{
    config(
        indexes=[
            {'columns': ['slug'], 'unique': True},
            {'columns': ['category_key']},
        ]
    )
}}
