import logging
import requests
from typing import List, Dict, Optional
from app.metrics import TOKEN_SWITCH_COUNT


class GitHubTokenRotator:
    """Manages rotation of GitHub tokens to maximize rate limits."""

    def __init__(self, tokens: List[str]):
        if not tokens:
            raise ValueError("At least one GitHub token is required")
        self.tokens = tokens
        self.current_index = 0
        self.token_stats = {
            token: {"requests": 0, "errors": 0, "exhausted": False} for token in tokens
        }

    def check_rate_limit(self, token: str) -> int:
        """Check remaining rate limit for a token."""
        try:
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"token {token}",
                "User-Agent": "GitHubCrawler/1.0",
            }
            response = requests.get(
                "https://api.github.com/rate_limit", headers=headers, timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("rate", {}).get("remaining", 0)
            else:
                return 0
        except Exception:
            return 0

    def get_next_token(self) -> Optional[str]:
        """Get the next available token in rotation, skipping exhausted ones."""
        start_index = self.current_index
        checked_count = 0

        while checked_count < len(self.tokens):
            token = self.tokens[self.current_index]

            # Skip if already marked as exhausted
            if self.token_stats[token]["exhausted"]:
                self.current_index = (self.current_index + 1) % len(self.tokens)
                checked_count += 1
                continue

            # Check current rate limit
            remaining = self.check_rate_limit(token)
            if remaining <= 10:  # Buffer of 10 requests
                logging.warning(
                    f"Token ...{token[-4:]} exhausted (remaining: {remaining}), skipping"
                )
                self.token_stats[token]["exhausted"] = True
                self.current_index = (self.current_index + 1) % len(self.tokens)
                checked_count += 1
                continue

            # Token is good to use
            self.current_index = (self.current_index + 1) % len(self.tokens)
            self.token_stats[token]["requests"] += 1
            TOKEN_SWITCH_COUNT.inc()

            logging.info(
                "Token rotated",
                extra={
                    "event": "Switch Token",
                    "token_mask": f"...{token[-4:]}",
                    "total_requests": self.token_stats[token]["requests"],
                    "remaining": remaining,
                },
            )
            return token

        # All tokens exhausted
        logging.error("All GitHub tokens are exhausted!")
        return None

    def get_headers(self) -> Optional[Dict[str, str]]:
        """Get headers with rotated token."""
        token = self.get_next_token()
        if token is None:
            return None
        return {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {token}",
            "User-Agent": "GitHubCrawler/1.0",
        }

    def mark_error(self, token: str):
        """Mark a token as having encountered an error."""
        if token in self.token_stats:
            self.token_stats[token]["errors"] += 1

    def reset_exhausted_tokens(self):
        """Reset exhausted status for all tokens (call this after rate limit reset)."""
        for token in self.tokens:
            self.token_stats[token]["exhausted"] = False
