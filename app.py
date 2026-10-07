import set  # 標準ライブラリ

def extract_keywords(text):
    """タイトルから記号・ストップワードを除去し、意味のある単語集合（集合）を返す"""
    # カッコとその中身を除去（【速報】や（ニュース名）など）
    text = re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', text)
    # 英数字・ひらがな・カタカナ・漢字以外を除去
    cleaned = re.sub(r'[^\w\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', ' ', text)
    # 2文字以上の単語（簡易形態素分解風）を抽出
    words = set([w.lower() for w in cleaned.split() if len(w) >= 2])
    return words

def is_similar_news(title1, title2):
    """2つのタイトルが同じニュース（話題）を指しているか多角的に判定"""
    # 1. 類似度判定（difflib SequenceMatcher）
    clean1 = clean_title_for_comparison(title1)
    clean2 = clean_title_for_comparison(title2)
    seq_ratio = SequenceMatcher(None, clean1, clean2).ratio()
    
    # 全体文字の類似度が 45% 以上なら重複とみなす（判定を厳しく設定）
    if seq_ratio >= 0.45:
        return True

    # 2. Jaccard係数によるキーワード一致判定（単語の重複率）
    kw1 = extract_keywords(title1)
    kw2 = extract_keywords(title2)
    
    if kw1 and kw2:
        intersection = kw1.intersection(kw2)
        union = kw1.union(kw2)
        jaccard_ratio = len(intersection) / len(union) if union else 0
        
        # 主要キーワードが 35% 以上一致、または共通の単語が 3 個以上入っている場合は重複
        if jaccard_ratio >= 0.35 or len(intersection) >= 3:
            return True

    return False

def fetch_news(query, region_mode, max_items):
    """Google News RSS からニュースを取得（キーワード重複・文章類似度で厳格に統合）"""
    search_query = f"{query} -site:wikipedia.org when:3d"

    encoded_query = urllib.parse.quote(search_query)
    hl_gl = "hl=ja&gl=JP&ceid=JP:ja" if region_mode == "🇯🇵 日本国内ニュース" else "hl=en-US&gl=US&ceid=US:en"
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&{hl_gl}"
    
    feed = feedparser.parse(rss_url)
    
    unique_groups = []
    
    # 上位 50 件まで対象を広げて集約
    for entry in feed.entries[:50]:
        title = entry.title.rsplit(" - ", 1)[0] if " - " in entry.title else entry.title
        source = entry.title.rsplit(" - ", 1)[1] if " - " in entry.title else "不明"
        
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

        # 重複チェック（新判定ロジック）
        matched_group = None
        for group in unique_groups:
            if is_similar_news(title, group['article']['original_title']):
                matched_group = group
                break

        if matched_group:
            # 既存記事より新しいニュースがあれば最新情報に更新
            if pub_dt > matched_group['pub_dt']:
                matched_group['article'] = article_data
                matched_group['pub_dt'] = pub_dt
        else:
            unique_groups.append({
                'article': article_data,
                'pub_dt': pub_dt
            })

    # 最新順に並び替え（表示件数は max_items でカット）
    sorted_groups = sorted(unique_groups, key=lambda x: x['pub_dt'], reverse=True)
    
    return [g['article'] for g in sorted_groups[:max_items]]
