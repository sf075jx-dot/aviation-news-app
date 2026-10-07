import streamlit as st
import feedparser
import requests
from bs4 import BeautifulSoup
import urllib.parse
import os
import re
import datetime
import time
from email.utils import parsedate_to_datetime
from difflib import SequenceMatcher
from google import genai

# ---------------------------------------------------------
# 1. ページ基本設定（スマホ対応レスポンシブ）
# ---------------------------------------------------------
st.set_page_config(
    page_title="航空業界ニュース・アナライザー",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.title("航空業界ニュース・アナライザー")
st.caption("国内外の航空ニュースを検索し、リクエストされた記事を多角的な視点から深掘り分析します。")

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
# 4. 除外・重複判定処理
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

def clean_title_for_comparison(title):
    """【速報】やメディア名、記号などを除去しテキストのみ抽出"""
    title = re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', title)
    title = re.sub(r'[^\w\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', '', title).lower()
    return title

def extract_keywords(text):
    """タイトルから記号・不要語を除き、単語の集合を作成"""
    text = re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', text)
    cleaned = re.sub(r'[^\w\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', ' ', text)
    words = set([w.lower() for w in cleaned.split() if len(w) >= 2])
    return words

def is_similar_news(title1, title2):
    """2つのタイトルが同じ話題を指しているか総合的に判定"""
    clean1 = clean_title_for_comparison(title1)
    clean2 = clean_title_for_comparison(title2)
    
    # 1. 文章全体の類似度（45%以上で一致）
    seq_ratio = SequenceMatcher(None, clean1, clean2).ratio()
    if seq_ratio >= 0.45:
        return True

    # 2. キーワード（単語）の一致率（35%以上または共通単語3個以上で一致）
    kw1 = extract_keywords(title1)
    kw2 = extract_keywords(title2)
    
    if kw1 and kw2:
        intersection = kw1.intersection(kw2)
        union = kw1.union(kw2)
        jaccard_ratio = len(intersection) / len(union) if union else 0
        
        if jaccard_ratio >= 0.35 or len(intersection) >= 3:
            return True

    return False

def parse_published_time(entry):
    """RSSのpublished文字列をdatetimeオブジェクトに変換"""
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        try:
            return datetime.datetime(*entry.published_parsed[:6])
        except Exception:
            pass
    try:
        return parsedate_to_datetime(entry.get('published', ''))
    except Exception:
        return datetime.datetime.min

# ---------------------------------------------------------
# 5. Gemini API 関数（※詳細分析ボタン専用：多角的分析プロンプト）
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def generate_gemini_summary(title, content, is_foreign=False):
    """多角的な視点から構造的・網羅的な分析レポートを生成（リトライ機能付き）"""
    if not client:
        return "⚠️ Gemini APIキーが設定されていません。"
    
    lang_instruction = "※元のニュースは英語です。分析文言はすべて【自然で分かりやすい日本語】で執筆してください。" if is_foreign else ""

    prompt = f"""あなたは優秀な航空・産業アナリストです。
以下のニュースについて、単なる表面的な要約や経済影響だけに留まらず、**「技術的課題」「法規制・政策」「環境・サステナビリティ」「消費者心理・社会受容性」「地政学・サプライチェーン」などの多角的な視点**から深く多面的に分析し、質の高い考察レポートを作成してください。
{lang_instruction}

【ニュースタイトル】
{title}

【ニュース概要】
{content}

---
【出力フォーマット】
以下の見出しに沿って、箇条書きと簡潔な文章で回答してください。

■ 1. ニュースの核心（多面的な背景）
・単なる事実要約だけでなく、この出来事の背景にある構造的な要因や多面的な意味合いを2〜3行でまとめてください。

■ 2. 航空業界内へのインパクト
・運航の安全性、航空会社の経営戦略、機材運用、乗客へのサービス面などに与える直接的・間接的な影響。

■ 3. 技術・法規制・インフラストラクチャーの視点
・関与するテクノロジーの課題、安全基準、関連する航空法・国際法規、インフラ（空港や管制等）への波及。

■ 4. 経済・他業界および環境（サステナビリティ）への波及効果
・サプライチェーン、観光・ホテル・物流業界への影響、および環境規制やCO2削減などへの長期的な波及。

■ 5. 今後のシナリオと注視すべきポイント
・短期・長期でどのような変化が想定されるか、今後業界関係者や市場が注視すべき決定的な分かれ目（リスク要因など）。
"""
    
    # 503エラー（一時的高負荷）対策として最大2回リトライする
    max_retries = 2
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            if "503" in str(e) and attempt < max_retries - 1:
                time.sleep(2)  # 2秒待って再試行
                continue
            return f"分析レポートの生成に失敗しました（一時的な混雑の可能性があります。少し時間を置いて再度お試しください）: {e}"

# ---------------------------------------------------------
# 6. スクレイピング & ニュース取得（重複は最新件へ統合）
# ---------------------------------------------------------
def fetch_news(query, region_mode, max_items):
    """Google News RSS からニュースを取得（Wikipedia除外・重複統合）"""
    search_query = f"{query} -site:wikipedia.org when:3d"

    encoded_query = urllib.parse.quote(search_query)
    hl_gl = "hl=ja&gl=JP&ceid=JP:ja" if region_mode == "🇯🇵 日本国内ニュース" else "hl=en-US&gl=US&ceid=US:en"
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&{hl_gl}"
    
    feed = feedparser.parse(rss_url)
    
    unique_groups = []
    
    # RSS上位 50 件をスキャンして集約
    for entry in feed.entries[:50]:
        title = entry.title.rsplit(" - ", 1)[0] if " - " in entry.title else entry.title
        source = entry.title.rsplit(" - ", 1)[1] if " - " in entry.title else "不明"
        
        # 1. ウィキペディアを除外
        if is_wikipedia(title, source, entry.link):
            continue

        pub_dt = parse_published_time(entry)
        summary_raw = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text()
        
        article_data = {
            "original_title": title,
            "source": source,
            "link": entry.link,
            "published": entry.get("published", "最新"),
            "pub_dt": pub_dt,
            "summary": summary_raw if len(summary_raw.strip()) > 10 else title
        }

        # 2. 重複チェック（新判定ロジック）
        matched_group = None
        for group in unique_groups:
            if is_similar_news(title, group['article']['original_title']):
                matched_group = group
                break

        if matched_group:
            # 重複していた場合：より最新の日時であれば最新記事に差し替え
            if pub_dt > matched_group['pub_dt']:
                matched_group['article'] = article_data
                matched_group['pub_dt'] = pub_dt
        else:
            # 重複がない新規話題：グループとして登録
            unique_groups.append({
                'article': article_data,
                'pub_dt': pub_dt
            })

    # 3. 日時が新しい順に並び替え、指定件数分を取得
    sorted_groups = sorted(unique_groups, key=lambda x: x['pub_dt'], reverse=True)
    
    return [g['article'] for g in sorted_groups[:max_items]]

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
        
        with st.expander("📊 AI要約・多角的な分析レポートを表示"):
            if st.button("📊 このニュースを詳細分析する", key=f"btn_{idx}"):
                with st.spinner("Geminiが多角的な視点から分析レポートを作成中..."):
                    summary = generate_gemini_summary(art['original_title'], art['summary'], is_foreign=is_foreign)
                    st.markdown(summary)
            else:
                st.write("※ ボタンを押すと、技術・法規制・環境・経済などの多角的視点を含む解説記事を表示します。")
        
        st.divider()
