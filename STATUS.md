# x402 Weather API — Status

## 現在の状態: 本番稼働中

- **ネットワーク**: Base Mainnet (eip155:8453)
- **Facilitator**: CDP (Bazaar Discovery 対応)
- **ポート**: 4022
- **データソース**: Open-Meteo (APIキー不要、CC BY 4.0)

## エンドポイント

| EP | 価格 | 説明 |
|----|------|------|
| `GET /health` | 無料 | ヘルスチェック |
| `GET /weather/current?city=Tokyo` | $0.001 | 現在の天気 |
| `GET /weather/forecast?city=Tokyo&days=3` | $0.001 | 日次予報 |

## リリース履歴

- **2026-02-20**: 初回リリース
