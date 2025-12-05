import requests
from app.config import GITHUB_TOKENS

headers = {'Authorization': f'token {GITHUB_TOKENS[0]}'}
url = 'https://api.github.com/search/repositories?q=stars:>=50000&sort=stars&order=desc&per_page=10&page=1'

print(f"Using token: {GITHUB_TOKENS[0][:20]}...")
print(f"Requesting: {url}\n")

response = requests.get(url, headers=headers, timeout=10)
print(f"Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    print(f"Found {data.get('total_count', 0)} total repos")
    print(f"Items in response: {len(data.get('items', []))}")
    if data.get('items'):
        for i, repo in enumerate(data['items'][:3], 1):
            print(f"{i}. {repo['full_name']} - Stars: {repo['stargazers_count']}")
else:
    print(f"Error: {response.text}")
