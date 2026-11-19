// Site-wide constants. Working name for now; change it here and every page title, header and footer follows.
export const SITE_NAME = "Great Deals";
export const SITE_TAGLINE = "Used electronics price trends and deals in Canada";

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

// Plain links in the top bar (no menu).
export const NAV_LINKS = [{ label: "How it works", href: "/how-it-works/" }] as const;

// Top-bar sections. `base` is the URL of the section's hub page; the Products entry also lists every product in its menu.
export const NAV_SECTIONS = [
  { label: "Products", base: "/categories/" },
  { label: "Market Insights", base: "/market-insights/" },
  { label: "Top Deals", base: "/top-deals/" },
  { label: "All Listings", base: "/all-listings/" },
] as const;
