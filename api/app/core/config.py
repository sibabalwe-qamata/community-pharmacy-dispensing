from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://formulary:formulary@db:5432/formulary"
    test_database_url: str = "postgresql+psycopg://formulary:formulary@db:5432/formulary_test"

    api_prefix: str = "/api/v1"
    business_timezone: str = "Africa/Johannesburg"
    window_days: int = 30

    default_page_size: int = 25
    max_page_size: int = 100

    # Seed volumes, per the brief's data-volume requirement.
    seed_medicines: int = 500
    seed_dispenses: int = 2000
    seed_patients: int = 2000


@lru_cache
def get_settings() -> Settings:
    return Settings()
