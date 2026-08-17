import re

src = open('static/app.js', encoding='utf-8').read()
ids = sorted(set(re.findall(r"id: '([^']+)'", src)))
print(f"共 {len(ids)} 个端口 ID:")
print(" ".join(ids))
