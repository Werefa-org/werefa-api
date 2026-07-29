import secrets
import warnings
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    Field,
    HttpUrl,
    PostgresDsn,
    computed_field,
    field_validator,
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

    # OpenAPI / internal title (can differ from customer-facing email brand).
    PROJECT_NAME: str = "Werefa API"
    # Shown in email subjects, bodies, and default From name.
    BRAND_NAME: str = "Werefa"
    # Optional: enable cross-process real-time (queue WebSocket) fan-out. If unset, in-memory only.
    REALTIME_REDIS_URL: str | None = None
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = Field(default=5432)

    @field_validator("POSTGRES_SERVER", mode="before")
    @classmethod
    def _host_without_port(cls, v: Any) -> Any:
        """Allow mistaken ``host:5432`` in POSTGRES_SERVER; port belongs in POSTGRES_PORT."""
        if isinstance(v, str) and v.count(":") == 1:
            host, port_str = v.rsplit(":", 1)
            if port_str.isdigit():
                return host
        return v
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
            self.EMAILS_FROM_NAME = self.BRAND_NAME
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

    # FR-09 recall: staff can re-call the last **completed** ticket within this
    # many seconds of ``completed_at`` (mistaken close / customer returns).
    RECALL_COMPLETED_WINDOW_SECONDS: int = 90

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
    # FR-05: after entering top-K remotely, the customer must ping within this
    # many seconds or the ticket is ``flagged`` (hint for staff — not auto strike).
    LIVENESS_GRACE_SECONDS: int = 600
    # FR-05 sync can add ledger rows; turn off in tests that assert strict
    # FR-07 notification counts.
    LIVENESS_ENABLED: bool = True
    NOTIFICATION_DEFAULT_PREFS: list[str] = ["websocket", "email", "logger"]

    # --- Off-request delivery (FR-07) ---
    # Channels that leave this machine (sms, email) are handed to an
    # in-process worker instead of being sent inside the request, so a slow
    # gateway can no longer hold a response open — or, on the one ``async
    # def`` route that triggers alerts, hold the event loop.
    # Turning this off restores the old fully-synchronous dispatch, which is
    # the rollback lever if the worker ever misbehaves in production.
    NOTIFICATION_DELIVERY_ASYNC: bool = True
    NOTIFICATION_DELIVERY_WORKERS: int = Field(default=2, ge=1)
    # Refusing work beats queueing without bound: a gateway outage would
    # otherwise turn every queue mutation into retained memory. On overflow
    # dispatch falls through to the next *local* channel (in practice the
    # ``logger`` backstop) so the alert is still recorded, and the remote
    # send is parked below rather than abandoned.
    NOTIFICATION_DELIVERY_QUEUE_MAX: int = Field(default=1000, ge=1)
    # Overflow parking. Shed remote sends wait here for the queue to drain,
    # so a burst costs latency instead of costing the channel the user
    # actually chose. Set to 0 to drop shed sends outright.
    NOTIFICATION_DELIVERY_SHED_MAX: int = Field(default=500, ge=0)
    # ...but not forever. A "you're next" text that lands minutes late is
    # worse than none, because the customer has usually been served by
    # then, so a parked send is discarded once it goes stale.
    NOTIFICATION_DELIVERY_SHED_TTL_SECONDS: float = Field(default=120.0, gt=0)
    # One initial send plus three retries at ~1s, ~2s, ~4s. Sized against how
    # long a queue alert stays useful, not against how long a gateway might
    # be down — "you're next" is worthless ten minutes late.
    NOTIFICATION_DELIVERY_MAX_ATTEMPTS: int = Field(default=4, ge=1)
    NOTIFICATION_DELIVERY_RETRY_BASE_SECONDS: float = Field(default=1.0, gt=0)
    NOTIFICATION_DELIVERY_RETRY_MAX_SECONDS: float = Field(default=60.0, gt=0)
    NOTIFICATION_DELIVERY_RETRY_JITTER: float = Field(default=0.2, ge=0, lt=1)
    # How long shutdown waits for in-flight sends before dropping the rest.
    NOTIFICATION_DELIVERY_SHUTDOWN_SECONDS: float = Field(default=5.0, gt=0)

    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # US-SYS-00 OTP stub + KYC file storage (Cloudinary)
    OTP_TTL_MINUTES: int = 10
    # Preferred (dashboard → API Keys): cloudinary://<api_key>:<api_secret>@<cloud_name>
    CLOUDINARY_URL: str | None = None
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    CLOUDINARY_FOLDER: str = "werefa/kyc"
    CLOUDINARY_AVATARS_FOLDER: str = "werefa/avatars"
    MAX_UPLOAD_BYTES: int = 15 * 1024 * 1024
    MAX_AVATAR_BYTES: int = 5 * 1024 * 1024

    @staticmethod
    def parse_cloudinary_url(url: str) -> tuple[str, str, str]:
        """Parse ``cloudinary://key:secret@cloud_name`` from the dashboard."""
        raw = url.strip()
        prefix = "cloudinary://"
        if not raw.startswith(prefix):
            raise ValueError("CLOUDINARY_URL must start with cloudinary://")
        rest = raw[len(prefix) :]
        creds, sep, cloud_name = rest.rpartition("@")
        if not sep or not cloud_name:
            raise ValueError("CLOUDINARY_URL must end with @<cloud_name>")
        api_key, colon, api_secret = creds.partition(":")
        if not colon or not api_key or not api_secret:
            raise ValueError("CLOUDINARY_URL must be cloudinary://<api_key>:<api_secret>@<cloud_name>")
        return cloud_name, api_key, api_secret

    @model_validator(mode="after")
    def _apply_cloudinary_url(self) -> Self:
        if self.CLOUDINARY_URL:
            name, key, secret = self.parse_cloudinary_url(self.CLOUDINARY_URL)
            object.__setattr__(self, "CLOUDINARY_CLOUD_NAME", name)
            object.__setattr__(self, "CLOUDINARY_API_KEY", key)
            object.__setattr__(self, "CLOUDINARY_API_SECRET", secret)
        return self

    @property
    def cloudinary_configured(self) -> bool:
        return bool(
            self.CLOUDINARY_CLOUD_NAME
            and self.CLOUDINARY_API_KEY
            and self.CLOUDINARY_API_SECRET
        )

    # Optional — when set, the push notifier reports "delivered" for wiring tests.
    PUSH_DELIVERY_STUB_ENABLED: bool = False

    # --- SMS (FR-07) ---
    # Which gateway backs the ``sms`` notification channel. Built-ins are
    # "disabled", "console" (log-only, for local dev) and "twilio"; the name is
    # resolved against the registry in
    # ``notifications/infrastructure/sms/factory.py``, so a deployment can point
    # this at any adapter registered via ``register_sms_provider`` without a
    # code change here.
    SMS_PROVIDER: str = "disabled"
    # Country to assume for national numbers (``0911…`` → ``+251911…``). With
    # this unset, only numbers already stored in international form can be
    # texted — the rest are skipped rather than guessed at.
    SMS_DEFAULT_COUNTRY_CODE: str | None = None
    # 320 chars ≈ two GSM-7 segments. Bodies are truncated, not split further.
    # Constrained because a 0 or negative cap would silently send the whole
    # body — i.e. a typo'd env var turns into unbounded multi-segment bills
    # rather than a startup failure.
    SMS_MAX_BODY_CHARS: int = Field(default=320, ge=40)
    # Include the ticket deep link in the message text.
    SMS_INCLUDE_TICKET_LINK: bool = True
    # Per-send ceiling on the gateway round-trip. Sends now happen on the
    # delivery worker rather than in the request (see
    # ``NOTIFICATION_DELIVERY_ASYNC``), so this no longer bounds response
    # latency — it bounds how long one worker thread is tied up before the
    # attempt is called transient and retried.
    SMS_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0)

    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    # Sender: either a purchased number or (preferred in production) a
    # Messaging Service, which handles sender pools and per-country
    # compliance. The Messaging Service wins when both are set.
    TWILIO_FROM_NUMBER: str | None = None
    TWILIO_MESSAGING_SERVICE_SID: str | None = None
    # Overridable so tests and staging can point at a local fake.
    TWILIO_API_BASE_URL: str = "https://api.twilio.com"

    # Deprecated: superseded by ``SMS_PROVIDER=console``. Still honoured so
    # existing .env files keep working — see ``_apply_legacy_sms_stub_flag``.
    SMS_DELIVERY_STUB_ENABLED: bool = False

    @model_validator(mode="after")
    def _apply_legacy_sms_stub_flag(self) -> Self:
        if self.SMS_DELIVERY_STUB_ENABLED and self.SMS_PROVIDER == "disabled":
            warnings.warn(
                "SMS_DELIVERY_STUB_ENABLED is deprecated; "
                "set SMS_PROVIDER=console instead.",
                DeprecationWarning,
                stacklevel=1,
            )
            object.__setattr__(self, "SMS_PROVIDER", "console")
        return self

    @model_validator(mode="after")
    def _check_twilio_credentials(self) -> Self:
        """Fail at startup rather than at the first queue alert.

        A half-filled Twilio block otherwise surfaces as notifications
        quietly falling through to the logger channel, which is
        indistinguishable from "nobody has SMS in their prefs".
        """
        if self.SMS_PROVIDER != "twilio":
            return self
        missing = [
            name
            for name, value in (
                ("TWILIO_ACCOUNT_SID", self.TWILIO_ACCOUNT_SID),
                ("TWILIO_AUTH_TOKEN", self.TWILIO_AUTH_TOKEN),
            )
            if not value
        ]
        if not (self.TWILIO_FROM_NUMBER or self.TWILIO_MESSAGING_SERVICE_SID):
            missing.append("TWILIO_FROM_NUMBER or TWILIO_MESSAGING_SERVICE_SID")
        if missing:
            raise ValueError(
                "SMS_PROVIDER=twilio requires: " + ", ".join(missing)
            )
        return self

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
