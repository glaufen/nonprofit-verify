from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://nonprofit:nonprofit@localhost:5432/nonprofit_verify"
    redis_url: str = "redis://localhost:6379/0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cache_ttl_seconds: int = 7 * 24 * 3600  # 7 days
    cache_404_ttl_seconds: int = 24 * 3600  # 24 hours
    free_tier_monthly_limit: int = 100
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_pro_price_id: str = ""
    stripe_enterprise_price_id: str = ""
    base_url: str = "http://localhost:8000"

    model_config = {"env_file": ".env"}


settings = Settings()
