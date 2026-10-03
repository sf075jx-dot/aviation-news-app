import streamlit as st
import feedparser
import requests
from bs4 import BeautifulSoup
from google import genai
import time
import urllib.parse

# ---------------------------------------------------------
# 1. ページ初期設定 & 画面タイトル
# ---------------------------------------------------------
st.set_page_config(
    page_title="マルチニュースAIアナライザー (Gemini版)",
    page_icon="✈️",
    layout="wide"
)

st.title("✈️ 航空業界・マルチニュース AI要約・記事生成ツール")
st.caption("様々なニュースサイトやキーワード検索から最新情報を自動取得し、Google Gemini APIが業界向け要約レポートを作成します。")

# ---------------------------------------------------------
# 2. サイドバー（APIキー設定 & 情報源選択）
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 設定")
    
    # Gemini APIキーの入力（Secrets設定があれば自動取得）
    api_key_input = st.text_input(
        "Gemini API Key",
        type="password",
        value=st.secrets.get("GEMINI_API_KEY", ""),
        help="Google AI Studio (https://aistudio.google.com/) で取得したAPIキーを入力してください。"
    )
    
    st.divider()
    
    # モード選択: キーワード検索 or プリセットサイト
    fetch_mode = st.radio(
        "取得モードを選択",
        ["🔍 キーワード自由検索 (Google News)", "🌐 専門サイト一覧から選択"]
    )
    
    rss_url = ""
    
    if fetch_mode == "🔍 キーワード自由検索 (Google News)":
        search_keyword = st.text_input("検索キーワード", value="航空")
        encoded_keyword = urllib.parse.quote(search_keyword)
        # Google News RSS (キーワード検索URL)
        rss_url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=ja&gl=JP&ceid=JP:ja"
        st.info(f"💡 WEB全体のメディアから「{search_keyword}」に関する最新記事を収集します。")
        
    else:
        # プリセットサイト一覧
        site_options = {
            "TRAICY (航空・旅行全般)": "https://www.traicy.com/feed",
            "乗りものニュース (交通・航空)": "https://trafficnews.jp/feed",
            "Aviation Wire (国内航空)": "https://www.aviationwire.jp/feed",
            "FlightGlobal (英語・海外航空)": "https://www.flightglobal.com/rss/news",
            "Google News (航空業界全般)": "https://news.google.com/rss/search?q=%E8%88%AA%E7%A9%BA&hl=ja&gl=JP&ceid=JP:ja"
        }
        selected_site = st.selectbox("情報源サイトを選択", list(site_options.keys()))
        rss_url = site_options[selected_site]
    
    st.divider()
    max_articles = st.slider("取得件数", min_value=1, max_value=5, value=3)

# ---------------------------------------------------------
# 3. 便利関数の定義
# ---------------------------------------------------------
def fetch_rss_news(url, max_items=3):
    """RSSフィード/Google Newsから最新ニュースを取得する（User-Agentヘッダー付き）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        feed = feedparser.parse(response.content)
    except Exception:
        feed = feedparser.parse(url)

    articles = []
    for entry in feed.entries[:max_items]:
        # 本文または概要の取得とHTMLタグ除去
        summary_raw = entry.get("summary", entry.get("description", ""))
        clean_summary = BeautifulSoup(summary_raw, "html.parser").get_text()
        
        # 本文が極端に短い場合の補填処理
        if len(clean_summary.strip()) < 10:
            clean_summary = entry.title
            
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "published": entry.get("published", entry.get("updated", "日時不明")),
            "summary": clean_summary
        })
    return articles

def generate_ai_report(client, title, content):
    """Gemini API（gemini-3.8-flash）を使ってニュースのAI要約・分析記事を生成する"""
    prompt = f"""
あなたは航空・交通業界専門のシニアアナリストです。
以下のニュース記事を読み、業界実務担当者向けの要約・分析レポートを作成してください。
※ニュースが英語の場合は、日本語に翻訳した上でレポートを作成してください。

【ニュースタイトル】
{title}

【ニュース概要・本文】
{content}

【出力フォーマット】
以下の構成（Markdown形式）で出力してください。
1. **📌 3行エグゼクティブサマリー**（重要なポイントを箇条書き3つで）
2. **🔍 業界へのインパクト・分析**（路線・運賃・旅客・競合動向などへの影響）
3. **🏷️️ 関連タグ**（例: #JAL #燃油サーチャージ #国際線）
"""

    # 503混雑時の最大3回自動リトライ
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
                st.error("ニュース記事が取得できませんでした。検索キーワードや情報源を確認してください。")
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
                        
                        # レートリミット回避のため3秒待機
                        if idx < len(articles):
                            time.sleep(3)
                        
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")