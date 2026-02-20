"""
Self-pay script — Trigger Bazaar cataloging by making one payment to your own API.

Prerequisites:
  1. A wallet with USDC on Base Mainnet (even $0.001 = 1000 atomic units is enough)
  2. Set EVM_PRIVATE_KEY env var with the wallet's private key
  3. The API server must be running and accessible at the URL below

Usage:
  export EVM_PRIVATE_KEY="0x..."
  python self_pay.py

What happens:
  1. Sends GET to /weather/current → receives 402 with payment requirements
  2. x402 client auto-creates a USDC payment signature (EIP-3009, gasless for payer)
  3. Retries request with payment → CDP facilitator verifies + settles
  4. CDP facilitator catalogs the API on Bazaar Discovery during settlement
  5. API becomes discoverable by AI agents worldwide
"""

import asyncio
import os
import sys

from eth_account import Account

from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client

# --- Config ---
API_URL = os.getenv("WEATHER_API_URL", "http://localhost:4022")
PRIVATE_KEY = os.getenv("EVM_PRIVATE_KEY")

if not PRIVATE_KEY:
    print("ERROR: Set EVM_PRIVATE_KEY environment variable")
    print("  export EVM_PRIVATE_KEY='0x...'")
    sys.exit(1)


async def main():
    # Create x402 client with wallet signer
    client = x402Client()
    account = Account.from_key(PRIVATE_KEY)
    register_exact_evm_client(client, EthAccountSigner(account))

    # Detect same-address (CDP facilitator rejects from == to)
    server_address = os.getenv("EVM_ADDRESS", "")
    if server_address and account.address.lower() == server_address.lower():
        print("ERROR: Payer address == server EVM_ADDRESS (same wallet)")
        print("  CDP facilitator rejects from == to payments.")
        print("  See playbook 地雷 #11 for the temporary-wallet workaround.")
        sys.exit(1)

    print(f"Payer wallet: {account.address}")
    print(f"Target API:   {API_URL}")
    print()

    endpoints = [
        "/weather/current?city=Tokyo",
        "/weather/forecast?city=Tokyo&days=3",
    ]

    async with x402HttpxClient(client) as http:
        for ep in endpoints:
            url = f"{API_URL}{ep}"
            print(f"--- {ep} ---")
            response = await http.get(url)
            print(f"Status: {response.status_code}")
            print(f"Body:   {response.text[:200]}")
            print()

    print("Done! Both endpoints should now be cataloged on Bazaar.")
    print("Check: https://www.x402.org/ecosystem")


if __name__ == "__main__":
    asyncio.run(main())
