# ちゃとた競馬AI

スマホからnetkeibaの出馬表URLを入力し、レース情報を取得するFlaskプロトタイプです。

## ローカル起動
python -m pip install -r requirements.txt
python server.py

## Render等のWebサービス
Build Command:
pip install -r requirements.txt

Start Command:
gunicorn server:app --bind 0.0.0.0:$PORT

## 注意
netkeiba等の外部サイトからデータを取得する場合は、対象サイトの利用規約・robots.txt・アクセス制限・データ利用条件を確認し、許可された範囲で利用してください。
このプロトタイプは外部サイトへの実接続がこの作業環境では検証されていません。
