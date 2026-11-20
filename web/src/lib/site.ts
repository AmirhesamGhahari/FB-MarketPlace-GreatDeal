// Site-wide constants. Working name for now; change it here and every page title, header and footer follows.
export const SITE_NAME = "Great Deals";
export const SITE_TAGLINE = "Used electronics price trends and deals in Canada";

// TODO before launch: replace with a real address on the site's own domain (shown on the Contact and Privacy pages).
export const CONTACT_EMAIL = "contact@your-domain.example";

// Ad slots (AdSlot component) render nothing while this is false, so no empty boxes show before ads exist.
export const ADS_ENABLED = false;

// The tabs on every product page. `path` is appended to /{category}/{slug}/ ("" = the overview page itself).
export const PRODUCT_TABS = [
  { key: "overview", label: "Overview", path: "" },
  { key: "market-insights", label: "Market insights", path: "market-insights/" },
  { key: "top-deals", label: "Top deals", path: "top-deals/" },
  { key: "listings", label: "All listings", path: "listings/" },
] as const;
export type ProductTabKey = (typeof PRODUCT_TABS)[number]["key"];

// The three hub sections of the top bar. `tab` is the key of the product page each card leads to (see PRODUCT_TABS).
// The all-listings hub is not for Google (noindex), like the listings pages it leads to.
export const HUBS = {
  "market-insights": { label: "Market Insights", tab: "market-insights", noindex: false },
  "top-deals": { label: "Top Deals", tab: "top-deals", noindex: false },
  "all-listings": { label: "All Listings", tab: "listings", noindex: true },
} as const;
export type HubKey = keyof typeof HUBS;

// The owners of the brands whose products the site tracks, for the "not affiliated" statements.
export const BRAND_OWNERS = "Facebook, Meta, Apple, Samsung, Sony, Microsoft, Nintendo or Oura";

// Plain links in the top bar (no menu).
export const NAV_LINKS = [{ label: "How it works", href: "/how-it-works/" }] as const;

// Top-bar sections. `base` is the URL of the section's hub page; the Products entry also lists every product in its menu.
export const NAV_SECTIONS = [
  { label: "Products", base: "/categories/" },
  { label: "Market Insights", base: "/market-insights/" },
  { label: "Top Deals", base: "/top-deals/" },
  { label: "All Listings", base: "/all-listings/" },
] as const;
