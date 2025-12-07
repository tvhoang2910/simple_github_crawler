import logging
from typing import List, Dict

class GitHubTokenRotator:
    """Manages rotation of GitHub tokens to maximize rate limits."""
    
    def __init__(self, tokens: List[str]):
        if not tokens:
            raise ValueError("At least one GitHub token is required")
        self.tokens = tokens
        self.current_index = 0
        self.token_stats = {token: {"requests": 0, "errors": 0} for token in tokens}
    
    def get_next_token(self) -> str:
        """Get the next token in rotation."""
        token = self.tokens[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.tokens)
        self.token_stats[token]["requests"] += 1
        return token
    
    def get_headers(self) -> Dict[str, str]:
        """Get headers with rotated token."""
        token = self.get_next_token()
        return {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {token}",
            "User-Agent": "GitHubCrawler/1.0"
        }
    
    def mark_error(self, token: str):
        """Mark a token as having encountered an error."""
        if token in self.token_stats:
            self.token_stats[token]["errors"] += 1
