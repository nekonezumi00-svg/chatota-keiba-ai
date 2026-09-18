# ちゃとた競馬AI v9

v8の「4,5,6,7頭しか出ない」問題を修正。
ページ内で見つかった候補グループを比較し、最初の小さなグループではなく、最も多い2〜18頭の馬詳細リンク集合を採用します。

Render Start Command:
gunicorn server:app --bind 0.0.0.0:$PORT
