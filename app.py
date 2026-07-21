import streamlit as st
import pandas as pd
import io

def process_csv(df):
    """
    ネクストエンジンの商品マスターデータをTikTok連携用データに変換する
    """
    # 1. バリデーション（必須項目のチェック）
    required_cols = ['商品コード', '商品分類タグ', '代表商品コード']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        return False, f"エラー：アップロードされたCSVに以下の必須項目がありません。({', '.join(missing_cols)})", None
    
    # 2. 空欄チェック
    if df['商品コード'].isnull().any():
        return False, "エラー：『商品コード』に空欄の行が存在します。", None
    if df['代表商品コード'].isnull().any():
        return False, "エラー：『代表商品コード』に空欄の行が存在します。", None

    # 3. データの変換処理
    result_df = pd.DataFrame()
    
    # syohin_code: そのままコピー
    result_df['syohin_code'] = df['商品コード']
    
    # tag: 元のタグに [TikTokShop出品] を追加（既に含まれている場合は追加しない）
    def append_tiktok_tag(tag_val):
        base_tag = str(tag_val) if pd.notna(tag_val) else ""
        if "[TikTokShop出品]" not in base_tag:
            return base_tag + "[TikTokShop出品]"
        return base_tag
    
    result_df['tag'] = df['商品分類タグ'].apply(append_tiktok_tag)
    
    # image_url_http: 代表商品コードから9枚分のURLを自動生成
    def generate_image_urls(parent_code):
        # 念のため文字列化し、数値の.0などがついている場合は除去
        parent_code_str = str(parent_code).replace('.0', '').strip()
        head3 = parent_code_str[:3]
        
        urls = []
        for i in range(1, 10):
            num = str(i).zfill(2) # 01, 02...09
            url = f"https://bath.fs-storage.jp/fs2cabinet/{head3}/{parent_code_str}/{parent_code_str}-m-{num}-pl.jpg"
            urls.append(url)
        
        # 改行(\r\n)で結合
        return "\r\n".join(urls)
    
    result_df['image_url_http'] = df['代表商品コード'].apply(generate_image_urls)
    
    return True, "データ変換に成功しました！", result_df


# --- Streamlit UI設定 ---
st.set_page_config(page_title="TikTokShop連携CSV生成", layout="centered")
st.title("TikTokShop用 CSVコンバーター")
st.write("ネクストエンジンから出力した「商品マスター」CSVをアップロードしてください。")

# ファイルアップローダー
uploaded_file = st.file_uploader("CSVファイルを選択", type=['csv'])

if uploaded_file is not None:
    try:
        # ネクストエンジンのCSVはShift-JISが多いため指定
        df = pd.read_csv(uploaded_file, encoding='shift_jis')
    except Exception:
        # Shift-JISで失敗した場合はUTF-8でフォールバック
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
            
            # CSVをShift-JISでメモリ上に書き出し
            csv_buffer = io.StringIO()
            result_df.to_csv(csv_buffer, index=False, encoding='shift_jis', lineterminator='\r\n')
            
            # ダウンロードボタンを表示
            st.download_button(
                label="変換後CSVをダウンロード",
                data=csv_buffer.getvalue().encode('shift_jis', errors='replace'),
                file_name="tiktok_shop_update.csv",
                mime="text/csv"
            )