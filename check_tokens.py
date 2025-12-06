import requests
from datetime import datetime


def check_token_rate_limit(token: str) -> dict:
    """Check rate limit for a single GitHub token."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}",
        "User-Agent": "GitHubCrawler/1.0",
    }

    try:
        # Make a simple API call to check rate limit
        response = requests.get(
            "https://api.github.com/rate_limit", headers=headers, timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            rate_limit = data.get("rate", {})

            return {
                "limit": rate_limit.get("limit"),
                "remaining": rate_limit.get("remaining"),
                "reset": rate_limit.get("reset"),
                "reset_time": datetime.fromtimestamp(
                    rate_limit.get("reset", 0)
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "status": "OK",
            }
        else:
            return {
                "status": f"ERROR {response.status_code}",
                "message": response.text[:100],  # Truncate long error messages
            }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


def main():
    # Load tokens from environment variable or .env file
    from app.config import GITHUB_TOKENS
    
    # Use tokens from config
    tokens = GITHUB_TOKENS
    
    if not tokens:
        print("Error: No GitHub tokens found in environment variables (GITHUB_TOKENS)")
        print("Please add tokens to your .env file or export them as environment variable")
        return

    print("Checking GitHub token rate limits...\n")
    print("=" * 80)

    total_remaining = 0
    valid_tokens = 0

    for i, token in enumerate(tokens, 1):
        print(f"Token {i}: ...{token[-4:]}")
        result = check_token_rate_limit(token)

        if result["status"] == "OK":
            remaining = result["remaining"]
            limit = result["limit"]
            reset_time = result["reset_time"]

            total_remaining += remaining
            valid_tokens += 1

            print("  Status: ✅ Valid")
            print(f"  Limit: {limit}")
            print(f"  Remaining: {remaining}")
            print(f"  Reset Time: {reset_time}")

            # Calculate percentage
            if limit > 0:
                percentage = (remaining / limit) * 100
                print(f"  Usage: {percentage:.1f}%")
            print()
        else:
            print("  Status: ❌ Invalid")
            print(f"  Error: {result['message']}")
            print()

        print("-" * 40)

    print("=" * 80)
    print("Summary:")
    print(f"  Valid tokens: {valid_tokens}/{len(tokens)}")
    print(f"  Total remaining requests: {total_remaining}")
    if valid_tokens > 0:
        print(f"  Average remaining per token: {total_remaining // valid_tokens}")
    print("=" * 80)


if __name__ == "__main__":
    main()
