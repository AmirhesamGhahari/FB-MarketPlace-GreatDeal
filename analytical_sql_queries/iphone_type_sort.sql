with base as(
SELECT 
	fr.fb_listing_id,
	fr.title,
	fr.description,
	fr.price,
	fr.location_city,
	fr.search_query,
	fr.is_highly_rated_seller,
	fr.listed_at,
	fc.listing_type ,
	fc.product_brand,
	fc.product_model,
	fc.product_variant,
	fc.condition,
	fc.storage_gb,
	fc.color,
	fc.deal_score,
	fc.notes
FROM facebook.fb_listings_raw fr
left join facebook.fb_listings_classified AS fc on fc.raw_listing_id = fr.id 
)
select 
	*
from base 
where listing_type = 'phone'
and product_model = 'iPhone 17 Pro Max'
--group by listed_at::date, listing_type, product_model
order by listed_at::date desc, listing_type