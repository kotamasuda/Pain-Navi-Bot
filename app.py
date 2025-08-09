# -*- coding: utf-8 -*-
# Streamlit版：痛みナビBot（自由記載・方針反映・履歴/資料取り込み・赤旗・CSVログ・デモ対応）

import os, csv, glob
import datetime as dt
from pathlib import Path
import streamlit as st

try:
    from openai import OpenAI
except Exception:
    st.error("openai ライブラリが必要です。`python3 -m pip install openai`")
    st.stop()

# ---------- ページ設定 ----------
st.set_page_config(page_title="痛みナビBot", layout="centered")
st.title("🧭 痛みナビBot（一般向けセルフケア）")
st.caption("※診断ではありません。危険サインがあれば医療機関の受診を最優先してください。")

# ---------- 設定（API or デモ） ----------
st.sidebar.subheader("設定")
DEMO = st.sidebar.toggle("デモモード（APIを使わない）", value=False)

def get_client():
    key_env = os.environ.get("OPENAI_API_KEY", "")
    api_key = st.sidebar.text_input(
        "OpenAI APIキー（環境変数に設定済みなら空でOK）",
        value="" if key_env else "",
        type="password",
        help="環境変数 OPENAI_API_KEY が設定されていれば空でOK"
    ) or key_env
    if DEMO: return None
    if not api_key:
        st.sidebar.warning("APIキーを入力するか、デモモードをオンにしてください。"); st.stop()
    return OpenAI(api_key=api_key)

client = get_client()
MODEL = "gpt-4o-mini"

# ---------- プロファイル（あなたの発信・方針を反映） ----------
PROFILE_PATH = Path("bot_profile.txt")
def load_profile() -> str:
    return PROFILE_PATH.read_text(encoding="utf-8") if PROFILE_PATH.exists() else ""

def save_profile(text: str):
    PROFILE_PATH.write_text(text, encoding="utf-8")

profile_text = st.sidebar.text_area(
    "あなたの発信・方針（保存可）",
    value=load_profile(), height=160,
    placeholder="例：生活指導は“続けられる簡単な工夫”を最優先／体幹より股関節の可動を重視／朝のルーティン例を必ず入れる…"
)
colP1, colP2 = st.sidebar.columns(2)
if colP1.button("保存"): 
    save_profile(profile_text); st.sidebar.success("保存しました")
if colP2.button("再読込"):
    st.experimental_rerun()

# ---------- 参考資料の取り込み（TXT/MD） ----------
uploaded = st.sidebar.file_uploader("参考資料を添付（.txt / .md）", type=["txt","md"])
extra_ref = ""
if uploaded:
    extra_ref = uploaded.read().decode("utf-8")
    st.sidebar.info(f"参考資料 {uploaded.name} を読み込みました（{len(extra_ref)} 文字）")

# ---------- 履歴の取り込み（直近N件） ----------
LOG_DIR = Path("logs"); LOG_DIR.mkdir(exist_ok=True)
def load_recent_logs(n=3) -> str:
    files = sorted(glob.glob(str(LOG_DIR / "painlog_*.csv")))
    if not files: return ""
    last = files[-1]
    rows = []
    try:
        with open(last, "r", encoding="utf-8", newline="") as f:
            r = list(csv.DictReader(f))
            for row in r[-n:]:
                rows.append(f"部位:{row.get('part','')} / タイプ:{row.get('type','')} / 因子:{row.get('factor','')} / 抜粋:{row.get('advice','')[:180]}")
    except Exception:
        return ""
    return "\n".join(rows)

use_history = st.sidebar.toggle("過去ログを取り込む（直近3件）", value=False)
history_text = load_recent_logs(3) if use_history else ""

# ---------- 出力フォーマットを固定 ----------
SYSTEM_PROMPT = (
    "あなたは腰痛・坐骨神経痛などの一般向けセルフケアを案内する理学療法の専門家です。"
    "・“赤旗”症状（外傷/発熱/排尿排便障害/急な麻痺 など）があれば受診を最優先するよう促す。"
    "・自宅でできる安全なセルフケア（姿勢/生活習慣/軽い運動）を短く具体的に、箇条書き中心で示す。"
    "・専門用語は控えめ、断定的診断は避ける、痛みが増える動きは無理しないと明記する。"
    "出力は必ず次のMarkdown見出しの順で、各セクション3〜6項目にまとめる："
    "## 可能性のある原因（メカニズム・生活要因）"
    "## 考えられること（鑑別の方向性：断定しない）"
    "## セルフケアの提案（手順は短く）"
    "## 避ける動き"
    "## 受診の目安"
)

# ---------- 赤旗チェック ----------
st.sidebar.markdown("### 🩺 安全確認（赤旗チェック）")
flag_trauma   = st.sidebar.checkbox("最近の強い外傷（転倒・交通事故など）がある")
flag_fever    = st.sidebar.checkbox("38℃以上の発熱や悪寒などの体調不良がある")
flag_cauda    = st.sidebar.checkbox("排尿/排便障害・会陰部のしびれがある（馬尾症状の疑い）")
flag_weakness = st.sidebar.checkbox("足に力が入りにくい等の進行性の麻痺がある")
red_flags = [name for name, on in [
    ("強い外傷", flag_trauma),
    ("発熱/感染疑い", flag_fever),
    ("排尿排便障害/馬尾症状疑い", flag_cauda),
    ("進行する神経症状", flag_weakness),
] if on]
has_red_flag = len(red_flags) > 0
if has_red_flag:
    st.warning("⚠️ 赤旗に該当する可能性があります： " + " / ".join(red_flags))
    proceed = st.sidebar.toggle("受診を前提に、軽い注意点だけ確認する", value=False)
    if not proceed: st.stop()
    proceed_note = "（赤旗該当のため運動は控えめ。痛みが増す動きは避け、受診を最優先）"
else:
    proceed_note = ""

st.divider()

# ---------- 入力UI（自由記載を追加） ----------
part = st.radio("痛みが強い場所を選んでください：",
                ["腰","お尻・太もも","ふくらはぎ/足","その他（自由入力）"])
if part == "腰":
    type_options = ["慢性的な鈍痛","急に出た鋭い痛み（ギクッと）","お尻や足に広がる/しびれる","その他（自由入力）"]
elif part == "お尻・太もも":
    type_options = ["慢性的な痛み","鋭い痛み/ピリッと走る","足先まで広がる/しびれ","その他（自由入力）"]
elif part == "ふくらはぎ/足":
    type_options = ["しびれがある","鋭い痛み","筋肉が張る・つりやすい","その他（自由入力）"]
else:
    type_options = ["痛み中心","しびれ中心","こわばり/張り中心","その他（自由入力）"]

ptype = st.radio("症状のタイプは？", type_options)
if ptype == "その他（自由入力）":
    ptype = st.text_input("自由入力（症状のタイプ）") or "その他（詳細未入力）"

st.subheader("追加の評価")
intensity = st.radio("今の痛みの強さ（目安）", ["0〜3（軽い）","4〜6（中等度）","7〜10（強い〜最強）","その他（自由入力）"])
if intensity == "その他（自由入力）":
    intensity = st.text_input("自由入力（痛みの強さ）") or "その他（詳細未入力）"
onset = st.radio("発症からの期間", ["急性（〜6週間）","亜急性（6〜12週間）","慢性（3か月〜）","その他（自由入力）"])
if onset == "その他（自由入力）":
    onset = st.text_input("自由入力（発症期間）") or "その他（詳細未入力）"
diurnal = st.radio("一日の中で強くなるタイミング", ["朝に強い","夕方〜夜に強い","変わらない","その他（自由入力）"])
if diurnal == "その他（自由入力）":
    diurnal = st.text_input("自由入力（日内変動）") or "その他（詳細未入力）"
factor = st.radio("当てはまるもの（最も近いもの）",
                  ["長時間座りっぱなし","前かがみや重い物で悪化","朝より夕方に悪化/歩くと楽","その他（自由入力）"])
if factor == "その他（自由入力）":
    factor = st.text_input("自由入力（背景・増悪因子）") or "その他（詳細未入力）"

# ★ 自由記載（新規追加）
free_text = st.text_area(
    "症状の自由記載（きっかけ・いつから・既往歴・画像所見・服薬・試したこと・NGにしてほしい助言など）",
    height=140, placeholder="例：3週間前に重い荷物を持ってから悪化。朝はこわばり、前かがみで強くなる。市販NSAIDsで少し楽。筋トレは続かないので生活動作の工夫中心がいい。"
)

# 詳細レベル
detail = st.slider("出力の詳細レベル", 1, 5, 4, help="値が大きいほど具体例や手順を増やします")

st.divider()

# ---------- 生成 ----------
def build_user_summary():
    hist = f"\n【直近の相談と出力の要旨】\n{history_text}\n" if history_text else ""
    ref  = f"\n【参考資料の抜粋】\n{extra_ref[:2000]}\n" if extra_ref else ""
    prof = f"\n【制作者の発信・方針】\n{profile_text[:1500]}\n" if profile_text else ""
    ft   = f"\n【症状の自由記載】\n{free_text}\n" if free_text else ""
    return (
        f"【安全注記】{proceed_note}\n"
        f"部位: {part}\n"
        f"タイプ: {ptype}\n"
        f"痛み強度: {intensity}\n"
        f"発症期間: {onset}\n"
        f"日内変動: {diurnal}\n"
        f"増悪因子/背景: {factor}\n"
        f"【具体性の指示】レベル{detail}。具体例（1日のルーティン/回数/頻度/所要時間）を入れる。\n"
        + prof + hist + ref + ft +
        "以下の見出し・順番・分量でMarkdown出力：\n"
        "## 可能性のある原因（メカニズム・生活要因）\n"
        "## 考えられること（鑑別の方向性：断定しない）\n"
        "## セルフケアの提案（手順は短く）\n"
        "## 避ける動き\n"
        "## 受診の目安\n"
    )

def local_advice():
    # デモ時は自由記載・方針を軽く反映
    lines = []
    if profile_text:
        lines.append(f"制作者の方針に配慮：{profile_text.splitlines()[0][:40]} …")
    if free_text:
        lines.append(f"自由記載の要点：{free_text[:80]} …")
    base = (
        "## 可能性のある原因（メカニズム・生活要因）\n"
        "- 姿勢や活動量の偏りによる筋・筋膜の過緊張\n"
        "- 座位や前かがみ作業の増加による負担\n\n"
        "## 考えられること（鑑別の方向性：断定しない）\n"
        "- 筋・筋膜性の痛みの傾向\n"
        "- 坐骨神経への刺激（しびれがある場合）\n\n"
        "## セルフケアの提案（手順は短く）\n"
        "1. 30–60分ごとに立って1–2分歩く（タイマー推奨）\n"
        "2. 前かがみ作業は股関節から曲げる練習を1日3回×3分\n"
        "3. ふくらはぎストレッチ20秒×3を朝夕\n"
        "4. 楽な範囲で5–10分の歩行を1日2回\n\n"
        "## 避ける動き\n"
        "- 痛みが増える動作の反復\n"
        "- 急に重い物を持ち上げる\n\n"
        "## 受診の目安\n"
        "- 発熱・外傷後・排尿排便障害・急な麻痺/広範なしびれ\n"
        "- 改善が数週間以上乏しい/夜間増悪/歩行困難が続く\n"
    )
    if lines:
        return "\n".join([f"> {l}" for l in lines]) + "\n\n" + base
    return base

if st.button("✅ アドバイスを生成する", type="primary"):
    user_summary = build_user_summary()

    if DEMO:
        advice = local_advice()
    else:
        try:
            with st.spinner("AIが提案を作成中…"):
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_summary},
                    ],
                    temperature=0.6,
                )
                advice = resp.choices[0].message.content.strip()
        except Exception as e:
            st.error(f"API呼び出しでエラー：{e}")
            st.info("デモモードに自動切替して続行します。")
            advice = local_advice()

    st.subheader("📝 出力")
    st.markdown(advice)

    # ---- ログ保存 ----
    LOG_PATH = LOG_DIR / f"painlog_{dt.datetime.now().strftime('%Y%m%d')}.csv"
    write_header = not LOG_PATH.exists()
    row = {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "model": MODEL if not DEMO else "LOCAL-DEMO",
        "red_flag": "YES" if has_red_flag else "NO",
        "red_flag_list": " / ".join(red_flags),
        "part": part, "type": ptype, "intensity": intensity,
        "onset": onset, "diurnal": diurnal, "factor": factor,
        "free_text": free_text.replace("\n"," / "),
        "profile_used": "YES" if profile_text else "NO",
        "history_used": "YES" if use_history else "NO",
        "advice": advice.replace("\n"," / "),
        "detail": detail,
    }
    with LOG_PATH.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header: w.writeheader()
        w.writerow(row)
    st.success(f"ログ保存完了: {LOG_PATH.resolve()}")
