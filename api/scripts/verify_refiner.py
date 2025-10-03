import json
import random

from api.refiner import refine_evidence
from api.schemas.refine_schema import RefineModel

SAMPLE = [
    ["$ABC listing on XYZ exchange at 12:00 UTC", "Pair ABC/USDT opened"],
    [
        "Token LMN announces mainnet launch next week",
        "Dev updates indicate feature freeze",
    ],
    ["Liquidity spike on DEX for PEPE/USDT", "Whale wallet accumulated 2M PEPE"],
    ["Solana RPC degraded", "Validator downtime affects swaps"],
    ["Project ZYX rug rumors", "GoPlus flags high tax"],
    ["BTC ETF inflows hit record", "Market sentiment turns positive"],
    ["Airdrop confirmed for holders", "Snapshot taken at block 123"],
    ["Exchange delists DEF", "Volume near zero"],
    ["Partnership announced", "No tokenomics change"],
    ["Bridge exploit mitigated", "Funds in multisig"],
]


def main():
    ok = 0
    latencies = []
    for ev in SAMPLE:
        out = refine_evidence(ev, hint="D6")
        RefineModel(**out)  # will raise if invalid
        print(json.dumps(out, ensure_ascii=False))
        ok += 1
    print(f"valid={ok}/{len(SAMPLE)}")


if __name__ == "__main__":
    main()
