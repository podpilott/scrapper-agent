"""Supabase JWT authentication middleware with JWKS support."""

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Security, status
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


async def verify_websocket_token(token: str | None) -> AuthUser | None:
    """Verify token from WebSocket query parameter.

    Args:
        token: JWT token from query parameter.

    Returns:
        AuthUser if valid, None otherwise.
    """
    # If no Supabase configured, allow all (dev mode)
    if not settings.supabase_url:
        return AuthUser(user_id="dev-user", email="dev@example.com")

    if not token:
        return None

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
            return None

        email = payload.get("email")
        return AuthUser(user_id=user_id, email=email)

    except Exception:
        return None
