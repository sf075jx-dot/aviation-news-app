import streamlit as st
import feedparser
import requests
from bs4 import BeautifulSoup
from google import genai
import time  # 連続アクセス制御 & リトライ用

# ---------------------------------------------------------
# 1. ページ初期設定 & 画面タイトル
# ---------------------------------------------------------
st.set_page_config(
    page_title="航空ニュースAIアナライザー (Gemini版)",
    page_icon="✈️",
    layout="wide"
)

st.title("✈️ 航空業界ニュース AI要約・記事生成ツール")
st.caption("最新の航空ニュースを取得し、Google Gemini APIが完全無料で業界向け要約レポートを自動作成します。")

# ---------------------------------------------------------
# 2. サイドバー（APIキー設定 & 条件指定）
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 設定")
    
    # Gemini APIキーの入力（Secrets設定があれば自動取得）
    api_key_input = st.text_input(
        "Gemini API Key",
        type="password",
        value=st.secrets.get("GEMINI_API_KEY", ""),
        help="Google AI Studio (https://aistudio.google.com/) から取得したAPIキーを入力してください。"
    )
    
    st.divider()
    
    # ニュース情報源の選択（RSSフィードURL）
    rss_dict = {
        "Aviation Wire（国内航空ニュース）": "https://www.aviationwire.jp/feed",
        "FlightGlobal（海外英語ニュース）": "https://www.flightglobal.com/rss/news",
    }
    selected_source = st.selectbox("ニュース情報源を選択", list(rss_dict.keys()))
    rss_url = rss_dict[selected_source]
    
    max_articles = st.slider("取得件数", min_value=1, max_value=5, value=3)

# ---------------------------------------------------------
# 3. 便利関数の定義
# ---------------------------------------------------------
def fetch_rss_news(url, max_items=3):
    """RSSフィードから最新ニュースを取得する"""
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:max_items]:
        # 本文のHTMLタグ除去
        summary_raw = entry.get("summary", entry.get("description", ""))
        clean_summary = BeautifulSoup(summary_raw, "html.parser").get_text()
        
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "published": entry.get("published", "日時不明"),
            "summary": clean_summary
        })
    return articles

def generate_ai_report(client, title, content):
    """Gemini API（gemini-3.8-flash）を使ってニュースのAI要約・分析記事を生成する"""
    prompt = f"""
あなたは航空業界専門のシニアアナリストです。
以下の航空関連ニュースを読み、業界実務担当者向けの要約レポートを作成してください。
※ニュースが英語の場合は、日本語に翻訳した上でレポートを作成してください。

【ニュースタイトル】
{title}

【ニュース概要・本文】
{content}

【出力フォーマット】
以下の構成（Markdown形式）で出力してください。
1. **📌 3行エグゼクティブサマリー**（重要なポイントを箇条書き3つで）
2. **🔍 業界へのインパクト・分析**（路線・運賃・旅客・競合動向などへの影響）
3. **🏷️ 関連タグ**（例: #JAL #燃油サーチャージ #国際線）
"""

    # サーバー一時混雑(503)対策: 最大3回まで5秒間隔でリトライ
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt
            )
            return response.text
        except Exception as e:
            if "503" in str(e) and attempt < 2:
                time.sleep(5)
                continue
            raise e

# ---------------------------------------------------------
# 4. メイン処理・UI表示
# ---------------------------------------------------------
if not api_key_input:
    st.warning("👈 サイドバーで Gemini API キーを入力してください。")
    st.info("💡 APIキーは [Google AI Studio](https://aistudio.google.com/) でクレジットカード登録なしで無料発行できます。")
    st.stop()

# Gemini クライアント初期化
client = genai.Client(api_key=api_key_input)

# 実行ボタン
if st.button("🔄 最新ニュースを取得してAI分析を実行", type="primary"):
    with st.spinner("ニュースを取得してGeminiがレポートを作成中..."):
        try:
            articles = fetch_rss_news(rss_url, max_items=max_articles)
            
            if not articles:
                st.error("ニュース記事が取得できませんでした。情報源のURLを確認してください。")
            else:
                st.success(f"{len(articles)} 件の最新記事を取得・分析しました！")
                
                # 取得した記事ごとにAIで要約生成・表示
                for idx, article in enumerate(articles, 1):
                    with st.expander(f"【記事{idx}】{article['title']}", expanded=True):
                        st.write(f"**元記事リンク:** [{article['title']}]({article['link']}) ({article['published']})")
                        
                        # AI要約生成
                        report = generate_ai_report(client, article['title'], article['summary'])
                        
                        st.markdown("---")
                        st.markdown(report)
                        
                        # 連続アクセス制御（レートリミット回避）のため3秒待機
                        if idx < len(articles):
                            time.sleep(3)
                        
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")