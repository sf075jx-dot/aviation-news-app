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

# Gemini API クライアント初期化（※【厳禁ルール遵守】解説記事生成機能でのみ使用）
api_key = st.secrets.get("GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
client = genai.Client(api_key=api_key) if api_key else None

if not api_key:
    st.warning("⚠️ `GEMINI_API_KEY` が設定されていません。Streamlit Community Cloudの Secrets または環境変数にAPIキーを設定してください。")

# ---------------------------------------------------------
# 2. サイドバー（ジャンル表示と条件指定）
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
            "⚠️ 航空事故・インシデント・安全": "航空 事故 インシデント 緊急着陸 欠航 安全",
            "✈️ 航空会社・路線・運航動向": "JAL ANA LCC 航空会社 路線 運航 就航 増便",
            "📈 エアライン経営・業績・燃油サーチャージ": "航空 業績 決算 燃油サーチャージ 運賃 旅客需要",
            "🛠️ 機材・航空機製造（ボーイング/エアバス）": "ボーイング エアバス Boeing Airbus 旅客機 機材 納入",
            "🏢 空港・グランドハンドリング・管制・整備": "空港 管制 グランドハンドリング 整備 羽田 成田 関空"
        }
        category_map_en = {
            "⚠️ 航空事故・インシデント・安全": "aviation accident incident emergency landing safety grounded",
            "✈️ 航空会社・路線・運航動向": "airline route flight expansion frequency cancellation",
            "📈 エアライン経営・業績・燃油サーチャージ": "airline revenue profit fuel surcharge fare demand",
            "🛠️ 機材・航空機製造（ボーイング/エアバス）": "Boeing Airbus aircraft delivery order flaw fleet",
            "🏢 空港・グランドハンドリング・管制・整備": "airport ATC air traffic control delay ground handling maintenance"
        }
        
        query_text = category_map_ja[selected_genre] if region_mode == "🇯🇵 日本国内ニュース" else category_map_en[selected_genre]

    max_articles = st.slider("表示件数", min_value=3, max_value=15, value=5)
    exclude_spotter = st.checkbox("写真・スポッター・ゴシップ系サイトを除外", value=True)

# ---------------------------------------------------------
# 3. 翻訳処理（Gemini完全不使用）
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def translate_title_without_gemini(text):
    """Gemini APIを絶対に使わずに日本語へ翻訳する関数"""
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
# 4. ノイズ・海外メディア排除判定（Gemini不使用のコード処理）
# ---------------------------------------------------------
# 海外系メディア（日本語版含む）の除外リスト
EXCLUDE_OVERSEAS_SOURCES = [
    "BBC", "CNN", "AFP", "Reuters", "ロイター", "Bloomberg", "ブルームバーグ",
    "AP通信", "The New York Times", "WSJ", "ウォール・ストリート・ジャーナル"
]

# 写真・ゴシップ・事故トラブル系メディア＆キーワードの除外リスト
NG_DOMAINS = ["flyteam.jp", "planespotters.net", "jetphotos.com", "airliners.net", "encount.press"]
NG_KEYWORDS = [
    "FlyTeam", "航空フォト", "機材写真", "特別塗装機", "PlaneSpotters", "JetPhotos",
    "ENCOUNT", "観客", "顔面", "直撃", "鼻血", "怪我", "けが", "マナー", "炎上", "悲鳴", "物議"
]

def is_unwanted_article(title, source, link, is_domestic_mode, filter_spotter):
    """Pythonコードのみで不要な記事（海外メディア・ゴシップ記事）を自動判定"""
    link_lower = link.lower()
    source_lower = source.lower()
    title_lower = title.lower()

    # 1. 国内モード時に海外メディアをカット
    if is_domestic_mode:
        if any(s.lower() in source_lower for s in EXCLUDE_OVERSEAS_SOURCES):
            return True

    # 2. スポッター・ゴシップ・トラブル記事をカット
    if filter_spotter:
        if any(d in link_lower for d in NG_DOMAINS):
            return True
        if any(k.lower() in source_lower or k.lower() in title_lower for k in NG_KEYWORDS):
            return True

    return False

# ---------------------------------------------------------
# 5. Gemini API 関数（※【唯一のGemini利用箇所】詳細分析ボタン専用）
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
def fetch_news(query, region_mode, max_items, filter_spotter):
    """Google News RSS からニュースを取得"""
    is_domestic_mode = (region_mode == "🇯🇵 日本国内ニュース")
    
    # 検索クエリにも事前に除外コマンドを付与（検索エンジンの段階でカット）
    if is_domestic_mode:
        search_query = f"{query} -site:bbc.com -site:reuters.com -site:cnn.co.jp -ENCOUNT when:3d"
    else:
        search_query = f"{query} when:3d"

    encoded_query = urllib.parse.quote(search_query)
    hl_gl = "hl=ja&gl=JP&ceid=JP:ja" if is_domestic_mode else "hl=en-US&gl=US&ceid=US:en"
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&{hl_gl}"
    
    feed = feedparser.parse(rss_url)
    articles = []
    
    for entry in feed.entries:
        title = entry.title.rsplit(" - ", 1)[0] if " - " in entry.title else entry.title
        source = entry.title.rsplit(" - ", 1)[1] if " - " in entry.title else "不明"
        
        # Pythonコードによる厳格フィルター（Gemini不使用）
        if is_unwanted_article(title, source, entry.link, is_domestic_mode, filter_spotter):
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
    articles = fetch_news(query_text, region_mode, max_articles, exclude_spotter)

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
