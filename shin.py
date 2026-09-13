import streamlit as st
import pandas as pd
from playwright.sync_api import sync_playwright
import urllib.parse
import re
import os
import datetime

# --- クラウド用の初期設定（ブラウザの自動インストール） ---
os.system("playwright install chromium")

# 画面レイアウトの設定
st.set_page_config(page_title="X Target Extractor SaaS", page_icon="🎯", layout="wide")

st.title("🎯 X ターゲット抽出・精査ツール (SaaSデモ版)")
st.write("高精度リアルタイムデータエンジンにより、キーワードと除外ワードを指定して自動で最新リストを抽出します。")

# ==========================================
# 履歴＆回数制限用の設定（クラウド保存用にパスを変更）
# ==========================================
HISTORY_FILE = "extraction_history.txt"
LIMIT_FILE = "free_usage.txt"
today_str = datetime.date.today().strftime("%Y-%m-%d")

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f)
    return set()

def save_history(new_users):
    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
        for u in new_users:
            f.write(f"{u}\n")

def get_free_usage():
    if os.path.exists(LIMIT_FILE):
        try:
            with open(LIMIT_FILE, 'r', encoding='utf-8') as f:
                data = f.read().strip().split(',')
                if len(data) == 2 and data[0] == today_str:
                    return int(data[1])
        except:
            pass
    return 0

def increment_free_usage():
    count = get_free_usage()
    with open(LIMIT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"{today_str},{count + 1}")

# --- ライセンス認証 ---
st.sidebar.header("🔑 ライセンス認証")
license_key = st.sidebar.text_input("プロ版ライセンスキーを入力", type="password", help="有効なキーを入力するとフル機能が解放されます。")
is_pro = (license_key == "PRO-2026")

if is_pro:
    st.sidebar.success("✨ プロ版ライセンス認証完了！全機能が解放されました。")
else:
    st.sidebar.warning("現在ライト版（無料お試し）です。一部機能に制限があります。")

# --- サイドバー（入力フォーム） ---
st.sidebar.header("⚙️ 抽出条件の設定")

keyword = st.sidebar.text_input("検索キーワード (スペース区切りで複数指定可)", value="待機 暇")
is_female_only = st.sidebar.checkbox("🚺 女性アカウントのみ抽出（簡易判定）", value=True, help="男性特有の一人称（俺は、僕は）や、客側の発言を自動で除外します。")

default_ng = "スカウト, 高収入, 稼げる, 案件, 店舗公式, スタッフ, プロフ見て, 固ツイ, 固定ツイ, DM開放, 面接, エージェント, 紹介料, 保証, 応募, 弊社, 稼ぎたい方"
ng_words_input = st.sidebar.text_area("除外ワード (カンマ区切りで入力)", value=default_ng, height=150)

if is_pro:
    limit = st.sidebar.slider("最大取得件数", min_value=10, max_value=100, value=50, step=10)
    st.sidebar.markdown("---")
    st.sidebar.subheader("🛡️ 重複防止コントロール")
    if st.sidebar.button("🗑️ 過去の抽出履歴をリセット"):
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        st.sidebar.success("抽出履歴をリセットしました！")
else:
    st.sidebar.markdown("---")
    free_usage_count = get_free_usage()
    st.sidebar.info(f"🔒 本日の無料お試し枠: 残り {max(0, 2 - free_usage_count)} 回")
    limit = 10

reach_limit = (not is_pro) and (get_free_usage() >= 2)
run_button = st.sidebar.button("🚀 リストを抽出する", type="primary", disabled=reach_limit)

# --- メイン処理 ---
if run_button:
    if not is_pro:
        increment_free_usage()
        
    status_text = st.empty()
    progress_text = st.empty()
    
    status_text.info(f"🔄 抽出処理を開始しました。超高速でデータを解析中です…")
    
    spam_words = [w.strip() for w in ng_words_input.split(",") if w.strip()]
    spam_username_words = ["スカウト", "公式", "紹介", "エージェント", "稼げる", "高収入", "bot"]

    male_text_words = []
    male_username_words = []
    if is_female_only:
        male_text_words = ["俺は", "俺が", "俺の", "僕は", "僕が", "僕の", "ワイは", "キャバ行く", "風俗行く", "メンエス行く"]
        male_username_words = ["おじさん"]

    past_history_set = load_history() if is_pro else set()
    
    def check_spam(tweet_text, display_name):
        for ng in spam_words:
            if ng in tweet_text: return True
        for ng in spam_username_words:
            if ng in display_name: return True
        return False

    def check_male(tweet_text, display_name):
        if not is_female_only: return False
        for mw in male_text_words:
            if mw in tweet_text: return True
        for mw in male_username_words:
            if mw in display_name: return True
        return False

    extracted_data = []
    seen_tweets = set()
    
    total_checked = 0
    history_skipped = 0
    spam_skipped = 0
    male_skipped = 0
    no_new_data_count = 0
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={'width': 1280, 'height': 800})
            page = context.new_page()

            encoded_query = urllib.parse.quote(keyword)
            search_url = f"https://search.yahoo.co.jp/realtime/search?p={encoded_query}"
            page.goto(search_url)
            page.wait_for_timeout(4000)

            while len(extracted_data) < limit:
                prev_count = len(extracted_data)
                tweets = page.locator('div[class*="Tweet_body"]').all()
                
                for tweet in tweets:
                    if len(extracted_data) >= limit:
                        break
                        
                    try:
                        tweet_text = tweet.inner_text(timeout=500)
                        
                        match = re.search(r'@[A-Za-z0-9_]+', tweet_text)
                        if not match:
                            continue
                            
                        user_handle = match.group(0)
                        
                        if user_handle in seen_tweets:
                            continue
                            
                        total_checked += 1
                        
                        if user_handle in past_history_set:
                            history_skipped += 1
                            progress_text.caption(f"🔍 解析中... (確認: {total_checked}件 / 🔄履歴: {history_skipped} / 🤖業者: {spam_skipped} / 🚹男性: {male_skipped} / ✨成功: {len(extracted_data)})")
                            seen_tweets.add(user_handle)
                            continue

                        display_name = ""
                        name_loc = tweet.locator('a[class*="Tweet_authorName"]').first
                        if name_loc.count() > 0:
                            display_name = name_loc.inner_text(timeout=500)

                        if check_spam(tweet_text, display_name):
                            spam_skipped += 1
                            progress_text.caption(f"🔍 解析中... (確認: {total_checked}件 / 🔄履歴: {history_skipped} / 🤖業者: {spam_skipped} / 🚹男性: {male_skipped} / ✨成功: {len(extracted_data)})")
                            seen_tweets.add(user_handle)
                            continue

                        if check_male(tweet_text, display_name):
                            male_skipped += 1
                            progress_text.caption(f"🔍 解析中... (確認: {total_checked}件 / 🔄履歴: {history_skipped} / 🤖業者: {spam_skipped} / 🚹男性: {male_skipped} / ✨成功: {len(extracted_data)})")
                            seen_tweets.add(user_handle)
                            continue

                        time_text = "時間不明"
                        tweet_url = "取得不可"
                        time_loc = tweet.locator('a[href*="/status/"]').first
                        if time_loc.count() > 0:
                            time_text = time_loc.inner_text(timeout=500).strip()
                            tweet_url = time_loc.get_attribute('href', timeout=500)

                        profile_url = f"https://x.com/{user_handle.replace('@', '')}"
                        clean_body = tweet_text.replace('\n', ' ').strip()
                        
                        extracted_data.append([user_handle, time_text, profile_url, clean_body, tweet_url])
                        seen_tweets.add(user_handle)
                        
                        progress_text.caption(f"🔍 解析中... (確認: {total_checked}件 / 🔄履歴: {history_skipped} / 🤖業者: {spam_skipped} / 🚹男性: {male_skipped} / ✨成功: {len(extracted_data)})")

                    except:
                        continue

                if len(extracted_data) == prev_count:
                    no_new_data_count += 1
                    if no_new_data_count >= 5: 
                        break
                else:
                    no_new_data_count = 0

                if len(extracted_data) < limit:
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(2500)
                    
                    try:
                        more_button = page.locator("text=もっと見る").first
                        if more_button.is_visible(timeout=1000):
                            more_button.click()
                            page.wait_for_timeout(3000)
                    except:
                        pass

            browser.close()

        df = pd.DataFrame(extracted_data, columns=['ユーザーID', '投稿時間', 'プロフィールURL', 'ツイート本文', 'ツイートURL'])
        
        progress_text.caption(f"✅ 解析完了！ (最終確認: {total_checked}件)")
        
        if not df.empty:
            if is_pro:
                save_history(seen_tweets)
                status_text.success(f"✨ 抽出完了！ スパムと男性を除外した超優良リストが **{len(df)}件** 見つかりました。")
                st.dataframe(df, use_container_width=True)
                
                csv_data = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                st.download_button(
                    label="📥 抽出したリストをCSVでダウンロード",
                    data=csv_data,
                    file_name="target_list.csv",
                    mime="text/csv",
                )
            else:
                status_text.success(f"✨ 抽出完了！ 無料お試し版のため **{len(df)}件** のみ表示しています。")
                st.dataframe(df, use_container_width=True)
                
                current_count = get_free_usage()
                if current_count >= 2:
                    st.error("🚨 【重要】本日の無料お試し枠は終了しました。明日また試すか、プロ版のライセンスをご入力ください。")
                else:
                    st.warning(f"🔒 リストの【CSVダウンロード】や【抽出件数の無制限化】等はプロ版限定機能です。（本日残り {2 - current_count} 回）")
        else:
            status_text.warning(f"条件に一致する新しいデータが見つかりませんでした。\n\n【ブロック内訳】\n・🤖 業者/スパムとして排除: {spam_skipped}件\n・🚹 男性として排除: {male_skipped}件\n・🔄 過去に抽出済みのため重複排除: {history_skipped}件")
            
    except Exception as e:
        status_text.error(f"エラーが発生しました: {e}")
else:
    st.write("👈 左側のサイドバーから条件を設定し、**「リストを抽出する」**ボタンを押してください。")
