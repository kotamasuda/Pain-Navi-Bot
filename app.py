# -*- coding: utf-8 -*-
# 痛みナビBot（Streamlit・コピペ即動作）
# - デモモード既定ON（OpenAI不要） / OpenAI任意
# - 出力の見出し固定（鑑別・セルフケア・回避動作・受診目安）
# - 赤旗チェック（手動＋自動） / 履歴参照 / CSVログ / 参考資料＆方針の反映
# - 部位：肩/首・腰・お尻/太もも・股関節・膝・ふくらはぎ/足・肘・手首・足首・その他

import os, csv, glob, re
import datetime as dt
from pathlib import Path
import streamlit as st

# ================= ユーティリティ =================
def secret_get(key: str, default: str = "") -> str:
    """secrets.toml が無くても安全に既定値を返す"""
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

# ================= ページ設定 =================
st.set_page_config(page_title="痛みナビBot", layout="centered")
st.title("痛みナビBotくん🤖")
st.caption("※診断ではありません。危険サインがあれば医療機関の受診を最優先。")

# ================= OpenAIクライアント（任意） =================
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # デモなら不要

st.sidebar.subheader("設定")
DEMO = True  # ← デモ固定
st.sidebar.caption("デモモード固定（APIは使用しません）")
use_own_key = False

def get_client():
    return None  # デモ固定なのでAPIは使わない

    server_key = os.environ.get("OPENAI_API_KEY", "") or secret_get("OPENAI_API_KEY", "")
    user_key = ""
    if use_own_key:
        user_key = st.sidebar.text_input("OpenAI APIキー（利用者）", type="password", key="user_api_key")
    api_key = (user_key or server_key).strip()
    if not api_key:
        st.sidebar.warning("APIキーがありません。デモモードONのまま使うか、Secrets/環境変数に設定してください。")
        st.stop()
    if OpenAI is None:
        st.error("openai ライブラリが必要です。`python3 -m pip install openai`")
        st.stop()
    return OpenAI(api_key=api_key)

client = get_client()
MODEL = "LOCAL-DEMO"

# ================= 制作者の方針 / 参考資料 / 履歴 =================
PROFILE_PATH = Path("profile_masuda.md")
profile_default = secret_get("PROFILE_MASUDA", "")
if not profile_default and PROFILE_PATH.exists():
    profile_default = PROFILE_PATH.read_text(encoding="utf-8")

profile_text = st.sidebar.text_area(
    "あなたの発信・方針（保存可）",
    value=profile_default,
    height=160,
    placeholder="例：診断名に固執しない／生活で続けられる工夫を最優先／朝のルーティンを必ず提案… など",
)
c1, c2 = st.sidebar.columns(2)
if c1.button("保存", key="save_profile"):
    try:
        PROFILE_PATH.write_text(profile_text, encoding="utf-8")
        st.sidebar.success("保存しました")
    except Exception as e:
        st.sidebar.error(f"保存に失敗: {e}")
if c2.button("再読込", key="reload_profile"):
    if PROFILE_PATH.exists():
        st.rerun()

uploaded = st.sidebar.file_uploader("参考資料を添付（.txt / .md）", type=["txt", "md"])
extra_ref = uploaded.read().decode("utf-8") if uploaded else ""

LOG_DIR = Path("logs"); LOG_DIR.mkdir(exist_ok=True)
def load_recent_logs(n=3) -> str:
    files = sorted(glob.glob(str(LOG_DIR / "painlog_*.csv")))
    if not files: return ""
    last = files[-1]
    try:
        with open(last, "r", encoding="utf-8", newline="") as f:
            r = list(csv.DictReader(f))
        rows = []
        for row in r[-n:]:
            rows.append(f"部位:{row.get('part','')} / タイプ:{row.get('type','')} / 因子:{row.get('factor','')} / 抜粋:{row.get('advice','')[:160]}")
        return "\n".join(rows)
    except Exception:
        return ""

use_history = st.sidebar.toggle("過去ログを取り込む（直近3件）", value=False)
history_text = load_recent_logs(3) if use_history else ""

# ================= 出力見出し固定 =================
H_CAUSES   = "## 可能性のある原因（メカニズム・生活要因）"
H_DIFFS    = "## 考えられること（鑑別の方向性：断定しない）"
H_TIPS     = "## セルフケアの提案（手順は短く）"
H_AVOID    = "## 避ける動き"
H_REFERRAL = "## 受診の目安"

SYSTEM_PROMPT = (
    "あなたは腰痛・坐骨神経痛などの一般向けセルフケアを案内する理学療法の専門家です。"
    "・“赤旗”症状（外傷/発熱/排尿排便障害/急な麻痺 など）があれば受診を最優先するよう促す。"
    "・自宅でできる安全なセルフケア（姿勢/生活習慣/軽い運動）を短く具体的に、箇条書き中心で示す。"
    "・専門用語は控えめ、断定的診断は避ける、痛みが増える動きは無理しないと明記する。"
    "出力は必ず次のMarkdown見出しの順で、各セクション3〜6項目にまとめる："
    f"{H_CAUSES}{H_DIFFS}{H_TIPS}{H_AVOID}{H_REFERRAL}"
    "・セルフケアの提案は最低3件（目安5件）。重要度の高い順に番号付きで、末尾に（優先度★★★/★★/★）を付ける。"
)
if profile_text:
    SYSTEM_PROMPT = profile_text.strip() + "\n\n" + SYSTEM_PROMPT

def normalize_headings(md: str) -> str:
    if not isinstance(md, str):
        try:
            md = "" if md is None else str(md)
        except Exception:
            return ""
    mapping = {
        "## 回避の動き": H_AVOID,
        "## 回避すべき動き": H_AVOID,
        "## 注意すべき動き": H_AVOID,
        "## 受診すべき場合": H_REFERRAL,
        "## 注意が必要なサイン": H_REFERRAL,
    }
    for k, v in mapping.items():
        md = md.replace(k, v)
    # 必須見出しが無ければテンプレで補完
    if H_CAUSES not in md:
        md = f"{H_CAUSES}\n- \n\n{H_DIFFS}\n- \n\n{H_TIPS}\n1. （優先度★★）\n\n{H_AVOID}\n- \n\n{H_REFERRAL}\n- \n"
    return md

# ================= 赤旗チェック（手動＋自動） =================
st.sidebar.markdown("### 🩺 安全確認（赤旗チェック）")
flag_trauma   = st.sidebar.checkbox("最近の強い外傷（転倒・交通事故など）がある")
flag_fever    = st.sidebar.checkbox("38℃以上の発熱や悪寒などの体調不良がある")
flag_cauda    = st.sidebar.checkbox("排尿/排便障害・会陰部のしびれがある（馬尾症状の疑い）")
flag_weakness = st.sidebar.checkbox("足に力が入りにくい等の進行性の麻痺がある")

red_flags_manual = [name for name, on in [
    ("強い外傷", flag_trauma),
    ("発熱/感染疑い", flag_fever),
    ("排尿排便障害/馬尾症状疑い", flag_cauda),
    ("進行する神経症状", flag_weakness),
] if on]

# ================= 入力UI =================
part_choice = st.radio(
    "痛みが強い場所を選んでください：",
    ["肩/首","腰","お尻・太もも","股関節","膝","ふくらはぎ/足","肘","手首","足首","その他（自由入力）"],
    key="part_radio"
)
if part_choice == "その他（自由入力）":
    part_free = st.text_input("自由入力（痛みの場所）", placeholder="例：肩甲骨の内側／背中の右側／すねの外側 など", key="part_free")
    part = part_free.strip() or "その他（詳細未入力）"
else:
    part = part_choice

type_options_map = {
    "腰": ["慢性的な鈍痛","急に出た鋭い痛み（ギクッと）","お尻や足に広がる/しびれる","その他（自由入力）"],
    "お尻・太もも": ["慢性的な痛み","鋭い痛み/ピリッと走る","足先まで広がる/しびれ","その他（自由入力）"],
    "ふくらはぎ/足": ["しびれがある","鋭い痛み","筋肉が張る・つりやすい","その他（自由入力）"],
    "肩/首": ["動かすと痛い","しびれがある","重だるい/こり","その他（自由入力）"],
    "股関節": ["前面が痛い","側面/お尻側が痛い","動かし始めに痛い","その他（自由入力）"],
    "膝": ["階段で痛い","曲げ伸ばしで痛い","クリック/引っかかる","その他（自由入力）"],
    "肘": ["物を掴むと痛い","手首を反らすと痛い","その他（自由入力）"],
    "手首": ["反らすと痛い","手のしびれ","タイピングで悪化","その他（自由入力）"],
    "足首": ["捻挫後","アキレス周りが痛い","長く歩くと痛い","その他（自由入力）"],
    "その他（自由入力）": ["痛み中心","しびれ中心","こわばり/張り中心","その他（自由入力）"],
}
type_options = type_options_map.get(part_choice, type_options_map["その他（自由入力）"])

ptype = st.radio("症状のタイプは？", type_options, key="ptype_radio")
if ptype == "その他（自由入力）":
    ptype = st.text_input("自由入力（症状のタイプ）", key="ptype_free").strip() or "その他（詳細未入力）"

intensity = st.radio("今の痛みの強さ（目安）", ["0〜3（軽い）","4〜6（中等度）","7〜10（強い〜最強）","その他（自由入力）"], key="intensity_radio")
if intensity == "その他（自由入力）":
    intensity = st.text_input("自由入力（痛みの強さ）", key="intensity_free") or "その他（詳細未入力）"

onset = st.radio("発症からの期間", ["急性（〜6週間）","亜急性（6〜12週間）","慢性（3か月〜）","その他（自由入力）"], key="onset_radio")
if onset == "その他（自由入力）":
    onset = st.text_input("自由入力（発症期間）", key="onset_free") or "その他（詳細未入力）"

diurnal = st.radio("一日の中で強くなるタイミング", ["朝に強い","夕方〜夜に強い","変わらない","その他（自由入力）"], key="diurnal_radio")
if diurnal == "その他（自由入力）":
    diurnal = st.text_input("自由入力（日内変動）", key="diurnal_free") or "その他（詳細未入力）"

factor = st.radio("当てはまるもの（最も近いもの）",
                  ["長時間座りっぱなし","前かがみや重い物で悪化","朝より夕方に悪化/歩くと楽","その他（自由入力）"],
                  key="factor_radio")
if factor == "その他（自由入力）":
    factor = st.text_input("自由入力（背景・増悪因子）", key="factor_free") or "その他（詳細未入力）"

free_text = st.text_area(
    "症状の自由記載（きっかけ・いつから・既往歴・画像所見・服薬・試したこと・NGにしてほしい助言など）",
    height=140,
    placeholder="例：3週間前に重い荷物で悪化。朝こわばる／前かがみで増悪。市販鎮痛で少し楽。筋トレは続かないので生活動作の工夫中心がよい など",
    key="free_text"
)
detail = st.slider("出力の詳細レベル", 1, 5, 4, help="大きいほど具体例や手順を増やします", key="detail_slider")

st.divider()

# ================= 自動赤旗検出 =================
RED_FLAG_PATTERNS = [
    r"膀胱|尿(の|が)?出(ない|づらい|にくい)|失禁|直腸|便(が)?出ない",
    r"会陰部|サドル麻痺|鞍部",
    r"つま先立ちできない|急(な|に)筋力低下|足(が)?急激に(痩|や)せ",
    r"発熱|原因不明の体重減少|がん|癌",
    r"交通事故|大怪我|外傷",
]
auto_red = any(re.search(rx, free_text or "") for rx in RED_FLAG_PATTERNS)
red_flags = list(red_flags_manual)
if auto_red and "自動検出" not in red_flags:
    red_flags.append("自動検出: 危険サインの語句を含む可能性")

has_red_flag = len(red_flags) > 0
if has_red_flag:
    st.warning("⚠️ 赤旗に該当する可能性があります： " + " / ".join(red_flags))
    proceed = st.sidebar.toggle("受診を前提に、軽い注意点だけ確認する", value=False, key="rf_proceed")
    if not proceed:
        st.stop()
    proceed_note = "（赤旗該当のため運動は控えめ。痛みが増す動きは避け、受診を最優先）"
else:
    proceed_note = ""

# ================= 要約（プロンプト入力用） =================
def build_user_summary():
    hist = f"\n【直近の相談と出力の要旨】\n{history_text}\n" if history_text else ""
    ref  = f"\n【参考資料の抜粋】\n{extra_ref[:2000]}\n" if extra_ref else ""
    prof = f"\n【制作者の発信・方針】\n{profile_text[:1500]}\n" if profile_text else ""
    ft   = f"\n【症状の自由記載】\n{free_text}\n" if free_text else ""
    return (
        f"【安全注記】{proceed_note}\n"
        f"部位: {part}\nタイプ: {ptype}\n痛み強度: {intensity}\n発症期間: {onset}\n"
        f"日内変動: {diurnal}\n増悪因子/背景: {factor}\n"
        f"【具体性の指示】レベル{detail}。具体例（1日のルーティン/回数/頻度/所要時間）を入れる。\n"
        + prof + hist + ref + ft +
        "以下の見出し・順番でMarkdown出力：\n"
        f"{H_CAUSES}\n{H_DIFFS}\n{H_TIPS}\n{H_AVOID}\n{H_REFERRAL}\n"
    )

# ================= デモ用ロジック（優先度つき/3〜5件保証） =================
def local_advice():
    causes, diffs, avoid = [], [], []
    tips_hi, tips_mid, tips_low = [], [], []

    def uniq_extend(dst, items):
        for x in items:
            if x and x not in dst:
                dst.append(x)

    def format_prioritized(hi, mid, low):
        ordered = [(3, t) for t in hi] + [(2, t) for t in mid] + [(1, t) for t in low]
        seen, uniq = set(), []
        for pr, t in ordered:
            if t not in seen:
                uniq.append((pr, t)); seen.add(t)
        pad_pool = [
            "60分ごとに1–2分立って歩く（タイマー推奨）",
            "前かがみ作業は股関節から曲げるフォーム練習を1日3回×3分",
            "ふくらはぎストレッチ20秒×3（朝/入浴後）",
            "5–10分の楽な歩行を1日2回",
            "腰に薄いタオルを当てて座る（骨盤を立てる）",
        ]
        for t in pad_pool:
            if len(uniq) >= 5: break
            if t not in {u[1] for u in uniq}:
                uniq.append((2, t))
        base = [
            (3, "60分ごとに1–2分立って歩く（タイマー推奨）"),
            (3, "前かがみ作業は股関節から曲げるフォーム練習"),
            (2, "5–10分の楽な歩行を1日2回"),
        ]
        i = 0
        while len(uniq) < 3 and i < len(base):
            if base[i][1] not in {u[1] for u in uniq}:
                uniq.append(base[i])
            i += 1
        uniq = uniq[:5]
        lines = [f"{i}. {t}（優先度{'★'*pr}）" for i, (pr, t) in enumerate(uniq, 1)]
        return "\n".join(lines)

    txt_all = " ".join([s for s in [part, free_text, factor, diurnal, ptype] if isinstance(s, str)])
    def has_any(words): return any(w in txt_all for w in words)

    # ---- 部位別（要点ベース）----
    if part == "腰":
        uniq_extend(causes, ["腰部の筋・筋膜の過緊張", "骨盤/胸郭位置の崩れによる持続負荷"])
        if ("鋭" in ptype) or ("ギク" in ptype):
            uniq_extend(diffs, ["椎間板/靱帯ストレス（前屈で増悪）"])
            tips_hi += ["台に手を置いて作業（腰を丸めすぎない）","仰向け膝立て＋腹式呼吸1分×3"]
            tips_mid += ["股関節から曲げるフォーム練習（1日3回×3分）"]
            avoid += ["深い前屈","勢いよく反る"]
        elif ("しびれ" in ptype) or ("広が" in ptype):
            uniq_extend(diffs, ["神経根刺激の可能性（長時間座位で増悪）"])
            tips_hi += ["60分ごと立って1–2分歩く","腰当て（薄タオル）で骨盤を立てる"]
            tips_mid += ["背もたれ使用＋座面奥に座る"]
            avoid += ["長時間の座位","無理な前屈"]
        else:
            tips_hi += ["60分ごとに立って1–2分歩く"]
            tips_mid += ["股関節ヒンジ練習（1日3回×3分）"]

    elif part == "お尻・太もも":
        uniq_extend(causes, ["臀筋群の硬さ/使いすぎ","坐骨神経の滑走低下"])
        if ("鋭" in ptype) or ("ピリ" in ptype):
            uniq_extend(diffs, ["梨状筋周囲の過緊張による神経刺激"])
            tips_hi += ["尻ポケットに長財布/スマホを入れない"]
            tips_mid += ["仰向け片膝抱えストレッチ20秒×3（左右）"]
        elif ("しびれ" in ptype) or ("広が" in ptype):
            uniq_extend(diffs, ["神経滑走の低下（長座/長距離運転で増悪）"])
            tips_hi += ["椅子をやや高めにして股関節角度を広げる"]
            tips_mid += ["短時間の早歩きを1日2回（増悪しない範囲）"]
        else:
            tips_mid += ["臀部のやさしいボールほぐし（各30秒）"]

    elif part == "ふくらはぎ/足":
        if "しびれ" in ptype:
            uniq_extend(diffs, ["末梢神経の刺激/血流低下の可能性"])
        elif ("張" in ptype) or ("つり" in ptype):
            uniq_extend(diffs, ["腓腹筋・ヒラメ筋の過緊張/疲労"])
        tips_hi += ["ふくらはぎストレッチ20秒×3（朝/入浴後）"]
        tips_mid += ["つま先上げ下げ20回×2（座位OK）"]
        avoid += ["急な坂道ダッシュ","長時間の爪先立ち"]

    elif part in ["肩/首","肩","首"] or has_any(["肩","肩甲骨","首","頸","うなじ","回すと","動かすと"]):
        uniq_extend(causes, ["頸肩部の筋・筋膜の過緊張", "肩甲骨挙上/前傾＋胸郭後方シフト"])
        if has_any(["しびれ","腕","手まで"]):
            uniq_extend(diffs, ["頸椎神経根刺激／胸郭出口の可能性"])
            tips_hi += ["スマホ首回避：画面は目線・肘90°支持","頸部回旋/側屈を各5回（1–2時間ごと）"]
            tips_mid += ["神経滑走：腕外転＋手のひら上⇄下10回"]
            avoid += ["長時間のうつむき","強い牽引や強ストレッチ"]
        else:
            tips_hi += ["毎時1回の姿勢リセット（立って胸を開き深呼吸3回）",
                        "前鋸筋活性：四つ這いで小指球押し10回"]
            tips_mid += ["僧帽筋下部：壁スライド10回（肩すくめない）"]

    elif part in ["股関節","股"] or has_any(["股","股関節","鼠径","そけい"]):
        uniq_extend(causes, ["股関節前面の過負荷／腸腰筋・殿筋のアンバランス"])
        uniq_extend(diffs, ["前方インピンジ（前傾＋内/外旋）／後方インピンジ（後傾＋外旋）傾向"])
        tips_hi += ["ヒップヒンジ10回×2（背中は丸めない）","グルートブリッジ10回×2（痛くない範囲）"]
        tips_mid += ["長時間座位を避け60分ごとに立つ","歩幅をやや小さくして歩く"]
        avoid += ["反り腰の維持","勢いよく脚を大きく振る"]

    elif part in ["膝","ひざ"] or has_any(["膝","ひざ","膝蓋","階段","しゃがむ"]):
        uniq_extend(causes, ["膝蓋大腿部へのストレス増／周囲筋のアンバランス","反張膝傾向（過伸展）"])
        uniq_extend(diffs, ["膝蓋大腿痛／半月板刺激（クリック・階段で増悪など）"])
        tips_hi += ["クワッドセッティング5秒×10（1日3回）","横向きクラムシェル10回×2（痛くない範囲）"]
        tips_mid += ["微屈での立位練習（わずかに膝を緩める）","階段は手すり使用・下りは小刻みに"]
        avoid += ["急な下り坂ダッシュ","長時間の深屈曲","膝をロックした立位"]

    elif part == "肘" or has_any(["肘","テニス肘","外側上顆","雑巾絞り","強い握り"]):
        uniq_extend(causes, ["手首背屈筋の使いすぎによる付着部ストレス"])
        uniq_extend(diffs, ["外側上顆炎（把持で増悪）"])
        tips_hi += ["グリップを太めに変更（道具/マウス）","前腕伸筋のエキセントリック10回×2"]
        tips_mid += ["前腕の軽いマッサージ30秒×2","カウンターフォースバンド（短時間）"]
        avoid += ["強い握り込み・雑巾絞り反復"]

    elif part in ["手首","手"] or has_any(["手首","手のひら","キーボード","腱鞘炎","腕立て"]):
        uniq_extend(causes, ["手関節の反復伸展／屈曲による腱・神経の刺激"])
        uniq_extend(diffs, ["腱鞘炎／手根管症候群の可能性"])
        tips_hi += ["手首ニュートラル：手首置き利用・マウス感度UP","掌支持は拳/バーで代替"]
        tips_mid += ["正中神経グライド10回×2（増悪しない範囲）","20-8-2ルールでこまめに休憩"]
        avoid += ["深い手首反りで荷重","長時間の同一姿勢"]

    elif part in ["足首","足関節"] or has_any(["足首","捻挫","段差","つまずき","アキレス"]):
        uniq_extend(causes, ["足関節不安定性／下腿三頭筋の過負荷"])
        uniq_extend(diffs, ["外側靭帯軽度損傷／アキレス腱周囲炎の可能性"])
        tips_hi += ["片脚立ち30秒×2（安全確保）→慣れたら難度UP","カーフレイズ10回×2（増悪しない範囲）"]
        tips_mid += ["足首のABC運動×1セット/日","凸凹路面は当面回避"]
        avoid += ["ジャンプ反復","不安定な靴での長時間歩行"]

    # ---- 背景因子・期間・強さ・自由記載（共通）----
    if "座" in factor:
        uniq_extend(causes, ["長時間座位で腰背部に持続的負担"])
        tips_hi += ["60分ごとに立って1–2分歩く"]
        tips_mid += ["座面奥に座り背もたれを使う"]
        avoid += ["同じ姿勢を長時間続ける"]
    if ("前かが" in factor) or ("重い物" in factor) or ("持ち上げ" in txt_all):
        uniq_extend(causes, ["前屈＋荷重で椎間板・靱帯にストレス"])
        tips_hi += ["荷物は体に近づけ、ねじらず持ち上げる（股関節から曲げる）"]
        avoid += ["前かがみで重い物を持つ"]
    if ("夕方" in diurnal) or ("歩くと楽" in factor) or ("歩くと楽" in txt_all):
        uniq_extend(diffs, ["脊柱管狭窄傾向（前屈で楽/歩行で改善しやすい）"])
        tips_mid += ["5–10分の楽な散歩を1日2–3回"]

    if "急性" in onset:
        tips_hi += ["初期48–72時間は“楽な範囲”の生活動作（安静にし過ぎない）"]
    if "慢性" in onset:
        tips_mid += ["1日の合計活動量を少しずつ増やす（週10%目安）"]
    if any(k in intensity for k in ["7","8","9","10","最強"]):
        avoid += ["痛みが増える動きの反復"]
        tips_hi += ["短時間・低負荷で様子見し、楽な姿勢で休む"]

    kw = (free_text or "")
    if any(k in kw for k in ["ラン", "ジョグ", "走"]):
        uniq_extend(diffs, ["オーバーユース（走行距離/ペース急増）"])
        tips_mid += ["距離を半分・ペース1段階下げて1週間様子見"]
    if any(k in kw for k in ["デスク", "PC", "運転"]):
        tips_mid += ["作業環境：モニタ目線・肘90°・足裏は床ベタ置き"]

    if not causes: uniq_extend(causes, ["姿勢や活動量の偏りによる筋・筋膜の過緊張"])
    if not diffs:   uniq_extend(diffs, ["筋・筋膜性の痛みの傾向"])
    if not avoid:   uniq_extend(avoid, ["急に重い物を持つ","痛みが増える動作の反復"])

    tips_md = format_prioritized(tips_hi, tips_mid, tips_low)

    note = [
        "発熱・外傷後・排尿排便障害・急な麻痺/広範なしびれ",
        "改善が数週間以上乏しい/夜間増悪/歩行困難が続く",
    ]
    if "受診" in proceed_note:
        note.insert(0, proceed_note.strip("（）"))

    return (
        f"{H_CAUSES}\n- " + "\n- ".join(causes[:6]) + "\n\n"
        f"{H_DIFFS}\n- " + "\n- ".join(diffs[:6]) + "\n\n"
        f"{H_TIPS}\n" + tips_md + "\n\n"
        f"{H_AVOID}\n- " + "\n- ".join(avoid[:5]) + "\n\n"
        f"{H_REFERRAL}\n- " + "\n- ".join(note) + "\n"
    )

# ================= 生成ボタン =================
if st.button("✅ アドバイスを生成する", type="primary", key="generate_main"):
    user_summary = build_user_summary()
    if DEMO:
        advice = local_advice()
    else:
        try:
            with st.spinner("AIが提案を作成中…"):
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role":"system","content":SYSTEM_PROMPT},
                              {"role":"user","content":user_summary}],
                    temperature=0.6,
                )
                advice = resp.choices[0].message.content.strip()
        except Exception as e:
            st.error(f"API呼び出しでエラー：{e}")
            st.info("デモモードで続行します。")
            advice = local_advice()

    advice = normalize_headings(advice)
    st.subheader("📝 出力")
    st.markdown(advice)
