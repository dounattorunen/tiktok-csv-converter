import streamlit as st
import pandas as pd
import io
import requests

def process_csv(df):
    required_cols = ['商品コード', '商品分類タグ', '代表商品コード']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        return False, f"エラー：アップロードされたCSVに以下の必須項目がありません。({', '.join(missing_cols)})", None
    
    if df['商品コード'].isnull().any():
        return False, "エラー：『商品コード』に空欄の行が存在します。", None
    if df['代表商品コード'].isnull().any():
        return False, "エラー：『代表商品コード』に空欄の行が存在します。", None

    result_df = pd.DataFrame()
    result_df['syohin_code'] = df['商品コード']
    
    def append_tiktok_tag(tag_val):
        base_tag = str(tag_val) if pd.notna(tag_val) else ""
        if "[TikTokShop出品]" not in base_tag:
            return base_tag + "[TikTokShop出品]"
        return base_tag
    
    result_df['tag'] = df['商品分類タグ'].apply(append_tiktok_tag)
    
    # --- 画像URLの存在チェック＆生成処理 ---
    url_cache = {} # 同じ代表商品コードの通信を省くためのキャッシュ辞書
    
    # プログレスバー用の設定（UIで進捗を見せるため）
    total_rows = len(df)
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    image_urls_list = []
    
    for index, row in df.iterrows():
        parent_code = row['代表商品コード']
        parent_code_str = str(parent_code).replace('.0', '').strip()
        
        # すでに確認済みの代表商品コードなら、キャッシュから取得
        if parent_code_str in url_cache:
            image_urls_list.append(url_cache[parent_code_str])
        else:
            head3 = parent_code_str[:3]
            valid_urls = []
            
            # 01〜20まで順番にチェック
            for i in range(1, 21):
                if len(valid_urls) >= 9:
                    break # 最大9枚集まったらループ終了
                    
                num = str(i).zfill(2)
                url = f"https://bath.fs-storage.jp/fs2cabinet/{head3}/{parent_code_str}/{parent_code_str}-m-{num}-pl.jpg"
                
                try:
                    # HEADリクエストで画像の存在確認（タイムアウト2秒）
                    response = requests.head(url, timeout=2)
                    if response.status_code == 200:
                        valid_urls.append(url)
                except requests.RequestException:
                    pass # 通信エラーやタイムアウト時はスキップ
            
            # 結果を改行区切りで結合し、キャッシュに保存
            result_url_str = "\r\n".join(valid_urls)
            url_cache[parent_code_str] = result_url_str
            image_urls_list.append(result_url_str)
            
        # プログレスバーの更新
        progress_bar.progress((index + 1) / total_rows)
        status_text.text(f"画像URLチェック中... {index + 1} / {total_rows} 件完了")
        
    result_df['image_url_http'] = image_urls_list
    
    # 処理完了時にプログレスバーを消去
    progress_bar.empty()
    status_text.empty()
    
    return True, "データ変換に成功しました！", result_df

# --- Streamlit UI設定 ---
st.set_page_config(page_title="TikTokShop連携CSV生成", layout="centered")
st.title("TikTokShop用 CSVコンバーター")
st.write("ネクストエンジンから出力した「商品マスター」CSVをアップロードしてください。")

uploaded_file = st.file_uploader("CSVファイルを選択", type=['csv'])

if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file, encoding='shift_jis')
    except Exception:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, encoding='utf-8')

    st.write("【プレビュー】アップロードされた元データ (先頭5行)")
    st.dataframe(df.head())

    if st.button("変換を実行する"):
        is_success, message, result_df = process_csv(df)
        
        if not is_success:
            st.error(message)
        else:
            st.success(message)
            st.write("【プレビュー】変換後のデータ (先頭5行)")
            st.dataframe(result_df.head())
            
            csv_buffer = io.StringIO()
            result_df.to_csv(csv_buffer, index=False, encoding='shift_jis', lineterminator='\r\n')
            
            st.download_button(
                label="変換後CSVをダウンロード",
                data=csv_buffer.getvalue().encode('shift_jis', errors='replace'),
                file_name="tiktok_shop_update.csv",
                mime="text/csv"
            )
