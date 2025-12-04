"""
Tortoise ORM Models

Defines database models for GitHub repositories, releases, and commits
using Tortoise ORM for async PostgreSQL operations.
"""

from tortoise import fields
from tortoise.models import Model


class Repository(Model):
    """
    Repository model representing a GitHub repository.
    """
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255)
    owner = fields.CharField(max_length=255)
    github_id = fields.BigIntField(unique=True, null=True)
    full_name = fields.CharField(max_length=255, null=True)
    html_url = fields.CharField(max_length=500, null=True)
    stargazers_count = fields.IntField(null=True)
    language = fields.CharField(max_length=100, null=True)
    created_at = fields.DatetimeField(null=True)
    
    class Meta:
        table = "repositories"
        unique_together = (("name", "owner"),)
        
    def __str__(self):
        return f"{self.owner}/{self.name}"


class Release(Model):
    """
    Release model representing a GitHub release.
    """
    id = fields.IntField(pk=True)
    repo = fields.ForeignKeyField(
        "models.Repository", 
        related_name="releases",
        on_delete=fields.CASCADE
    )
    tag_name = fields.CharField(max_length=100)
    release_name = fields.CharField(max_length=255, null=True)
    body = fields.TextField(null=True)
    published_at = fields.DatetimeField(null=True)
    html_url = fields.CharField(max_length=500, null=True)
    
    class Meta:
        table = "releases"
        unique_together = (("tag_name", "repo"),)
        
    def __str__(self):
        return f"{self.repo.full_name} - {self.tag_name}"


class Commit(Model):
    """
    Commit model representing a GitHub commit.
    """
    id = fields.IntField(pk=True)
    repo = fields.ForeignKeyField(
        "models.Repository",
        related_name="commits",
        on_delete=fields.CASCADE,
        null=True
    )
    release = fields.ForeignKeyField(
        "models.Release",
        related_name="commits",
        on_delete=fields.CASCADE,
        null=True
    )
    sha = fields.CharField(max_length=40, unique=True)
    message = fields.TextField(null=True)
    author_name = fields.CharField(max_length=255, null=True)
    date = fields.DatetimeField(null=True)
    html_url = fields.CharField(max_length=500, null=True)
    
    class Meta:
        table = "commits"
        
    def __str__(self):
        return f"{self.sha[:7]} - {self.message[:50] if self.message else 'No message'}"
