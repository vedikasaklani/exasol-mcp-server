"""MCP server tools to provide to external clients"""
import json
import os

from fastapi import HTTPException
from fastmcp import FastMCP
from fastmcp.server.auth.providers.workos import AuthKitProvider
from fastmcp.server.dependencies import get_access_token
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from commerce_client import commerce_client
from database.database import get_db
from database.database_models import User
from security import create_access_token

mcp = FastMCP(
    "ecommerce-agent",
    auth=AuthKitProvider(
        authkit_domain="https://polished-silence-88-staging.authkit.app",
        base_url="https://external-mcp-server.onrender.com",  #match what WorkOS has configured
    ),
)


def _headers() -> dict:
    """Map the WorkOS-verified caller to one of OUR users, then mint a
    normal backend JWT for calling our own FastAPI API."""
    token = get_access_token()               # verified by AuthKitProvider 
    email = token.claims.get("email")        

    # we have to drive the generator ourselves to get a real Session.
    db_gen = get_db()
    db = next(db_gen)
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise HTTPException(403, "No matching account for this email")
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}
    finally:
        next(db_gen, None)  


def _envelope(key: str, result):
    """Wrap a successful commerce_client result under `key`; pass errors through unchanged."""
    if isinstance(result, dict) and result.get("error"):
        return result
    return {key: result}


@mcp.tool()
def search_products(q: str = None, category: str = None, min_price: float = None,
                     max_price: float = None, in_stock: bool = None) -> dict:
    """Search and filter the product catalog by name, category, price range, or stock status."""
    result = commerce_client.search_products(
        _headers(), q=q, category=category, min_price=min_price, max_price=max_price, in_stock=in_stock
    )
    return _envelope("products", result)


@mcp.tool()
def get_product(product_id: int) -> dict:
    """Get full details for a single product by its id (pid), including current price and stock."""
    return _envelope("product", commerce_client.get_product(_headers(), product_id))


@mcp.tool()
def add_to_cart(product_id: int, quantity: int) -> dict:
    """Add a quantity of one product to the cart. Fails if quantity exceeds current stock.
    Calling this multiple times for the same product creates separate cart line items."""
    return _envelope("add-to-cart", commerce_client.add_to_cart(_headers(), product_id, quantity))


@mcp.tool()
def remove_from_cart(product_id: int, quantity: int) -> dict:
    """Remove a quantity of a product from the cart, by product id (not cart item id)."""
    return _envelope("remove from cart", commerce_client.remove_from_cart(_headers(), product_id, quantity))


@mcp.tool()
def view_cart() -> dict:
    """Get all current cart items and the current total cost."""
    return _envelope("cart", commerce_client.view_cart(_headers()))


@mcp.tool()
def create_order() -> dict:
    """Place an order using all items currently in the cart. Backend enforces a ₹10,000 cap
    for agent-initiated orders -- if this returns a 400, tell the user their order exceeds it."""
    return _envelope("order", commerce_client.create_order(_headers()))


@mcp.tool()
def get_payment_link(order_id: int) -> dict:
    """Get a hosted payment page link for an order awaiting payment.
    Send this URL to the user -- they complete payment there."""
    return _envelope("payment-link", commerce_client.get_payment_link(_headers(), order_id))


@mcp.tool()
def check_order_status(order_id: int) -> dict:
    """Check whether an order has been paid yet."""
    return _envelope("order-status", commerce_client.check_order_status(_headers(), order_id))


@mcp.tool()
def get_ratings(product_id: int) -> dict:
    """Get customer reviews and average rating for a product by ID."""
    return _envelope("ratings", commerce_client.get_ratings(_headers(), product_id))

# Workaround for pydantic httpurl automatically adding a slash at end: causes a mismatch error
METADATA_PATHS = {
    "/.well-known/oauth-protected-resource/mcp",
    "/.well-known/oauth-authorization-server/mcp",
}

class StripTrailingSlashMiddleware(BaseHTTPMiddleware):
    """Normalize trailing slashes in OAuth metadata responses."""

    async def dispatch(self, request, call_next):
        """Rewrite OAuth metadata URLs before returning the response."""
        response = await call_next(request)
        if request.url.path not in METADATA_PATHS:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            data = json.loads(body)
            if isinstance(data.get("issuer"), str):
                data["issuer"] = data["issuer"].rstrip("/")
            if isinstance(data.get("authorization_servers"), list):
                data["authorization_servers"] = [
                    u.rstrip("/") for u in data["authorization_servers"]
                ]
            body = json.dumps(data).encode()
        except Exception:
            pass

        return Response(
            content=body,
            status_code=response.status_code,
            headers={
                k: v for k, v in response.headers.items()
                if k.lower() not in ("content-length", "content-encoding")
            },
            media_type=response.media_type or "application/json",
        )

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 9000)),
        middleware=[Middleware(StripTrailingSlashMiddleware)],
    )
