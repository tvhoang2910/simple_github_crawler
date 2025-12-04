import asyncio
from typing import Optional
from urllib.parse import quote_plus

from tortoise import Tortoise

from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT


class ServiceFactory:
    _initialized: bool = False

    @staticmethod
    def _build_db_url(
        min_size: int = 1,
        max_size: int = 10,
        ssl: Optional[str] = None,
    ) -> str:
        user = quote_plus(DB_USER)
        pwd = quote_plus(DB_PASS or "")
        host = DB_HOST
        port = DB_PORT
        db = DB_NAME
        params = [f"min_size={min_size}", f"max_size={max_size}"]
        if ssl:
            params.append(f"ssl={ssl}")
        query = "&".join(params)
        return f"postgres://{user}:{pwd}@{host}:{port}/{db}?{query}"

    @staticmethod
    async def init_orm(
        models_modules: Optional[list[str]] = None,
        generate_schemas: bool = True
    ) -> None:
        """
        Initialize Tortoise ORM with database connection and models.
        
        Args:
            models_modules: List of module paths containing Tortoise models.
                           Default is ["models"] which loads models.py
            generate_schemas: Whether to automatically create tables. Default is True.
        
        Note:
            Connection pool is configured via _build_db_url() parameters.
            Uses UTF-8 encoding for PostgreSQL to support emoji and special characters.
        """
        if ServiceFactory._initialized:
            return

        db_url = ServiceFactory._build_db_url(min_size=5, max_size=20)
        modules = {"models": models_modules or ["models"]}

        await Tortoise.init(
            db_url=db_url,
            modules=modules,
            # Ensure UTF-8 encoding for emoji and special characters
            timezone="UTC"
        )
        
        # Create tables if they don't exist
        if generate_schemas:
            await Tortoise.generate_schemas(safe=True)
            
        ServiceFactory._initialized = True

    @staticmethod
    async def get_db():
        if not ServiceFactory._initialized:
            await ServiceFactory.init_orm()
        return Tortoise.get_connection("default")

    @staticmethod
    async def shutdown() -> None:
        if ServiceFactory._initialized:
            await Tortoise.close_connections()
            ServiceFactory._initialized = False


# Ví dụ dùng trong script sync:
# asyncio.run(ServiceFactory.init_orm(["models"]))
# ... chạy nghiệp vụ ...
# asyncio.run(ServiceFactory.shutdown())