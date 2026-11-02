"""Runtime settings, read from the environment once at app creation."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

DEV_ENVS = {"dev", "test"}
DEV_DEMO_PASSWORD = "northbeam-demo"
MIN_SECRET_BYTES = 32


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    env: str
    warehouse_path: str
    jwt_secret: str
    demo_password: str
    token_ttl_minutes: int = 60
    bcrypt_rounds: int = 12
    login_max_failures: int = 5
    login_window_seconds: int = 900

    @classmethod
    def from_env(cls) -> "Settings":
        # Default is NOT dev: a server started with no env refuses to run on default secrets.
        env = os.environ.get("NB_ENV", "prod").strip().lower()
        is_dev = env in DEV_ENVS

        secret = os.environ.get("NB_JWT_SECRET", "")
        if not secret:
            if not is_dev:
                raise ConfigError("NB_JWT_SECRET is required unless NB_ENV=dev")
            # Random per process in dev: no well-known secret exists that could sign a token.
            secret = secrets.token_urlsafe(48)
        elif len(secret.encode()) < MIN_SECRET_BYTES and not is_dev:
            raise ConfigError(f"NB_JWT_SECRET must be at least {MIN_SECRET_BYTES} bytes")

        password = os.environ.get("NB_DEMO_PASSWORD", "")
        if not password:
            if not is_dev:
                raise ConfigError("NB_DEMO_PASSWORD is required unless NB_ENV=dev")
            password = DEV_DEMO_PASSWORD

        return cls(
            env=env,
            warehouse_path=os.environ.get("NB_WAREHOUSE", "warehouse/northbeam.duckdb"),
            jwt_secret=secret,
            demo_password=password,
            bcrypt_rounds=int(os.environ.get("NB_BCRYPT_ROUNDS", "12")),
            login_max_failures=int(os.environ.get("NB_LOGIN_MAX_FAILURES", "5")),
            login_window_seconds=int(os.environ.get("NB_LOGIN_WINDOW_SECONDS", "900")),
        )
