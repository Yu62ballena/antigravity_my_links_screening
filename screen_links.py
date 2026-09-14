import os
import requests
import json
import random
import google.generativeai as genai
from dotenv import load_dotenv
import time

load_dotenv()

# --- 設定情報 ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATA_SOURCE_ID = os.getenv("DATA_SOURCE_ID")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Geminiの設定
genai.configure(api_key=GEMINI_API_KEY)
# 実質無料枠の広い gemini-2.5-flash を利用
model = genai.GenerativeModel('gemini-2.5-flash')

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2025-09-03"
}

def get_ai_curation(category_name, items, limit):
    """Geminiを使ってテーマ選定とコメント生成を行う"""
    if not items: return None

    item_list_text = "\n".join([f"- {'[あとで] ' if i['is_later'] else ''}{i['title']}" for i in items])
    
    prompt = f"""
    あなたは技術エディターです。以下の記事リストから、今読むべき「共通のテーマ」を1つ決め、
    それに合致する記事を最大{limit}件選んでください。[あとで]と付いているものは過去にストックした記事です。
    
    【{category_name} カテゴリの記事リスト】
    {item_list_text}
    
    【指示】
    1. リストから今回の切り口となる「テーマ」を決定してください。
    2. そのテーマに合う記事を選んでください。
    3. 各記事の見どころや概要を盛り込み、なぜ選んだのかが詳しく伝わる解説コメントを300〜450文字程度でしっかり作成してください（記事の中身がイメージできるボリューム感にしてください）。
    
    【出力形式（必ず以下のJSON形式のみで回答）】
    {{
      "theme": "今回のテーマ名",
      "comment": "まとめコメント内容",
      "selected_titles": ["選んだ記事のタイトル1", "選んだ記事のタイトル2"]
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        res_text = response.text.replace('```json', '').replace('```', '').strip()
        # 万が一JSONが壊れていた場合の最小限のクリーンアップ
        if not res_text.startswith('{'):
            res_text = res_text[res_text.find('{'):res_text.rfind('}')+1]
        return json.loads(res_text)
    except Exception as e:
        print(f"⚠️ {category_name}のAIキュレーション失敗: {e}")
        return None

def send_to_slack(message_text):
    payload = {"text": message_text}
    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=15)
    except Exception as e:
        print(f"⚠️ Slack送信失敗: {e}")

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
    try:
        response = requests.post(url, headers=HEADERS, json=filter_data, timeout=30)
        return response.json().get("results", []) if response.status_code == 200 else []
    except Exception as e:
        print(f"⚠️ Notionデータ取得失敗: {e}")
        return []

def update_page(page_id, category, is_later):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    properties = {"カテゴリー": {"select": {"name": category}}}
    properties["AI Status"] = {"select": {"name": "未処理" if is_later else "整理済み"}}
    try:
        requests.patch(url, headers=HEADERS, json={"properties": properties}, timeout=15)
    except Exception as e:
        print(f"⚠️ ページ更新失敗 (ID: {page_id}): {e}")

def classify_category(title, url):
    t = (title + url).lower()
    if any(kw in t for kw in ["ai", "claude", "gpt", "gemini", "genie", "llm", "生成"]): return "AI関連"
    if any(kw in t for kw in ["web", "python", "next.js", "udemy", "code", "api", "開発", "javascript", "react"]): return "Web関連"
    if any(kw in t for kw in ["davinci", "動画", "編集", "youtube", "sony", "α7", "レンズ", "写真", "カメラ", "映像"]): return "映像系"
    if any(kw in t for kw in ["guitar", "ギター", "effector", "jc-20", "テレキャス", "エフェクター"]): return "ギター系"
    if any(kw in t for kw in ["地図", "マップ", "tabelog", "場所"]): return "場所"
    if any(kw in t for kw in ["レシピ", "料理", "作り方", "recipe"]): return "レシピ"
    return "その他"

def run_screening():
    pages = get_target_pages()
    if not pages:
        print("✅ 対象記事はありませんでした。")
        return

    total = len(pages)
    categorized_data = {cat: [] for cat in ["AI関連", "Web関連", "映像系", "ギター系", "場所", "レシピ", "その他"]}
    
    print(f"� {total}件の処理を開始します...")

    for i, page in enumerate(pages, 1):
        try:
            props = page["properties"]
            
            # タイトル（名前）が空の場合のハンドリングを強化
            title_list = props.get("名前", {}).get("title", [])
            title = title_list[0].get("plain_text", "無題") if title_list else "無題"
            
            original_url = props.get("URL", {}).get("url") or ""
            is_later = props.get("あとで", {}).get("checkbox", False)
            
            category = classify_category(title, original_url)
            item = {"title": title, "url": page["url"], "id": page["id"], "is_later": is_later}
            categorized_data[category].append(item)
            
            # Notionのステータス更新
            update_page(page["id"], category, is_later)
            
            if i % 5 == 0 or i == total:
                print(f"  📊 進捗: {i}/{total} 件完了 ({(i/total*100):.1f}%)")
        except Exception as e:
            print(f"⚠️ 記事の処理中にエラー (ページ順序: {i}): {e}")
            continue

    # --- AIによるレポート作成 ---
    print("\n✍️ AIがキュレーションレポを作成中...")
    limits = {"AI関連": 5, "Web関連": 5, "映像系": 3, "ギター系": 3, "その他グループ": 3}
    report_msg = "════════════════════\n📱 AI編集長：今日のキュレーションレポート\n════════════════════\n"
    
    order = ["AI関連", "Web関連", "映像系", "ギター系"]
    
    for cat in order:
        items = categorized_data[cat]
        if not items: continue
        
        curation = get_ai_curation(cat, items, limits[cat])
        if curation:
            report_msg += f"\n【{cat}】テーマ：{curation['theme']}\n"
            report_msg += f"📝 {curation['comment']}\n\n"
            
            for title_picked in curation['selected_titles']:
                match = next((i for i in items if i["title"] in title_picked or title_picked in i["title"]), None)
                if match:
                    icon = "⏳ " if match["is_later"] else "・"
                    report_msg += f"{icon}{match['title']}\n   {match['url']}\n"
            report_msg += "────────────────────\n"

    others = categorized_data["場所"] + categorized_data["レシピ"] + categorized_data["その他"]
    if others:
        curation = get_ai_curation("場所・生活情報", others, limits["その他グループ"])
        if curation:
            report_msg += f"\n【生活・その他】テーマ：{curation['theme']}\n"
            report_msg += f"📝 {curation['comment']}\n\n"
            for title_picked in curation['selected_titles']:
                match = next((i for i in others if i["title"] in title_picked or title_picked in i["title"]), None)
                if match:
                    icon = "⏳ " if match["is_later"] else "・"
                    report_msg += f"{icon}{match['title']}\n   {match['url']}\n"
            report_msg += "────────────────────\n"

    report_msg += "\n════════════════════\n⏳ 印は「あとで」枠からのピックアップです。"

    send_to_slack(report_msg)
    print("\n✅ Slackにレポートを送信しました。")

if __name__ == "__main__":
    run_screening()
