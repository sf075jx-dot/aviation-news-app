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
    page_title="航空業界AIニュースアナライザー",
    page_icon="✈️",
    layout="wide"
)

st.title("✈️ 航空業界 AIニュースアナライザー & レポート生成")
st.caption("国内外の航空事故・インシデント・業界ニュースをワイドに自動収集し、Gemini APIが要約・リスク分析・簡易記事を作成します。")

# ---------------------------------------------------------
# 2. サイドバー（設定 & 検索条件）
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 設定")
    
    # Gemini APIキーの入力（Secrets自動取得対応）
    api_key_input = st.text_input(
        "Gemini API Key",
        type="password",
        value=st.secrets.get("GEMINI_API_KEY", ""),
        help="Google AI Studio (https://aistudio.google.com/) の無料キーを入力してください。"
    )
    
    st.divider()
    st.subheader("🌐 対象エリア選択")
    region_mode = st.radio(
        "検索対象エリア",
        ["🇯🇵 日本国内メイン", "🌐 海外・グローバル（自動日本語翻訳）"]
    )
    
    st.divider()
    st.subheader("🔍 ニュース検索設定")
    
    # 検索テーマ（キーワード）の選択・入力
    search_category = st.selectbox(
        "検索カテゴリ",
        [
            "⚠️ 航空事故・インシデント・安全運航・トラブル",
            "航空業界全般（JAL / ANA / LCC / 航空路線）",
            "エアライン経営・国際線・燃油サーチャージ",
            "新型旅客機・ボーイング・エアバス（機材・製造）",
            "空港・グランドハンドリング・管制・運航整備",
            "✏️ 自由キーワード指定"
        ]
    )
    
    if search_category == "✏️ 自由キーワード指定":
        user_keyword = st.text_input("検索キーワードを入力", value="航空 事故")
        query_text = user_keyword
    else:
        # カテゴリに応じたキーワードマッピング（海外検索用にも最適化）
        if region_mode == "🇯🇵 日本国内メイン":
            category_map = {
                "⚠️ 航空事故・インシデント・安全運航・トラブル": "航空事故 インシデント 欠航 トラブル 安全運航",
                "航空業界全般（JAL / ANA / LCC / 航空路線）": "航空 JAL ANA LCC 路線",
                "エアライン経営・国際線・燃油サーチャージ": "航空 燃油サーチャージ 国際線 運賃",
                "新型旅客機・ボーイング・エアバス（機材・製造）": "ボーイング エアバス 旅客機 航空機",
                "空港・グランドハンドリング・管制・運航整備": "空港 管制 整備 グランドハンドリング 航空"
            }
        else:
            category_map = {
                "⚠️ 航空事故・インシデント・安全運航・トラブル": "aviation accident incident emergency safety crash",
                "航空業界全般（JAL / ANA / LCC / 航空路線）": "airlines aviation flight route",
                "エアライン経営・国際線・燃油サーチャージ": "airline finance fare fuel surcharge international flight",
                "新型旅客機・ボーイング・エアバス（機材・製造）": "Boeing Airbus aircraft passenger plane",
                "空港・グランドハンドリング・管制・運航整備": "airport ATC maintenance ground handling"
            }
        query_text = category_map[search_category]
    
    max_articles = st.slider("取得・要約件数", min_value=1, max_value=5, value=3)

# ---------------------------------------------------------
# 3. ニュース検索 ＆ AI処理関数
# ---------------------------------------------------------
def search_web_news(query, region_mode, max_items=3):
    """Google News RSS連携を利用して国内外からニュースを収集"""
    encoded_query = urllib.parse.quote(query)
    
    if region_mode == "🇯🇵 日本国内メイン":
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ja&gl=JP&ceid=JP:ja"
    else:
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(rss_url, headers=headers, timeout=10)
        feed = feedparser.parse(response.content)
    except Exception:
        feed = feedparser.parse(rss_url)

    articles = []
    for entry in feed.entries[:max_items]:
        summary_raw = entry.get("summary", entry.get("description", ""))
        clean_summary = BeautifulSoup(summary_raw, "html.parser").get_text()
        
        if len(clean_summary.strip()) < 15:
            clean_summary = f"タイトル: {entry.title}"
            
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "published": entry.get("published", entry.get("updated", "最新")),
            "summary": clean_summary
        })
    return articles

def generate_ai_report(client, title, content):
    """Gemini API（gemini-3.8-flash）を使用した要約・リスク分析・記事作成"""
    prompt = f"""
あなたは航空業界専門のシニアアナリスト兼リスク管理専門家です。
以下の航空関連ニュース（事故・インシデント・運航・経営等）を読み込み、業界実務者向けの「要約」「業界インパクト・安全面へのリスク分析」「簡易ニュース解説記事」を作成してください。
※ニュースが英語の場合は、必ず自然で分かりやすい日本語に翻訳した上でレポートを作成してください。

【ニュースタイトル】
{title}

【ニュース本文・概要】
{content}

【出力フォーマット】
以下のMarkdown構成で出力してください。

### 📌 1. 重要ポイント（3行サマリー）
- 

### 🔍 2. 業界へのインパクト・リスク分析
（運航安全面への影響、ダイヤ乱れ・損害、業界・競合への影響、規制や再発防止策の動きなどを専門的視点で解説）

### 📝 3. 簡易ニュース解説記事
（社内共有や速報レポートとしてそのまま使えるような200〜300字程度の読みやすいニュース解説記事）

### 🏷 関連キーワード・タグ
"""

    # レートリミット(429)や混雑(503)発生時の自動再試行ループ
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt
            )
            return response.text
        except Exception as e:
            err_msg = str(e)
            # 429 (1分5回のリクエスト枠超過) が出たら30秒待機して自動リトライ
            if "429" in err_msg and attempt < 2:
                time.sleep(30)
                continue
            # 503 (サーバー一時高負荷) が出たら5秒待機して自動リトライ
            elif "503" in err_msg and attempt < 2:
                time.sleep(5)
                continue
            raise e

# ---------------------------------------------------------
# 4. メイン処理 & プログレス表示
# ---------------------------------------------------------
if not api_key_input:
    st.warning("👈 サイドバーで Gemini API キーを入力してください。")
    st.info("💡 キーは [Google AI Studio](https://aistudio.google.com/) で完全無料発行できます。")
    st.stop()

# Gemini クライアント初期化
client = genai.Client(api_key=api_key_input)

if st.button("🚀 最新ニュースを検索してAIレポートを生成", type="primary"):
    with st.spinner(f"🌐 [{region_mode}] 最新ニュースを検索中..."):
        articles = search_web_news(query_text, region_mode, max_items=max_articles)
        
    if not articles:
        st.error("ニュースの取得に失敗しました。検索キーワードやエリアを変更して再実行してください。")
    else:
        st.success(f"「{query_text}」に関する最新ニュースを {len(articles)} 件発見しました！要約・分析処理を開始します。")
        
        # 全体処理のプログレスバー
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, article in enumerate(articles, 1):
            status_text.text(f"🤖 記事 {idx}/{len(articles)} を Gemini API で要約・分析中...")
            
            with st.expander(f"【記事{idx}】{article['title']}", expanded=True):
                st.write(f"🔗 **元記事:** [{article['title']}]({article['link']})（{article['published']}）")
                
                # Gemini処理呼び出し
                start_time = time.time()
                report = generate_ai_report(client, article['title'], article['summary'])
                elapsed_time = round(time.time() - start_time, 1)
                
                st.markdown("---")
                st.markdown(report)
                st.caption(f"⚡ AI生成完了時間: 約 {elapsed_time} 秒")
                
            # 進捗更新
            progress_bar.progress(idx / len(articles))
            
            # 無料枠のレート制限（1分5回まで）に触れないよう、記事間に13秒の待機・カウントダウンを表示
            if idx < len(articles):
                countdown_placeholder = st.empty()
                for wait_sec in range(13, 0, -1):
                    countdown_placeholder.info(f"⏳ 無料枠のAPI連続リクエスト制限（5回/分）を回避するため、次の記事処理まで待機中... あと {wait_sec} 秒")
                    time.sleep(1)
                countdown_placeholder.empty()
                
        status_text.text("✨ すべてのニュースの要約・リスク分析レポート生成が完了しました！")