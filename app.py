import streamlit as st
import feedparser
import requests
from bs4 import BeautifulSoup
import urllib.parse
import json
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
st.caption("国内外の航空ニュースをスクレイピングし、他業界や経済への波及効果まで深掘り分析します。")

# Gemini API クライアント初期化（※分析機能専用）
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
# 3. 翻訳処理（Gemini完全不使用・2重バックアップ構造）
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def translate_title_without_gemini(text):
    """
    Gemini APIを絶対に使わずに日本語へ翻訳する関数。
    第1優先: Google Web Translate
    第2優先: MyMemory Free Translation API
    """
    if not text or not text.strip():
        return text

    # --- 方法1: Google Translate Web API ---
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "en",
            "tl": "ja",
            "dt": "t",
            "q": text
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(url, params=params, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            translated_parts = [item[0] for item in data[0] if item[0]]
            result_str = "".join(translated_parts)
            if result_str and result_str != text:
                return result_str
    except Exception:
        pass

    # --- 方法2: MyMemory Translation API（バックアップ） ---
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": text,
            "langpair": "en|ja"
        }
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json()
            translated_str = data.get("responseData", {}).get("translatedText", "")
            if translated_str and translated_str != text:
                return translated_str
    except Exception:
        pass

    return text

# ---------------------------------------------------------
# 4. Gemini API 関数（※詳細分析ボタン専用）
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def generate_gemini_summary(title, content, is_foreign=False):
    """他業界・経済への影響を含めた構造的分析記事を生成"""
    if not client:
        return "⚠️ Gemini APIキーが設定されていません。"
    
    lang_instruction = "※元のニュースは英語です。分析文言はすべて【自然で分かりやすい日本語】で執筆してください。" if is_foreign else ""

    prompt = f"""あなたは優秀な航空・産業アナリストです。
以下のニュースを多角的に分析し、航空業界内にとどまらない「経済・他業界への影響」を含めた質の高い考察レポートを作成してください。
{lang_instruction}

【ニュースタイトル】
{title}

【ニュース概要】
{content}

---
【出力フォーマット】
以下の見出しに沿って、箇条書きと簡潔な文章で回答してください。

■ 1. ニュースの概要（日本語要約）
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
# 5. スクレイピング & スポッターサイト除去
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
            "original_title": title,
            "source": source,
            "link": entry.link,
            "published": entry.get("published", "最新"),
            "summary": summary_raw if len(summary_raw.strip()) > 10 else title
        })
        if len(articles) >= max_items:
            break
            
    return articles

# ---------------------------------------------------------
# 6. メイン表示エリア
# ---------------------------------------------------------
col1, col2 = st.columns([3, 1])
with col1:
    st.subheader(f"📡 取得カテゴリ: `{search_category}`")
with col2:
    if st.button("🔄 最新に更新", type="primary"):
        st.cache_data.clear()

is_foreign = (region_mode == "🌐 海外・グローバルニュース (英語)")

with st.spinner("最新ニュースを取得・翻訳中..."):
    articles = fetch_news(query_text, region_mode, max_articles, exclude_spotter)

if not articles:
    st.warning("直近のニュースが見つかりませんでした。カテゴリやキーワードを変更してください。")
else:
    for idx, art in enumerate(articles, 1):
        # 海外ニュースの場合、Gemini不使用の二重バックアップ翻訳関数を実行
        if is_foreign:
            display_title = translate_title_without_gemini(art['original_title'])
        else:
            display_title = art['original_title']
        
        st.markdown(f"#### {idx}. [{display_title}]({art['link']})")
        
        if is_foreign:
            st.caption(f"🔤 原題: {art['original_title']} | 📰 出所: {art['source']} | 🕒 日時: {art['published']}")
        else:
            st.caption(f"📰 出所: {art['source']} | 🕒 日時: {art['published']}")
        
        with st.expander("📊 AI要約・経済影響分析を表示"):
            if st.button("📊 このニュースを詳細分析する", key=f"btn_{idx}"):
                with st.spinner("Geminiが経済・他業界への影響を分析中..."):
                    summary = generate_gemini_summary(art['original_title'], art['summary'], is_foreign=is_foreign)
                    st.markdown(summary)
            else:
                st.write("※ ボタンを押すと「他業界・経済への影響」の解説記事を表示します。")
        
        st.divider()
