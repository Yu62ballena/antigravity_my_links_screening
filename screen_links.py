import requests
import json
import random
import os
from dotenv import load_dotenv

load_dotenv()

# --- 設定情報 ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATA_SOURCE_ID = os.getenv("DATA_SOURCE_ID")
# 【New】取得したSlack Webhook URLをここに貼ります
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
# --------------

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2025-09-03"
}

def send_to_slack(message_text):
    """Slackにメッセージを送信する関数"""
    payload = {"text": message_text}
    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if response.status_code == 200:
        print("✅ Slackへの送信が完了しました！")
    else:
        print(f"❌ Slack送信エラー: {response.status_code}\n{response.text}")

def get_target_pages():
    url = f"https://api.notion.com/v1/data_sources/{DATA_SOURCE_ID}/query"
    filter_data = {
        "filter": {
            "and": [
                {"property": "AI Status", "select": {"does_not_equal": "スキップ推奨"}},
                {"property": "ゆうの処理", "checkbox": {"equals": False}}
            ]
        }
    }
    response = requests.post(url, headers=HEADERS, json=filter_data)
    return response.json().get("results", []) if response.status_code == 200 else []

def update_page(page_id, category):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {
        "properties": {
            "AI Status": {"select": {"name": "整理済み"}},
            "カテゴリー": {"select": {"name": category}}
        }
    }
    requests.patch(url, headers=HEADERS, json=data)

def classify_category(title, url):
    t = (title + url).lower()
    if any(kw in t for kw in ["ai", "claude", "gpt", "gemini", "genie", "llm", "生成"]):
        return "AI関連"
    elif any(kw in t for kw in ["web", "python", "next.js", "udemy", "code", "api", "開発", "javascript", "react", "github", "zenn"]):
        return "Web関連"
    elif any(kw in t for kw in ["davinci", "動画", "編集", "youtube", "sony", "α7", "レンズ", "写真", "カメラ", "映像"]):
        return "映像系"
    elif any(kw in t for kw in ["guitar", "ギター", "effector", "jc-20", "テレキャス", "エフェクター"]):
        return "ギター系"
    elif any(kw in t for kw in ["地図", "マップ", "tabelog", "場所"]):
        return "場所"
    elif any(kw in t for kw in ["レシピ", "料理", "作り方", "recipe"]):
        return "レシピ"
    else:
        return "その他"

def get_importance_score(title):
    score = 0
    keywords = ["最新", "完全", "プロンプト", "自動", "開発", "活用", "決定版"]
    for kw in keywords:
        if kw in title: score += 1
    return score

def run_screening():
    pages = get_target_pages()
    if not pages:
        print("✅ 新しい未チェックの記事はありませんでした。")
        return

    all_categorized = {"AI関連": [], "Web関連": [], "映像系": [], "ギター系": [], "場所": [], "レシピ": [], "その他": []}
    
    print(f"🔍 {len(pages)}件を分類中...")

    for page in pages:
        page_id = page["id"]
        notion_url = page["url"]
        props = page["properties"]
        title_list = props.get("名前", {}).get("title", [])
        title = title_list[0]["plain_text"] if title_list else "無題"
        original_url = props.get("URL", {}).get("url") or ""
        
        category = classify_category(title, original_url)
        item = {"title": title, "url": notion_url, "score": get_importance_score(title)}
        all_categorized[category].append(item)
        
        update_page(page_id, category)

    # --- ピックアップ作成 ---
    limits = {"AI関連": 5, "Web関連": 5, "映像系": 3, "ギター系": 3, "その他グループ": 3}
    recommendations = {}
    for cat, items in all_categorized.items():
        random.shuffle(items)
        sorted_items = sorted(items, key=lambda x: x["score"], reverse=True)
        if cat in ["場所", "レシピ", "その他"]:
            if "その他グループ" not in recommendations: recommendations["その他グループ"] = []
            recommendations["その他グループ"].extend(sorted_items)
        else:
            recommendations[cat] = sorted_items[:limits[cat]]
    recommendations["その他グループ"] = sorted(recommendations["その他グループ"], key=lambda x: x["score"], reverse=True)[:limits["その他グループ"]]

    # --- メッセージ構築 ---
    report_msg = "════════════════════\n📱 ゆうさんへ：今夜のおすすめアイデア\n════════════════════\n"
    order = ["AI関連", "Web関連", "映像系", "ギター系", "その他グループ"]
    
    for cat in order:
        items = recommendations.get(cat, [])
        if items:
            display_name = cat if cat != "その他グループ" else "場所・レシピ・その他"
            report_msg += f"\n【{display_name}】\n"
            for i in items:
                prefix = "⭐ " if i["score"] > 0 else "・"
                report_msg += f"{prefix}{i['title']}\n   {i['url']}\n"
    
    report_msg += "\n════════════════════\n※各URLはNotion詳細ページへ飛びます。"

    # Slack送信
    send_to_slack(report_msg)
    print(report_msg)

if __name__ == "__main__":
    run_screening()
