"""Dev helper: mint a signed channel token for a party (requires CHANNEL_SIGNING_KEY in the environment).

Usage: CHANNEL_SIGNING_KEY=... python scripts/mint_channel_token.py P9
"""
import os
import sys

from claims_agent.channel_auth import mint

if __name__ == "__main__":
    print(mint(sys.argv[1], os.environ["CHANNEL_SIGNING_KEY"]))
