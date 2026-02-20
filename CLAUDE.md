# x402 Weather API プロジェクトルール

## プロジェクト概要

x402プロトコル（Coinbase開発）を使ったグローバル天気API。
AIエージェント向けに、世界中の都市の現在の天気と日次予報を
マイクロペイメント（$0.001/リクエスト、USDC on Base）で販売する。

データソース: Open-Meteo（APIキー不要、CC BY 4.0 商用OK）

## 技術スタック

- Python 3.10+ / FastAPI / x402 Python SDK v2
- パッケージ管理: uv
- 決済: x402 (EVM, Base, USDC)
- 天気データ: Open-Meteo API (httpx)
- 公開: Cloudflare Tunnel（自宅Linux PCから配信）

## 受取ウォレット

`0x29322Ea7EcB34aA6164cb2ddeB9CE650902E4f60`（Ethereum/Base共通アドレス）

## ネットワーク設定

- 本番: `eip155:8453`（Base Mainnet）← **現在の設定**
- テストネット: `eip155:84532`（Base Sepolia）

## Facilitator

- **CDP** (`api.cdp.coinbase.com/platform/v2/x402`) — JWT認証・Bazaar Discovery対応
- `cdp-sdk` パッケージの `create_facilitator_config()` で自動認証
- `CDP_API_KEY_ID` / `CDP_API_KEY_SECRET` 環境変数で認証

## 既知の技術的注意点

- `cdp-sdk` → `web3` → `nest_asyncio` が `asyncio.run` をパッチする
- uvicorn 0.41+ は `loop_factory` 引数を使うため、パッチ版と互換性がない
- `main.py` の `__main__` ブロックで `asyncio.runners.run` に復元して回避済み

## 現在のフェーズ

STATUS.md を参照。本番稼働中（Base Mainnet + CDP facilitator）。

## 禁止事項

- 秘密鍵・シードフレーズをコードやファイルに書くこと
- .envをgitにコミットすること（.gitignoreで除外済み）
- x402 SDKのバージョンを勝手に下げること（v2必須）

## ファイル構成

| ファイル | 役割 |
|---------|------|
| `main.py` | FastAPI + x402ミドルウェア + エンドポイント定義 |
| `weather.py` | Open-Meteo API呼び出し（ジオコーディング・天気・予報） |
| `self_pay.py` | Bazaar登録用セルフペイスクリプト |
| `pyproject.toml` | 依存関係 |
| `.env` | 設定（git管理外） |
| `STATUS.md` | 進捗・残タスク・手順書 |
| `tests/` | ユニットテスト + エンドポイントテスト |
