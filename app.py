import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import streamlit as st

# --- 設定 ---
IMAGE_URL_TEMPLATE = "https://bath.fs-storage.jp/fs2cabinet/{head3}/{code}/{code}-m-{num}-pl.jpg"
MAX_IMAGE_NO = 20      # 01〜20まで確認
MAX_IMAGES = 9         # TikTok Shopの上限
REQUEST_TIMEOUT = 5    # 秒
RETRY_COUNT = 1        # 通信エラー時の再試行回数
MAX_WORKERS = 16       # 同時に確認するURL数
THUMBS_PER_ROW = 6     # 画像選択画面の1行あたりの枚数
TIKTOK_TAG = "[TikTokShop出品]"
REQUIRED_COLS = ['商品コード', '商品分類タグ', '代表商品コード']


def read_uploaded_csv(uploaded_file):
    """cp932 → UTF-8(BOM付き含む) の順で読み込む。全列を文字列として扱う。"""
    last_error = None
    for enc in ('cp932', 'utf-8-sig'):
        try:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding=enc, dtype=str), None
        except (UnicodeDecodeError, pd.errors.ParserError) as e:
            last_error = e
    return None, f"エラー：CSVを読み込めませんでした（Shift_JIS / UTF-8 のどちらでも読めません）。詳細: {last_error}"


def check_url(url):
    """画像URLの存在確認。戻り値: 'ok' / 'missing' / 'error:<内容>'"""
    detail = ""
    for _ in range(RETRY_COUNT + 1):
        try:
            response = requests.head(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                return "ok"
            if response.status_code == 404:
                return "missing"
            detail = f"HTTP {response.status_code}"
        except requests.RequestException as e:
            detail = type(e).__name__
    return f"error:{detail}"


def collect_image_urls(parent_codes, on_progress=None):
    """代表商品コードごとに存在する画像を番号順にすべて集める（01〜20）。

    戻り値: (代表コード→[(番号, URL), ...] の辞書, 確認できなかったURLのリスト[(コード, URL, 内容)])
    """
    tasks = {}
    for code in parent_codes:
        for i in range(1, MAX_IMAGE_NO + 1):
            tasks[(code, i)] = IMAGE_URL_TEMPLATE.format(head3=code[:3], code=code, num=f"{i:02d}")

    results = {}
    total = len(tasks)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(check_url, url): key for key, url in tasks.items()}
        for done, future in enumerate(as_completed(futures), start=1):
            results[futures[future]] = future.result()
            if on_progress:
                on_progress(done, total)

    image_map, errors = {}, []
    for code in parent_codes:
        found = []
        for i in range(1, MAX_IMAGE_NO + 1):
            status = results[(code, i)]
            if status == "ok":
                found.append((i, tasks[(code, i)]))
            elif status.startswith("error:"):
                errors.append((code, tasks[(code, i)], status[len("error:"):]))
        image_map[code] = found
    return image_map, errors


def append_tiktok_tag(tag_val):
    base_tag = str(tag_val) if pd.notna(tag_val) else ""
    if TIKTOK_TAG not in base_tag:
        return base_tag + TIKTOK_TAG
    return base_tag


def parse_numbers(text):
    """'1,2,5-10' のような指定を番号の集合にする。"""
    nums = set()
    for part in re.split(r"[,、\s]+", text.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*[-〜~]\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            nums.update(range(min(a, b), max(a, b) + 1))
        elif part.isdigit():
            nums.add(int(part))
        else:
            raise ValueError(part)
    return nums


def prepare_data(df):
    """入力チェックと画像の確認を行い、CSV作成に必要な情報をまとめる。"""
    missing_cols = [col for col in REQUIRED_COLS if col not in df.columns]
    if missing_cols:
        return False, f"エラー：アップロードされたCSVに以下の必須項目がありません。({', '.join(missing_cols)})", None

    df = df.reset_index(drop=True)
    product_codes = df['商品コード'].fillna("").str.strip()
    parent_codes = df['代表商品コード'].fillna("").str.strip()

    if (product_codes == "").any():
        return False, "エラー：『商品コード』に空欄の行が存在します。", None
    if (parent_codes == "").any():
        return False, "エラー：『代表商品コード』に空欄の行が存在します。", None

    unique_parents = list(dict.fromkeys(parent_codes))

    # 代表商品コードごとの商品名（画像選択画面の見出し用）
    names = {}
    if '商品名' in df.columns:
        for code, name in zip(parent_codes, df['商品名'].fillna("")):
            names.setdefault(code, name)

    progress_bar = st.progress(0.0)
    status_text = st.empty()

    def on_progress(done, total):
        progress_bar.progress(done / total)
        status_text.text(f"画像URLチェック中... {done} / {total} URL（代表商品コード {len(unique_parents)} 件）")

    image_map, errors = collect_image_urls(unique_parents, on_progress)
    progress_bar.empty()
    status_text.empty()

    prep = {
        'product_codes': product_codes.tolist(),
        'parent_codes': parent_codes.tolist(),
        'tags': df['商品分類タグ'].apply(append_tiktok_tag).tolist(),
        'unique_parents': unique_parents,
        'names': names,
        'image_map': image_map,
        'errors': errors,
        'no_image': [c for c in unique_parents if not image_map[c]],
    }
    return True, "画像の確認が完了しました！", prep


def build_result_df(prep, selected_urls):
    return pd.DataFrame({
        'syohin_code': prep['product_codes'],
        'tag': prep['tags'],
        'image_url_http': ["\r\n".join(selected_urls[c]) for c in prep['parent_codes']],
    })


def sel_key(code, num):
    return f"sel_{code}_{num}"


def reset_state():
    for key in list(st.session_state.keys()):
        if key == 'prep' or key.startswith('sel_'):
            del st.session_state[key]


def render_image_selector(prep):
    """商品ごとにサムネイルとチェックボックスを表示し、選択されたURLを返す。"""
    image_map = prep['image_map']

    # 初期値：先頭から9枚
    for code in prep['unique_parents']:
        for idx, (num, _) in enumerate(image_map[code]):
            st.session_state.setdefault(sel_key(code, num), idx < MAX_IMAGES)

    st.subheader("画像の選択")
    st.caption(f"チェックした画像が番号順に登録されます（1商品あたり最大{MAX_IMAGES}枚）。"
               "初期状態は先頭から9枚です。")

    col_input, col_btn = st.columns([3, 1])
    pattern = col_input.text_input("全商品にまとめて適用する番号", value="1-9",
                                   help="例: 1,2,5-10　→ 01・02・05〜10 を選択（存在しない番号は無視）")
    col_btn.write("")
    col_btn.write("")
    if col_btn.button("全商品に適用"):
        try:
            nums = parse_numbers(pattern)
            for code in prep['unique_parents']:
                for num, _ in image_map[code]:
                    st.session_state[sel_key(code, num)] = num in nums
        except ValueError as e:
            st.error(f"番号の指定を読み取れません: 「{e}」")

    selected_urls, over, empty = {}, [], []
    for code in prep['unique_parents']:
        images = image_map[code]
        chosen = [url for num, url in images if st.session_state.get(sel_key(code, num))]
        selected_urls[code] = chosen
        if not images:
            continue
        if len(chosen) > MAX_IMAGES:
            over.append(code)
        if not chosen:
            empty.append(code)

        mark = " ⚠️ 9枚超過" if len(chosen) > MAX_IMAGES else (" ⚠️ 未選択" if not chosen else "")
        title = f"{code}　{prep['names'].get(code, '')}　— 選択 {len(chosen)} / {len(images)} 枚{mark}"
        with st.expander(title, expanded=bool(mark)):
            for row_start in range(0, len(images), THUMBS_PER_ROW):
                cols = st.columns(THUMBS_PER_ROW)
                for col, (num, url) in zip(cols, images[row_start:row_start + THUMBS_PER_ROW]):
                    col.image(url, width=110)
                    col.checkbox(f"{num:02d}", key=sel_key(code, num))

    return selected_urls, over, empty


# --- Streamlit UI設定 ---
st.set_page_config(page_title="TikTokShop連携CSV生成", layout="centered")
st.title("TikTokShop用 CSVコンバーター")
st.write("ネクストエンジンから出力した「商品マスター」CSVをアップロードしてください。")

uploaded_file = st.file_uploader("CSVファイルを選択", type=['csv'])

if uploaded_file is None:
    reset_state()
    st.session_state.pop('file_key', None)
else:
    file_key = f"{uploaded_file.name}-{uploaded_file.size}"
    if st.session_state.get('file_key') != file_key:
        reset_state()
        st.session_state['file_key'] = file_key

    df, read_error = read_uploaded_csv(uploaded_file)
    if read_error:
        st.error(read_error)
        st.stop()

    st.write("【プレビュー】アップロードされた元データ (先頭5行)")
    st.dataframe(df.head())

    manual = st.checkbox("画像を手動で選ぶ（オプション）",
                         help="オンにすると、商品ごとにサムネイルを見ながら使う画像を選べます。"
                              "オフの場合は先頭から9枚を自動で使います。")

    if st.button("変換を実行する"):
        reset_state()
        is_success, message, prep = prepare_data(df)
        if not is_success:
            st.error(message)
        else:
            st.session_state['prep'] = prep

    prep = st.session_state.get('prep')
    if prep:
        st.success("画像の確認が完了しました。" + ("下で使う画像を選んでください。" if manual else ""))

        if prep['errors']:
            st.warning(
                f"通信エラーで確認できなかった画像が {len(prep['errors'])} 件あります。"
                "画像が抜けている可能性があるため、時間をおいて再実行してください。"
            )
            st.dataframe(pd.DataFrame(prep['errors'], columns=['代表商品コード', 'URL', '内容']))
        if prep['no_image']:
            st.warning("画像が1枚も見つからなかった代表商品コード: " + ", ".join(prep['no_image']))

        if manual:
            selected_urls, over, empty = render_image_selector(prep)
        else:
            selected_urls = {c: [url for _, url in imgs[:MAX_IMAGES]] for c, imgs in prep['image_map'].items()}
            over, empty = [], []

        result_df = build_result_df(prep, selected_urls)
        st.write("【プレビュー】変換後のデータ (先頭5行)")
        st.dataframe(result_df.head())

        if over:
            st.error(f"{MAX_IMAGES}枚を超えて選択している商品があります: " + ", ".join(over))
        if empty:
            st.error("画像が1枚も選択されていない商品があります: " + ", ".join(empty))

        csv_text = result_df.to_csv(index=False, lineterminator='\r\n')
        st.download_button(
            label="変換後CSVをダウンロード",
            data=csv_text.encode('cp932', errors='replace'),
            file_name="tiktok_shop_update.csv",
            mime="text/csv",
            disabled=bool(over or empty),
        )
