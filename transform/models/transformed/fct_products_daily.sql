-- depends_on: {{ ref('dim_classified_listings') }}
with listings as (
    select
        fb_listing_id,
        listing_url,
        product_model,
        listed_date,
        price,
        deal_score,
        condition,
        estimated_market_value
    from {{ ref('benchmark_listings') }}
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
        coalesce(sum(l.price) filter (where l.deal_score >= 8), 0) as sum_price_deal,
        count(l.price) filter (where l.condition in ('New', 'Like New')) as n_good,
        coalesce(sum(l.price) filter (where l.condition in ('New', 'Like New')), 0) as sum_price_good,
        count(l.estimated_market_value) as n_mv,
        coalesce(sum(l.estimated_market_value), 0) as sum_mv
    from dates as d
    left join listings as l
        on l.product_model = d.product_model and l.listed_date = d.stat_date
    group by d.product_model, d.stat_date
),

-- rolling windows include stat_date; daily has one row per product per day, so N rows = N days
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
        sum(n) over w1 as listings_1d,
        round(sum(sum_price) over w1 / nullif(sum(n) over w1, 0), 2) as avg_price_1d,
        sum(n_deal) over w_cum as deal8_listings_cumulative,
        round(sum(sum_price_deal) over w_cum / nullif(sum(n_deal) over w_cum, 0), 2) as deal8_avg_price_cumulative,
        sum(n_deal) over w30 as deal8_listings_30d,
        round(sum(sum_price_deal) over w30 / nullif(sum(n_deal) over w30, 0), 2) as deal8_avg_price_30d,
        sum(n_deal) over w7 as deal8_listings_7d,
        round(sum(sum_price_deal) over w7 / nullif(sum(n_deal) over w7, 0), 2) as deal8_avg_price_7d,
        sum(n_deal) over w3 as deal8_listings_3d,
        round(sum(sum_price_deal) over w3 / nullif(sum(n_deal) over w3, 0), 2) as deal8_avg_price_3d,
        sum(n_deal) over w1 as deal8_listings_1d,
        round(sum(sum_price_deal) over w1 / nullif(sum(n_deal) over w1, 0), 2) as deal8_avg_price_1d,
        sum(n_good) over w30 as good_condition_count_30d,
        round(sum(sum_price_good) over w30 / nullif(sum(n_good) over w30, 0), 2) as good_condition_avg_30d,
        sum(n_good) over w7 as good_condition_count_7d,
        round(sum(sum_price_good) over w7 / nullif(sum(n_good) over w7, 0), 2) as good_condition_avg_7d,
        sum(n_good) over w3 as good_condition_count_3d,
        round(sum(sum_price_good) over w3 / nullif(sum(n_good) over w3, 0), 2) as good_condition_avg_3d,
        sum(n_good) over w1 as good_condition_count_1d,
        round(sum(sum_price_good) over w1 / nullif(sum(n_good) over w1, 0), 2) as good_condition_avg_1d,
        round(sum(sum_mv) over w30 / nullif(sum(n_mv) over w30, 0), 2) as avg_market_value_30d
    from daily
    window
        w_cum as (partition by product_model order by stat_date rows between unbounded preceding and current row),
        w30 as (partition by product_model order by stat_date rows between 29 preceding and current row),
        w7 as (partition by product_model order by stat_date rows between 6 preceding and current row),
        w3 as (partition by product_model order by stat_date rows between 2 preceding and current row),
        w1 as (partition by product_model order by stat_date rows between current row and current row)
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
    s30.lowest_5_deals_30d,
    s7.lowest_5_deals_7d,
    s3.lowest_5_deals_3d,
    s1.lowest_5_deals_1d,
    s30.deal8_lowest_5_deals_30d,
    s7.deal8_lowest_5_deals_7d,
    s3.deal8_lowest_5_deals_3d,
    s1.deal8_lowest_5_deals_1d,
    s30.cutoff_price_cheapest_25pct_30d,
    s7.cutoff_price_cheapest_25pct_7d,
    s3.cutoff_price_cheapest_25pct_3d,
    s1.cutoff_price_cheapest_25pct_1d,
    s30.deal8_cutoff_price_cheapest_25pct_30d,
    s7.deal8_cutoff_price_cheapest_25pct_7d,
    s3.deal8_cutoff_price_cheapest_25pct_3d,
    s1.deal8_cutoff_price_cheapest_25pct_1d
from windowed as t
-- 30d window: 25th percentile price (only with at least 10 listings in the group) and the 5 cheapest listings,
-- for all listings and for deal_score >= 8
left join lateral (
    select
        case when count(*) >= 10
            then round((percentile_cont(0.25) within group (order by l.price))::numeric, 2)
        end as cutoff_price_cheapest_25pct_30d,
        case when count(*) filter (where l.deal_score >= 8) >= 10
            then round((percentile_cont(0.25) within group (order by l.price) filter (where l.deal_score >= 8))::numeric, 2)
        end as deal8_cutoff_price_cheapest_25pct_30d,
        (
            select jsonb_agg(
                       jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
                       order by x.price, x.fb_listing_id
                   )
            from (
                select l2.fb_listing_id, l2.listing_url, l2.price
                from listings as l2
                where l2.product_model = t.product_model and l2.listed_date between t.stat_date - 29 and t.stat_date
                order by l2.price, l2.fb_listing_id
                limit 5
            ) as x
        ) as lowest_5_deals_30d,
        (
            select jsonb_agg(
                       jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
                       order by x.price, x.fb_listing_id
                   )
            from (
                select l2.fb_listing_id, l2.listing_url, l2.price
                from listings as l2
                where l2.product_model = t.product_model and l2.listed_date between t.stat_date - 29 and t.stat_date
                    and l2.deal_score >= 8
                order by l2.price, l2.fb_listing_id
                limit 5
            ) as x
        ) as deal8_lowest_5_deals_30d
    from listings as l
    where l.product_model = t.product_model and l.listed_date between t.stat_date - 29 and t.stat_date
) as s30 on true
-- 7d window: 25th percentile price (only with at least 10 listings in the group) and the 5 cheapest listings,
-- for all listings and for deal_score >= 8
left join lateral (
    select
        case when count(*) >= 10
            then round((percentile_cont(0.25) within group (order by l.price))::numeric, 2)
        end as cutoff_price_cheapest_25pct_7d,
        case when count(*) filter (where l.deal_score >= 8) >= 10
            then round((percentile_cont(0.25) within group (order by l.price) filter (where l.deal_score >= 8))::numeric, 2)
        end as deal8_cutoff_price_cheapest_25pct_7d,
        (
            select jsonb_agg(
                       jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
                       order by x.price, x.fb_listing_id
                   )
            from (
                select l2.fb_listing_id, l2.listing_url, l2.price
                from listings as l2
                where l2.product_model = t.product_model and l2.listed_date between t.stat_date - 6 and t.stat_date
                order by l2.price, l2.fb_listing_id
                limit 5
            ) as x
        ) as lowest_5_deals_7d,
        (
            select jsonb_agg(
                       jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
                       order by x.price, x.fb_listing_id
                   )
            from (
                select l2.fb_listing_id, l2.listing_url, l2.price
                from listings as l2
                where l2.product_model = t.product_model and l2.listed_date between t.stat_date - 6 and t.stat_date
                    and l2.deal_score >= 8
                order by l2.price, l2.fb_listing_id
                limit 5
            ) as x
        ) as deal8_lowest_5_deals_7d
    from listings as l
    where l.product_model = t.product_model and l.listed_date between t.stat_date - 6 and t.stat_date
) as s7 on true
-- 3d window: 25th percentile price (only with at least 10 listings in the group) and the 5 cheapest listings,
-- for all listings and for deal_score >= 8
left join lateral (
    select
        case when count(*) >= 10
            then round((percentile_cont(0.25) within group (order by l.price))::numeric, 2)
        end as cutoff_price_cheapest_25pct_3d,
        case when count(*) filter (where l.deal_score >= 8) >= 10
            then round((percentile_cont(0.25) within group (order by l.price) filter (where l.deal_score >= 8))::numeric, 2)
        end as deal8_cutoff_price_cheapest_25pct_3d,
        (
            select jsonb_agg(
                       jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
                       order by x.price, x.fb_listing_id
                   )
            from (
                select l2.fb_listing_id, l2.listing_url, l2.price
                from listings as l2
                where l2.product_model = t.product_model and l2.listed_date between t.stat_date - 2 and t.stat_date
                order by l2.price, l2.fb_listing_id
                limit 5
            ) as x
        ) as lowest_5_deals_3d,
        (
            select jsonb_agg(
                       jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
                       order by x.price, x.fb_listing_id
                   )
            from (
                select l2.fb_listing_id, l2.listing_url, l2.price
                from listings as l2
                where l2.product_model = t.product_model and l2.listed_date between t.stat_date - 2 and t.stat_date
                    and l2.deal_score >= 8
                order by l2.price, l2.fb_listing_id
                limit 5
            ) as x
        ) as deal8_lowest_5_deals_3d
    from listings as l
    where l.product_model = t.product_model and l.listed_date between t.stat_date - 2 and t.stat_date
) as s3 on true
-- 1d window: 25th percentile price (only with at least 10 listings in the group) and the 5 cheapest listings,
-- for all listings and for deal_score >= 8
left join lateral (
    select
        case when count(*) >= 10
            then round((percentile_cont(0.25) within group (order by l.price))::numeric, 2)
        end as cutoff_price_cheapest_25pct_1d,
        case when count(*) filter (where l.deal_score >= 8) >= 10
            then round((percentile_cont(0.25) within group (order by l.price) filter (where l.deal_score >= 8))::numeric, 2)
        end as deal8_cutoff_price_cheapest_25pct_1d,
        (
            select jsonb_agg(
                       jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
                       order by x.price, x.fb_listing_id
                   )
            from (
                select l2.fb_listing_id, l2.listing_url, l2.price
                from listings as l2
                where l2.product_model = t.product_model and l2.listed_date = t.stat_date
                order by l2.price, l2.fb_listing_id
                limit 5
            ) as x
        ) as lowest_5_deals_1d,
        (
            select jsonb_agg(
                       jsonb_build_object('listing_id', x.fb_listing_id, 'url', x.listing_url, 'price', x.price)
                       order by x.price, x.fb_listing_id
                   )
            from (
                select l2.fb_listing_id, l2.listing_url, l2.price
                from listings as l2
                where l2.product_model = t.product_model and l2.listed_date = t.stat_date
                    and l2.deal_score >= 8
                order by l2.price, l2.fb_listing_id
                limit 5
            ) as x
        ) as deal8_lowest_5_deals_1d
    from listings as l
    where l.product_model = t.product_model and l.listed_date = t.stat_date
) as s1 on true
{% if is_incremental() %}
where t.stat_date >= (select start_date from rebuild_from)
{% endif %}

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
