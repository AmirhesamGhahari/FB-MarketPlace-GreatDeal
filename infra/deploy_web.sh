#!/usr/bin/env bash
# Builds the website and publishes it: build, check, copy to the S3 bucket, clear the CloudFront cache.
#
#   infra/deploy_web.sh          hidden version (noindex + robots.txt Disallow): safe to run any time
#   infra/deploy_web.sh live     the version Google may index (PUBLIC_SITE_LIVE=true): launch day
#
# Needs: terraform (outputs of infra/terraform), aws CLI logged in, node 22+ (the first `npm run build` reads the whole API).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${1:-}" = "live" ]; then
  export PUBLIC_SITE_LIVE=true
  echo "Building the LIVE version (Google may index it)."
else
  echo "Building the HIDDEN version (noindex). Use '$0 live' on launch day."
fi

# By hand the names come from Terraform; in an automated build (Phase 6) set WEB_BUCKET and CLOUDFRONT_DISTRIBUTION_ID instead.
BUCKET="${WEB_BUCKET:-$(terraform -chdir=infra/terraform output -raw web_bucket_name)}"
DISTRIBUTION="${CLOUDFRONT_DISTRIBUTION_ID:-$(terraform -chdir=infra/terraform output -raw cloudfront_distribution_id)}"

(cd web && npm run build && npm run check:site)

# Cache-Control is stored with each file and read by CloudFront (s-maxage) and by browsers (max-age); S3 itself does not cache.
#  - Pages and the search index change at every deploy under the same name: browsers keep them 5 minutes; CloudFront keeps
#    them up to a day, but the invalidation below empties it after every deploy, so in practice "until the next deploy".
#  - Files with a hash in their name (_astro) never change under that name: cached for a year everywhere.
PAGES_CACHE="public, max-age=300, s-maxage=86400"
aws s3 sync web/dist "s3://${BUCKET}" --delete --exclude "_astro/*" --cache-control "${PAGES_CACHE}"
aws s3 sync web/dist/_astro "s3://${BUCKET}/_astro" --delete --cache-control "public, max-age=31536000, immutable"

aws cloudfront create-invalidation --distribution-id "${DISTRIBUTION}" --paths "/*" --query "Invalidation.Id" --output text
echo "Done. Open https://$(terraform -chdir=infra/terraform output -raw site_url | sed 's#https://##')/"
