"""
Type Definitions and Interfaces

Defines TypedDict classes for GitHub API data structures
similar to TypeScript interfaces.
"""

from typing import TypedDict, List, Optional
from datetime import datetime


class GitHubCommitAuthor(TypedDict, total=False):
    """GitHub commit author information"""
    name: Optional[str]
    email: Optional[str]
    date: Optional[str]


class GitHubCommitDetail(TypedDict, total=False):
    """GitHub commit detail information"""
    message: str
    author: GitHubCommitAuthor
    committer: GitHubCommitAuthor


class GitHubCommit(TypedDict, total=False):
    """GitHub commit from API"""
    sha: str
    commit: GitHubCommitDetail
    html_url: Optional[str]
    author: Optional[dict]
    committer: Optional[dict]


class GitHubRelease(TypedDict, total=False):
    """GitHub release information"""
    id: int
    tag_name: str
    name: Optional[str]
    body: Optional[str]
    draft: bool
    prerelease: bool
    created_at: Optional[str]
    published_at: Optional[str]
    html_url: Optional[str]
    tarball_url: Optional[str]
    zipball_url: Optional[str]


class GitHubReleaseCommit(TypedDict):
    """Combined release and commits data"""
    release: GitHubRelease
    commits: List[GitHubCommit]


class RepositoryData(TypedDict, total=False):
    """Repository data for database operations"""
    github_id: Optional[int]
    name: str
    owner: str
    full_name: Optional[str]
    html_url: Optional[str]
    stargazers_count: Optional[int]
    language: Optional[str]
    created_at: Optional[datetime]
