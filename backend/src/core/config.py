"""Configuración transversal del ERP basada en Pydantic Settings.

Centraliza las variables de entorno que consumen los módulos. Los valores por
defecto están alineados con ``docker-compose.yml`` y permiten arrancar en
desarrollo sin un ``.env``; en producción **deben** sobrescribirse
``JWT_SECRET_KEY``, ``CAPTCHA_SECRET_KEY`` y las credenciales del superusuario.

Convención: los campos usan el mismo nombre que la variable de entorno
(``JWT_SECRET_KEY``), por lo que ``pydantic-settings`` los resuelve sin alias.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import EmailStr, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql://erp_user:erp_password@localhost:5432/erp_database"


class Settings(BaseSettings):
    """Parámetros de configuración del backend.

    ``extra="ignore"`` evita fallos por variables de entorno ajenas al ERP
    (por ejemplo, las que inyecta el propio contenedor o el runner de CI).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Persistencia -----------------------------------------------------
    DATABASE_URL: str = DEFAULT_DATABASE_URL
    SQLALCHEMY_ECHO: bool = False

    # --- JWT --------------------------------------------------------------
    JWT_SECRET_KEY: str = Field(
        default="dev-jwt-secret-key-change-me-in-production-0001",
        min_length=32,
        description="Clave HMAC para firmar access/refresh tokens (HS256).",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=1)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, ge=1)

    # --- CAPTCHA stateless (itsdangerous) ---------------------------------
    CAPTCHA_SECRET_KEY: str = Field(
        default="dev-captcha-secret-key-change-me-in-production-0001",
        min_length=32,
        description="Clave HMAC dedicada para firmar los tokens de CAPTCHA.",
    )
    CAPTCHA_MAX_AGE_SECONDS: int = Field(default=180, ge=1)

    # --- Superusuario inicial (seeding) -----------------------------------
    FIRST_SUPERUSER_EMAIL: EmailStr = "admin@synapsisx.com"
    FIRST_SUPERUSER_USERNAME: str = Field(
        default="administrator",
        min_length=1,
        max_length=50,
        pattern=r"^[A-Za-z0-9]+$",
    )
    FIRST_SUPERUSER_PASSWORD: str = Field(
        default="Admin1234!", min_length=10, max_length=128
    )
    FIRST_SUPERUSER_FULL_NAME: str = "Administrador del Sistema"

    # --- Seeding ----------------------------------------------------------
    AUTO_SEED_USERS: bool = True

    @field_validator("FIRST_SUPERUSER_PASSWORD")
    @classmethod
    def _validate_superuser_password(cls, value: str) -> str:
        """Aplica la política mínima de contraseñas de la sección 4.2."""
        missing = [
            label
            for label, check in (
                ("una mayúscula", str.isupper),
                ("una minúscula", str.islower),
                ("un número", str.isdigit),
            )
            if not any(check(char) for char in value)
        ]
        if not any(not char.isalnum() for char in value):
            missing.append("un carácter especial")

        if missing:
            raise ValueError(
                "FIRST_SUPERUSER_PASSWORD debe incluir " + ", ".join(missing) + "."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """Devuelve una única instancia de ``Settings`` (cacheada por proceso)."""
    return Settings()


settings = get_settings()
