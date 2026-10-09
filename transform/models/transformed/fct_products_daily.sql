with listings as (
    select
        l.fb_listing_id,
        l.listing_url,
        l.product_model,
        l.listed_at::date as listed_date,
        l.price,
        l.deal_score
    from {{ ref('dim_classified_listings') }} as l
    where l.listing_type in ('gaming_console', 'laptop', 'smartphone', 'smartwatch', 'smart_ring', 'tablet', 'earbuds')
        and l.is_relevant_listing is true
        and l.product_model is not null
        and l.listed_at is not null
        and l.listed_at::date >= '2026-08-01'::date
        and l.price > 0
        and (
            l.estimated_market_value is null
            or l.price between (0.20 * l.estimated_market_value) and (3.0 * l.estimated_market_value)
        )
),
dates as (
    select
        p.product_model,
        gs::date as stat_date
    from (
        select product_model, min(listed_date) as first_date
        from listings
        group by product_model
    ) as p
    cross join lateral generate_series(
        p.first_date::timestamp,
        current_date::timestamp,
        interval '1 day'
    ) as gs
),
daily as (
    select
        d.product_model,
        d.stat_date,
        count(l.price) as n,
        coalesce(sum(l.price), 0) as sum_price,
        count(l.price) filter (where l.deal_score >= 8) as n_deal,
        coalesce(sum(l.price) filter (where l.deal_score >= 8), 0) as sum_price_deal
    from dates as d
    left join listings as l
        on l.product_model = d.product_model and l.listed_date = d.stat_date
    group by d.product_model, d.stat_date
),

windowed as (
    select
        product_model,
        stat_date,
        sum(n) over w_cum as listings_cumulative,
        round(sum(sum_price) over w_cum / nullif(sum(n) over w_cum, 0), 2) as avg_price_cumulative,
        sum(n) over w30 as listings_30d,
        round(sum(sum_price) over w30 / nullif(sum(n) over w30, 0), 2) as avg_price_30d,
        sum(n) over w7 as listings_7d,
        round(sum(sum_price) over w7 / nullif(sum(n) over w7, 0), 2) as avg_price_7d,
        sum(n) over w3 as listings_3d,
        round(sum(sum_price) over w3 / nullif(sum(n) over w3, 0), 2) as avg_price_3d,
        n as listings_1d,
        round(sum_price / nullif(n, 0), 2) as avg_price_1d,
        sum(n_deal) over w_cum as deal8_listings_cumulative,
        round(sum(sum_price_deal) over w_cum / nullif(sum(n_deal) over w_cum, 0), 2) as deal8_avg_price_cumulative,
        sum(n_deal) over w30 as deal8_listings_30d,
        round(sum(sum_price_deal) over w30 / nullif(sum(n_deal) over w30, 0), 2) as deal8_avg_price_30d,
        sum(n_deal) over w7 as deal8_listings_7d,
        round(sum(sum_price_deal) over w7 / nullif(sum(n_deal) over w7, 0), 2) as deal8_avg_price_7d,
        sum(n_deal) over w3 as deal8_listings_3d,
        round(sum(sum_price_deal) over w3 / nullif(sum(n_deal) over w3, 0), 2) as deal8_avg_price_3d,
        n_deal as deal8_listings_1d,
        round(sum_price_deal / nullif(n_deal, 0), 2) as deal8_avg_price_1d
    from daily
    window
        w_cum as (partition by product_model order by stat_date rows between unbounded preceding and current row),
        w30 as (partition by product_model order by stat_date rows between 29 preceding and current row),
        w7 as (partition by product_model order by stat_date rows between 6 preceding and current row),
        w3 as (partition by product_model order by stat_date rows between 2 preceding and current row)
){% if is_incremental() %},
rebuild_from as (
    select
        least(
            current_date - {{ var('lookback_days', 3) }},
            coalesce(min(l.listed_at::date), date '9999-12-31')
        ) as start_date
    from {{ ref('dim_classified_listings') }} as l
    where l.listed_at is not null
        and (
            l.scraped_at >= current_timestamp - interval '{{ var('lookback_days', 3) }} days'
            or l.classified_at >= current_timestamp - interval '{{ var('lookback_days', 3) }} days'
        )
){% endif %}
select
    t.*,
    lo30.lowest_5_deals_30d,
    lo7.lowest_5_deals_7d,
    lo3.lowest_5_deals_3d,
    lo1.lowest_5_deals_1d,
    tenth.tenth_cheapest_price_7d,
    dec30.cutoff_price_cheapest_10pct_30d,
    d8lo30.deal8_lowest_5_deals_30d,
    d8lo7.deal8_lowest_5_deals_7d,
    d8lo3.deal8_lowest_5_deals_3d,
    d8lo1.deal8_lowest_5_deals_1d,
    d8tenth.deal8_tenth_cheapest_price_7d,
    d8dec30.deal8_cutoff_price_cheapest_10pct_30d
from windowed as t
left join lateral (
    select l.price as tenth_cheapest_price_7d
    from listings as l
    where l.product_model = t.product_model and l.listed_date between t.stat_date - 6 and t.stat_date
    order by l.price, l.fb_listing_id
    offset 9
    limit 1
) as tenth on true
left join lateral (
    select
        max(x.price) as cutoff_price_cheapest_10pct_30d
    from (
        select l.price, ntile(10) over (order by l.price) as decile
        from listings as l
        where l.product_model = t.product_model and l.listed_date between t.stat_date - 29 and t.stat_date
    ) as x
    where x.decile = 1
) as dec30 on true
left join lateral (
    select jsonb_agg(
               jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
               order by x.price, x.fb_listing_id
           ) as lowest_5_deals_30d
    from (
        select l.fb_listing_id, l.listing_url, l.price
        from listings as l
        where l.product_model = t.product_model and l.listed_date between t.stat_date - 29 and t.stat_date
        order by l.price, l.fb_listing_id
        limit 5
    ) as x
) as lo30 on true
left join lateral (
    select jsonb_agg(
               jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
               order by x.price, x.fb_listing_id
           ) as lowest_5_deals_7d
    from (
        select l.fb_listing_id, l.listing_url, l.price
        from listings as l
        where l.product_model = t.product_model and l.listed_date between t.stat_date - 6 and t.stat_date
        order by l.price, l.fb_listing_id
        limit 5
    ) as x
) as lo7 on true
left join lateral (
    select jsonb_agg(
               jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
               order by x.price, x.fb_listing_id
           ) as lowest_5_deals_3d
    from (
        select l.fb_listing_id, l.listing_url, l.price
        from listings as l
        where l.product_model = t.product_model and l.listed_date between t.stat_date - 2 and t.stat_date
        order by l.price, l.fb_listing_id
        limit 5
    ) as x
) as lo3 on true
left join lateral (
    select jsonb_agg(
               jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
               order by x.price, x.fb_listing_id
           ) as lowest_5_deals_1d
    from (
        select l.fb_listing_id, l.listing_url, l.price
        from listings as l
        where l.product_model = t.product_model and l.listed_date = t.stat_date
        order by l.price, l.fb_listing_id
        limit 5
    ) as x
) as lo1 on true
-- same metrics again, built only from listings with deal_score >= 8
left join lateral (
    select jsonb_agg(
               jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
               order by x.price, x.fb_listing_id
           ) as deal8_lowest_5_deals_30d
    from (
        select l.fb_listing_id, l.listing_url, l.price
        from listings as l
        where l.product_model = t.product_model and l.listed_date between t.stat_date - 29 and t.stat_date
            and l.deal_score >= 8
        order by l.price, l.fb_listing_id
        limit 5
    ) as x
) as d8lo30 on true
left join lateral (
    select jsonb_agg(
               jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
               order by x.price, x.fb_listing_id
           ) as deal8_lowest_5_deals_7d
    from (
        select l.fb_listing_id, l.listing_url, l.price
        from listings as l
        where l.product_model = t.product_model and l.listed_date between t.stat_date - 6 and t.stat_date
            and l.deal_score >= 8
        order by l.price, l.fb_listing_id
        limit 5
    ) as x
) as d8lo7 on true
left join lateral (
    select jsonb_agg(
               jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
               order by x.price, x.fb_listing_id
           ) as deal8_lowest_5_deals_3d
    from (
        select l.fb_listing_id, l.listing_url, l.price
        from listings as l
        where l.product_model = t.product_model and l.listed_date between t.stat_date - 2 and t.stat_date
            and l.deal_score >= 8
        order by l.price, l.fb_listing_id
        limit 5
    ) as x
) as d8lo3 on true
left join lateral (
    select jsonb_agg(
               jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
               order by x.price, x.fb_listing_id
           ) as deal8_lowest_5_deals_1d
    from (
        select l.fb_listing_id, l.listing_url, l.price
        from listings as l
        where l.product_model = t.product_model and l.listed_date = t.stat_date
            and l.deal_score >= 8
        order by l.price, l.fb_listing_id
        limit 5
    ) as x
) as d8lo1 on true
left join lateral (
    select l.price as deal8_tenth_cheapest_price_7d
    from listings as l
    where l.product_model = t.product_model and l.listed_date between t.stat_date - 6 and t.stat_date
        and l.deal_score >= 8
    order by l.price, l.fb_listing_id
    offset 9
    limit 1
) as d8tenth on true
left join lateral (
    select
        max(x.price) as deal8_cutoff_price_cheapest_10pct_30d
    from (
        select l.price, ntile(10) over (order by l.price) as decile
        from listings as l
        where l.product_model = t.product_model and l.listed_date between t.stat_date - 29 and t.stat_date
            and l.deal_score >= 8
    ) as x
    where x.decile = 1
) as d8dec30 on true
{% if is_incremental() %}
where t.stat_date >= (select start_date from rebuild_from)
{% endif %}

-- Indexes: (product_model, stat_date) serves the benchmark join and latest-row lookups per
-- product; stat_date serves the incremental delete and date-range scans.
{{
    config(
        materialized='incremental',
        unique_key=['product_model', 'stat_date'],
        incremental_strategy='delete+insert',
        indexes=[
            {'columns': ['product_model', 'stat_date'], 'unique': True},
            {'columns': ['stat_date']},
        ]
    )
}}
