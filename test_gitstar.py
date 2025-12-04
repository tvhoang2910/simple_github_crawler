#!/usr/bin/env python
"""
Test script để verify Gitstar fetcher hoạt động
"""

import sys
from crawler import fetch_repos_from_gitstar


def test_gitstar_fetch():
    """Test fetching repos from Gitstar"""
    print("Testing Gitstar fetcher...")
    print("-" * 60)

    try:
        # Test with limit=10 (để fetch nhanh)
        repos = fetch_repos_from_gitstar(limit=10)

        print(f"\n✅ Successfully fetched {len(repos)} repos from Gitstar")
        print("\nSample repos:")
        for i, repo in enumerate(repos[:5], 1):
            print(f"  {i}. {repo}")

        return True
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_gitstar_fetch()
    sys.exit(0 if success else 1)
