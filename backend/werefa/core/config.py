import secrets
import warnings
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str = "Werefa API"
    # Optional: enable cross-process real-time (queue WebSocket) fan-out. If unset, in-memory only.
    REALTIME_REDIS_URL: str | None = None
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""
    # Set to "require" for Neon, Supabase, RDS, etc. Omit for local Postgres without TLS.
    POSTGRES_SSLMODE: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        uri = PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )
        if self.POSTGRES_SSLMODE:
            return PostgresDsn(f"{uri!s}?sslmode={self.POSTGRES_SSLMODE}")
        return uri

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    # Penalty / no-show strikes (FR-12). The default values mirror the example
    # in `doc.md` Chapter 3 ("3 strikes in 30 days → 7-day block"). They are
    # tuned for the prod profile; tests override them via direct assignment to
    # exercise window math without waiting real time.
    STRIKE_WINDOW_DAYS: int = 30
    STRIKE_LIMIT: int = 3
    STRIKE_BLOCK_DAYS: int = 7

    # Service-weighted moving-average EWT (FR-06, FR-01). The values below
    # match the algorithm described in `phase-plan.md` §8.2 — fresh samples
    # weigh more (30-min half life), at least 3 samples are required before
    # the WMA is trusted (otherwise the configured `avg_duration_minutes`
    # baseline is used), and we keep at most 50 samples in the rolling
    # window per service line.
    EWT_HALF_LIFE_MIN: float = 30.0
    EWT_MIN_SAMPLES: int = 3
    EWT_HISTORY_LIMIT: int = 50
    # When a provider has multiple active service lines, "max" surfaces the
    # worst case (independent lines), "sum" assumes a single shared server.
    EWT_PROVIDER_AGGREGATION: Literal["max", "sum"] = "max"

    # Smart pre-alerts (FR-07). ``LIVENESS_TOP_K`` doubles as the position
    # threshold for the "head to counter" alert and (in Phase 11) the
    # liveness-ping window. ``NOTIFICATION_DEFAULT_PREFS`` is the ordered
    # list of channels new users start with — the first deliverable
    # channel wins per dispatch.
    LIVENESS_TOP_K: int = 3
    NOTIFICATION_DEFAULT_PREFS: list[str] = ["websocket", "email", "logger"]

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
