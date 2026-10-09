with new_listings as (
    select
        l.raw_listing_id,
        l.fb_listing_id,
        l.listing_url,
        l.title,
        l.category_key,
        l.product_model,
        l.price,
        l.deal_score,
        l.estimated_market_value,
        l.price_vs_market_pct,
        l.condition,
        l.location_city,
        l.listed_at,
        l.scraped_at,
        l.classified_at
    from {{ ref('dim_classified_listings') }} as l
    where l.listing_type in ('gaming_console', 'laptop', 'smartphone', 'smartwatch', 'smart_ring', 'tablet', 'earbuds')
        and l.is_relevant_listing is true
        and l.product_model is not null
        and l.listed_at is not null
        and l.price is not null
    {% if is_incremental() %}
        and not exists (
            select 1 from {{ this }} as t
            where t.fb_listing_id = l.fb_listing_id
                and t.raw_listing_id = l.raw_listing_id
                and t.classified_at >= l.classified_at
        )
    {% endif %}
),
latest_benchmark as (
    select max(stat_date) as max_stat_date
    from {{ ref('fct_products_daily') }}
)
select
    l.raw_listing_id,
    l.fb_listing_id,
    l.listing_url,
    l.title,
    l.category_key,
    l.product_model,
    l.price,
    l.deal_score,
    l.estimated_market_value,
    l.price_vs_market_pct,
    l.condition,
    l.location_city,
    l.listed_at,
    l.scraped_at,
    l.classified_at,
    current_timestamp as evaluated_at,
    f.stat_date as benchmark_date,
    f.listings_30d,
    f.listings_7d,
    f.deal8_listings_30d,
    f.deal8_listings_7d,
    f.tenth_cheapest_price_7d,
    f.tenth_cheapest_price_30d,
    f.cutoff_price_cheapest_10pct_7d,
    f.cutoff_price_cheapest_10pct_30d,
    f.deal8_tenth_cheapest_price_7d,
    f.deal8_tenth_cheapest_price_30d,
    f.deal8_cutoff_price_cheapest_10pct_7d,
    f.deal8_cutoff_price_cheapest_10pct_30d,
    coalesce(
        f.listings_30d >= 10 and l.price <= f.tenth_cheapest_price_7d, 
        false
    ) as hit_tenth_cheapest_7d,
    coalesce(
        f.listings_30d >= 10 and l.price <= f.cutoff_price_cheapest_10pct_30d,
        false
    ) as hit_cheapest_decile_30d,
    coalesce(
        l.deal_score >= 8 and l.price <= f.deal8_tenth_cheapest_price_7d,
        false
    ) as deal8_hit_tenth_cheapest_7d,
    coalesce(
        l.deal_score >= 8
            and f.deal8_listings_30d >= 10
            and l.price <= f.deal8_cutoff_price_cheapest_10pct_30d,
        false
    ) as deal8_hit_cheapest_decile_30d,
    coalesce(
        f.listings_30d >= 10 and l.price <= f.tenth_cheapest_price_30d,
        false
    ) as hit_tenth_cheapest_30d,
    coalesce(
        f.listings_7d >= 10 and l.price <= f.cutoff_price_cheapest_10pct_7d,
        false
    ) as hit_cheapest_decile_7d,
    coalesce(
        l.deal_score >= 8 and l.price <= f.deal8_tenth_cheapest_price_30d,
        false
    ) as deal8_hit_tenth_cheapest_30d,
    coalesce(
        l.deal_score >= 8
            and f.deal8_listings_7d >= 10
            and l.price <= f.deal8_cutoff_price_cheapest_10pct_7d,
        false
    ) as deal8_hit_cheapest_decile_7d,
    case
        -- age of this version of the listing (when we scraped it), not of the listing itself, so a
        -- price drop on an older listing is evaluated, while the existing backlog is skipped
        when l.scraped_at < current_timestamp - interval '{{ var('candidate_max_age_days', 2) }} days' then 'old_record'
        when not (
            l.price > 0
            and (
                l.estimated_market_value is null
                or l.price between (0.20 * l.estimated_market_value) and (3.0 * l.estimated_market_value)
            )
        ) then 'outlier'
        when f.stat_date is null then 'no_benchmark'
        when f.listings_30d < 10 then 'insufficient_history'
        when lb.max_stat_date < current_date - 2 then 'stale_benchmark'
    end as skip_reason
from new_listings as l
cross join latest_benchmark as lb
left join {{ ref('fct_products_daily') }} as f
    on f.product_model = l.product_model
    and f.stat_date = l.listed_at::date - 1

{{
    config(
        materialized='incremental',
        unique_key='fb_listing_id',
        incremental_strategy='delete+insert',
        full_refresh=false,
        indexes=[
            {'columns': ['fb_listing_id'], 'unique': True},
            {'columns': ['raw_listing_id'], 'unique': True},
            {'columns': ['skip_reason']},
            {'columns': ['product_model', 'listed_at']},
            {'columns': ['category_key', 'listed_at']},
            {'columns': ['evaluated_at']},
        ]
    )
}}
