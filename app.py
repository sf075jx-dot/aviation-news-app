import streamlit as st
import feedparser
import requests
from bs4 import BeautifulSoup
import urllib.parse
from difflib import SequenceMatcher
import os
from google import genai

# ---------------------------------------------------------
# 1. ページ基本設定（スマホ対応レスポンシブ）
# ---------------------------------------------------------
st.set_page_config(
    page_title="航空ニュース・アナライザー",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.title("✈️ 航空ニュース・アナライザー")
st.caption("国内外の航空ニュースをスクレイピングし、Gemini APIで他業界・経済への波及効果まで深掘り分析します。")

# Gemini API クライアント初期化（Streamlit Secrets 優先、次点で環境変数）
api_key = st.secrets.get("GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
client = genai.Client(api_key=api_key) if api_key else None

if not api_key:
    st.warning("⚠️ `GEMINI_API_KEY` が設定されていません。Streamlit Community Cloudの Secrets または環境変数にAPIキーを設定してください。")

# ---------------------------------------------------------
# 2. サイドバー（条件指定）
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ ニュース検索条件")
    region_mode = st.radio("対象エリア", ["🇯🇵 日本国内ニュース", "🌐 海外・グローバルニュース (英語)"])
    
    search_category = st.selectbox(
        "検索カテゴリ",
        [
            "⚠️ 航空事故・インシデント・安全・トラブル",
            "航空会社・運航（JAL / ANA / LCC / 路線）",
            "エアライン経営・国際線・燃油サーチャージ",
            "機材・製造（ボーイング / エアバス / 新型機）",
            "空港・グランドハンドリング・管制・整備",
            "✏️ 自由キーワード指定"
        ]
    )
    
    if search_category == "✏️ 自由キーワード指定":
        query_text = st.text_input("キーワードを入力", value="航空 事故")
    else:
        category_map_ja = {
            "⚠️ 航空事故・インシデント・安全・トラブル": "航空事故 インシデント 欠航 トラブル 安全運航",
            "航空会社・運航（JAL / ANA / LCC / 路線）": "航空 JAL ANA LCC 路線",
            "エアライン経営・国際線・燃油サーチャージ": "航空 燃油サーチャージ 国際線 運賃",
            "機材・製造（ボーイング / エアバス / 新型機）": "ボーイング エアバス 旅客機 航空機",
            "空港・グランドハンドリング・管制・整備": "空港 管制 整備 グランドハンドリング 航空"
        }
        category_map_en = {
            "⚠️ 航空事故・インシデント・安全・トラブル": "aviation accident incident emergency safety crash",
            "航空会社・運航（JAL / ANA / LCC / 路線）": "airlines aviation flight route",
            "エアライン経営・国際線・燃油サーチャージ": "airline finance fare fuel surcharge international flight",
            "機材・製造（ボーイング / エアバス / 新型機）": "Boeing Airbus aircraft passenger plane",
            "空港・グランドハンドリング・管制・整備": "airport ATC maintenance ground handling"
        }
        query_text = category_map_ja[search_category] if region_mode == "🇯🇵 日本国内ニュース" else category_map_en[search_category]

    max_articles = st.slider("表示件数", min_value=3, max_value=15, value=5)
    exclude_spotter = st.checkbox("写真・スポッター系サイトを除外", value=True)

# ---------------------------------------------------------
# 3. Gemini API アナリスト要約（キャッシュ & 拡張プロンプト）
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def generate_gemini_summary(title, content):
    """他業界・経済への影響を含めた構造的分析記事を生成"""
    if not client:
        return "⚠️ Gemini APIキーが設定されていません。"
    
    prompt = f"""あなたは優秀な航空・産業アナリストです。
以下のニュースを多角的に分析し、航空業界内にとどまらない「経済・他業界への影響」を含めた質の高い考察レポートを作成してください。

【ニュースタイトル】
{title}

【ニュース概要】
{content}

---
【出力フォーマット】
以下の見出しに沿って、箇条書きと簡潔な文章で回答してください。

■ 1. ニュースの要約
・出来事の要点を2〜3行で簡潔にまとめてください。

■ 2. 航空業界内への影響
・運航、経営、安全、顧客体験等への直接的なインパクト。

■ 3. 他業界・経済への波及効果
・サプライチェーン、観光・ホテル、物流、燃料・エネルギー、関連産業や景気動向などへの波及。

■ 4. 今後の展望・注目ポイント
・この出来事をきっかけに今後どのような変化が予想されるか、次に注視すべき動向。
"""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        return f"分析レポートの生成に失敗しました: {e}"

# ---------------------------------------------------------
# 4. スクレイピング & スポッターサイト除去
# ---------------------------------------------------------
NG_DOMAINS = ["flyteam.jp", "planespotters.net", "jetphotos.com", "airliners.net"]
NG_KEYWORDS = ["FlyTeam", "航空フォト", "機材写真", "特別塗装機", "PlaneSpotters", "JetPhotos"]

def is_spotter_site(title, source, link):
    """写真メイン・スポッター系サイトを判定"""
    return any(d in link.lower() for d in NG_DOMAINS) or any(k.lower() in source.lower() or k.lower() in title.lower() for k in NG_KEYWORDS)

def fetch_news(query, region_mode, max_items, filter_spotter):
    """Google News RSS からニュースを取得"""
    encoded_query = urllib.parse.quote(f"{query} when:3d")
    hl_gl = "hl=ja&gl=JP&ceid=JP:ja" if region_mode == "🇯🇵 日本国内ニュース" else "hl=en-US&gl=US&ceid=US:en"
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&{hl_gl}"
    
    feed = feedparser.parse(rss_url)
    articles = []
    
    for entry in feed.entries:
        title = entry.title.rsplit(" - ", 1)[0] if " - " in entry.title else entry.title
        source = entry.title.rsplit(" - ", 1)[1] if " - " in entry.title else "不明"
        
        if filter_spotter and is_spotter_site(title, source, entry.link):
            continue
            
        summary_raw = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text()
        articles.append({
            "title": title,
            "source": source,
            "link": entry.link,
            "published": entry.get("published", "最新"),
            "summary": summary_raw if len(summary_raw.strip()) > 10 else title
        })
        if len(articles) >= max_items:
            break
            
    return articles

# ---------------------------------------------------------
# 5. メイン表示エリア
# ---------------------------------------------------------
col1, col2 = st.columns([3, 1])
with col1:
    st.subheader(f"📡 取得カテゴリ: `{search_category}`")
with col2:
    if st.button("🔄 最新に更新", type="primary"):
        st.cache_data.clear()

with st.spinner("最新ニュースを取得中..."):
    articles = fetch_news(query_text, region_mode, max_articles, exclude_spotter)

if not articles:
    st.warning("直近のニュースが見つかりませんでした。カテゴリやキーワードを変更してください。")
else:
    for idx, art in enumerate(articles, 1):
        st.markdown(f"#### {idx}. [{art['title']}]({art['link']})")
        st.caption(f"📰 出所: {art['source']} | 🕒 日時: {art['published']}")
        
        # API消費を抑えるオンデマンド展開エリア
        with st.expander("📊 AI経済波及効果・アナリスト分析を表示"):
            if st.button(f"このニュースを詳細分析する", key=f"btn_{idx}"):
                with st.spinner("Geminiが経済・他業界への影響を分析中..."):
                    summary = generate_gemini_summary(art['title'], art['summary'])
                    st.markdown(summary)
            else:
                st.write("※ ボタンを押すと「他業界・経済への影響」を含めた解説記事を生成します。")
        
        st.divider()
