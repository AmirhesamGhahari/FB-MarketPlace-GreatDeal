from __future__ import annotations

from fastapi import FastAPI
from mangum import Mangum

from fb_marketplace_api.errors import install_error_handling
from fb_marketplace_api.routes import categories, deals, products

app = FastAPI(title="FB Marketplace Great Deals API", version="1")
install_error_handling(app)
app.include_router(categories.router)
app.include_router(deals.router)
app.include_router(products.router)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


# AWS Lambda entry point (API Gateway -> Mangum -> FastAPI).
# CloudFront serves the API under /api and forwards the full path; Mangum strips "/api" so routes stay /v1/...
handler = Mangum(app, lifespan="off", api_gateway_base_path="/api")
