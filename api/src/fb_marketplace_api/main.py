from __future__ import annotations

from fastapi import FastAPI
from mangum import Mangum

from fb_marketplace_api.errors import install_error_handling
from fb_marketplace_api.routes import products

app = FastAPI(title="FB Marketplace Great Deals API", version="1")
install_error_handling(app)
app.include_router(products.router)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


# AWS Lambda entry point (API Gateway -> Mangum -> FastAPI)
handler = Mangum(app, lifespan="off")
