"""Supabase JWT authentication middleware with JWKS support."""

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

import httpx
import jwt
from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from config.settings import settings

security = HTTPBearer(auto_error=False)

# Cache for JWKS client
_jwks_client: PyJWKClient | None = None
_jwks_client_created_at: float = 0
JWKS_CACHE_TTL = 3600  # 1 hour


def get_jwks_client() -> PyJWKClient:
    """Get or create JWKS client with caching."""
    global _jwks_client, _jwks_client_created_at

    now = time.time()
    if _jwks_client is None or (now - _jwks_client_created_at) > JWKS_CACHE_TTL:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url)
        _jwks_client_created_at = now

    return _jwks_client


@dataclass
class AuthUser:
    """Authenticated user information from JWT."""

    user_id: str
    email: str | None = None


async def verify_supabase_token(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> AuthUser:
    """Verify the Supabase JWT token from Authorization header.

    Args:
        credentials: Bearer token from Authorization header.

    Returns:
        AuthUser with user_id from the token.

    Raises:
        HTTPException: If token is missing, invalid, or expired.
    """
    # If no Supabase configured, allow all requests (dev mode)
    if not settings.supabase_url:
        return AuthUser(user_id="dev-user", email="dev@example.com")

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token. Include Authorization: Bearer <token> header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        # Try JWKS verification first (for ES256 keys)
        try:
            jwks_client = get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
            )
        except Exception:
            # Fall back to HS256 with JWT secret if configured
            if settings.supabase_jwt_secret:
                payload = jwt.decode(
                    token,
                    settings.supabase_jwt_secret.get_secret_value(),
                    algorithms=["HS256"],
                    audience="authenticated",
                )
            else:
                raise

        # Extract user_id from 'sub' claim
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Extract email if available
        email = payload.get("email")

        return AuthUser(user_id=user_id, email=email)

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_sse_token(request: Request) -> AuthUser:
    """Verify token from query param, cookie, or Authorization header.

    SSE/EventSource doesn't support custom headers, so we accept token via:
    1. Query parameter: ?token=xxx (preferred for cross-origin)
    2. Cookie: sb-*-auth-token (Supabase SSR format)
    3. Authorization header: Bearer xxx (for testing)

    Args:
        request: FastAPI request object.

    Returns:
        AuthUser with user_id from the token.

    Raises:
        HTTPException: If token is missing, invalid, or expired.
    """
    # If no Supabase configured, allow all requests (dev mode)
    if not settings.supabase_url:
        return AuthUser(user_id="dev-user", email="dev@example.com")

    token = None

    # Try query parameter first (for SSE cross-origin)
    token = request.query_params.get("token")

    # Try cookie (Supabase SSR format)
    if not token:
        for cookie_name, cookie_value in request.cookies.items():
            if cookie_name.startswith("sb-") and cookie_name.endswith("-auth-token"):
                try:
                    # Cookie value is URL-encoded JSON
                    decoded_value = unquote(cookie_value)
                    data = json.loads(decoded_value)
                    token = data.get("access_token")
                    if token:
                        break
                except (json.JSONDecodeError, TypeError):
                    pass

    # Fall back to Authorization header
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Missing auth cookie or Authorization header.",
        )

    try:
        # Try JWKS verification first (for ES256 keys)
        try:
            jwks_client = get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
            )
        except Exception:
            # Fall back to HS256 with JWT secret if configured
            if settings.supabase_jwt_secret:
                payload = jwt.decode(
                    token,
                    settings.supabase_jwt_secret.get_secret_value(),
                    algorithms=["HS256"],
                    audience="authenticated",
                )
            else:
                raise

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID.",
            )

        email = payload.get("email")
        return AuthUser(user_id=user_id, email=email)

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}",
        )
