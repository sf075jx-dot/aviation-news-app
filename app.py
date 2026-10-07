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

# Gemini API クライアント初期化（※記事分析ボタンでのみ使用）
api_key = st.secrets.get("GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
client = genai.Client(api_key=api_key) if api_key else None

if not api_key:
    st.warning("⚠️ `GEMINI_API_KEY` が設定されていません。Streamlit Community Cloudの Secrets または環境変数にAPIキーを設定してください。")

# ---------------------------------------------------------
# 2. サイドバー（ジャンル表示と検索設定）
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ ニュース検索条件")
    region_mode = st.radio("対象エリア", ["🇯🇵 日本国内ニュース", "🌐 海外・グローバルニュース (英語)"])
    
    genre_list = [
        "⚠️ 航空事故・インシデント・安全",
        "✈️ 航空会社・路線・運航動向",
        "📈 エアライン経営・業績・燃油サーチャージ",
        "🛠️ 機材・航空機製造（ボーイング/エアバス）",
        "🏢 空港・グランドハンドリング・管制・整備",
        "✏️ 自由キーワード指定"
    ]
    
    selected_genre = st.selectbox("検索ジャンル", genre_list)
    
    if selected_genre == "✏️ 自由キーワード指定":
        query_text = st.text_input("キーワードを入力", value="航空 事故")
    else:
        category_map_ja = {
            "⚠️ 航空事故・インシデント・安全": "(航空 OR 旅客機 OR エアライン OR 飛行機) (事故 OR インシデント OR トラブル OR 緊急着陸 OR ダイバート OR 欠航 OR 安全)",
            "✈️ 航空会社・路線・運航動向": "(JAL OR ANA OR LCC OR 航空会社 OR エアライン) (就航 OR 増便 OR 減便 OR 路線 OR 運航 OR 新路線 OR 撤退)",
            "📈 エアライン経営・業績・燃油サーチャージ": "(航空 OR エアライン OR 航空会社) (業績 OR 決算 OR 燃油サーチャージ OR 運賃 OR 値上げ OR 旅客需要)",
            "🛠️ 機材・航空機製造（ボーイング/エアバス）": "(ボーイング OR エアバス OR Boeing OR Airbus OR 旅客機) (納入 OR 不具合 OR 受注 OR 発注 OR 開発 OR 機体)",
            "🏢 空港・グランドハンドリング・管制・整備": "(空港 OR 成田 OR 羽田 OR 関空 OR 中部空港) (管制 OR グランドハンドリング OR 人手不足 OR 整備 OR 混雑 OR 滑走路)"
        }
        category_map_en = {
            "⚠️ 航空事故・インシデント・安全": '(aviation OR airline OR aircraft OR flight) (accident OR incident OR "emergency landing" OR grounded OR safety OR crash OR divert)',
            "✈️ 航空会社・路線・運航動向": '(airline OR "air carrier" OR aviation) (route OR flight OR expansion OR frequency OR cancellation OR "new service")',
            "📈 エアライン経営・業績・燃油サーチャージ": '(airline OR aviation OR "air carrier") (revenue OR profit OR "fuel surcharge" OR fare OR demand OR earnings OR loss)',
            "🛠️ 機材・航空機製造（ボーイング/エアバス）": '(Boeing OR Airbus OR "commercial aircraft") (delivery OR order OR flaw OR engine OR fleet OR delay OR jet)',
            "🏢 空港・グランドハンドリング・管制・整備": '(airport OR ATC OR "air traffic control") (delay OR "ground handling" OR staffing OR maintenance OR congestion OR runway)'
        }
        
        query_text = category_map_ja[selected_genre] if region_mode == "🇯🇵 日本国内ニュース" else category_map_en[selected_genre]

    max_articles = st.slider("表示件数", min_value=3, max_value=15, value=5)

# ---------------------------------------------------------
# 3. 翻訳処理（Gemini完全不使用）
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def translate_title_without_gemini(text):
    """Gemini APIを使わずに日本語へ翻訳する関数"""
    if not text or not text.strip():
        return text

    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "en", "tl": "ja", "dt": "t", "q": text}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, params=params, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            translated_parts = [item[0] for item in data[0] if item[0]]
            result_str = "".join(translated_parts)
            if result_str and result_str != text:
                return result_str
    except Exception:
        pass

    try:
        url = "https://api.mymemory.translated.net/get"
        params = {"q": text, "langpair": "en|ja"}
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
# 4. ウィキペディア判定処理
# ---------------------------------------------------------
def is_wikipedia(title, source, link):
    """ウィキペディア記事かどうかを判定"""
    link_lower = link.lower()
    source_lower = source.lower()
    title_lower = title.lower()
    
    return (
        "wikipedia.org" in link_lower or 
        "wikipedia" in source_lower or 
        "ウィキペディア" in title_lower or 
        "wikipedia" in title_lower
    )

# ---------------------------------------------------------
# 5. Gemini API 関数（※詳細分析ボタン専用）
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
# 6. スクレイピング & ニュース取得
# ---------------------------------------------------------
def fetch_news(query, region_mode, max_items):
    """Google News RSS からニュースを取得（Wikipediaのみ除外）"""
    # 検索クエリレベルでも Wikipedia を除外
    search_query = f"{query} -site:wikipedia.org when:3d"

    encoded_query = urllib.parse.quote(search_query)
    hl_gl = "hl=ja&gl=JP&ceid=JP:ja" if region_mode == "🇯🇵 日本国内ニュース" else "hl=en-US&gl=US&ceid=US:en"
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&{hl_gl}"
    
    feed = feedparser.parse(rss_url)
    articles = []
    
    for entry in feed.entries:
        title = entry.title.rsplit(" - ", 1)[0] if " - " in entry.title else entry.title
        source = entry.title.rsplit(" - ", 1)[1] if " - " in entry.title else "不明"
        
        # ウィキペディアを除外
        if is_wikipedia(title, source, entry.link):
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
# 7. メイン表示エリア
# ---------------------------------------------------------
col1, col2 = st.columns([3, 1])
with col1:
    st.subheader(f"📡 取得ジャンル: `{selected_genre}`")
with col2:
    if st.button("🔄 最新に更新", type="primary"):
        st.cache_data.clear()

is_foreign = (region_mode == "🌐 海外・グローバルニュース (英語)")

with st.spinner("最新ニュースを取得中..."):
    articles = fetch_news(query_text, region_mode, max_articles)

if not articles:
    st.warning("直近のニュースが見つかりませんでした。ジャンルを変更して再試行してください。")
else:
    for idx, art in enumerate(articles, 1):
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
