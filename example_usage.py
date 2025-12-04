"""
Example usage script for Tortoise ORM database operations.

This demonstrates how to use the ServiceFactory and database_tortoise
modules to perform upsert operations on GitHub repository data.
"""

import asyncio
from service import ServiceFactory
from database_tortoise import upsert_repo_with_releases_and_commits


async def example_usage():
    """
    Example demonstrating how to initialize ORM and perform upsert operations.
    """
    # Initialize Tortoise ORM with models
    await ServiceFactory.init_orm(["models"], generate_schemas=True)
    
    try:
        # Example upsert operation
        result = await upsert_repo_with_releases_and_commits(
            owner="octocat",
            repo_name="Hello-World",
            releases_with_commits=[
                {
                    "release": {
                        "tag_name": "v1.0.0",
                        "body": "First release",
                        "published_at": "2023-01-01T00:00:00Z"
                    },
                    "commits": [
                        {
                            "sha": "abc123def456",
                            "commit": {
                                "message": "Initial commit",
                                "author": {
                                    "name": "Octocat",
                                    "date": "2023-01-01T00:00:00Z"
                                }
                            },
                            "html_url": "https://github.com/octocat/Hello-World/commit/abc123"
                        }
                    ]
                }
            ]
        )
        print(f"Upsert result: {result}")
        
    finally:
        # Always close connections
        await ServiceFactory.shutdown()


if __name__ == "__main__":
    asyncio.run(example_usage())
