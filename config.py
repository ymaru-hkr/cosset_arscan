import cv2

# 基準となるマーカー間の実寸 (mm)
MARKER_DISTANCE_X_MM = 425.0
MARKER_DISTANCE_Y_MM = 275.0

# マーカー1辺の実寸 (mm)。画像からの推定値 (約23.5mm) なので、実寸が分かれば置き換える
MARKER_SIZE_MM = 24.0

# 射影変換後の鳥瞰図の画像サイズ (ピクセル)
# 鳥瞰図の四隅は各マーカーの外側の角なので、実寸は「中心間距離 + マーカー1辺」
PAPER_W_MM = MARKER_DISTANCE_X_MM + MARKER_SIZE_MM
PAPER_H_MM = MARKER_DISTANCE_Y_MM + MARKER_SIZE_MM
TARGET_WIDTH_PX = 800
TARGET_HEIGHT_PX = int(TARGET_WIDTH_PX * PAPER_H_MM / PAPER_W_MM)

# 4隅のマーカーID
CORNER_MARKER_IDS = {0, 1, 2, 3}

# Aruco辞書と検出器
ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
ARUCO_PARAMETERS = cv2.aruco.DetectorParameters()
DETECTOR = cv2.aruco.ArucoDetector(ARUCO_DICT, ARUCO_PARAMETERS)

# マーカー検出前のコントラスト補正（暗い背景に接したマーカーを検出しやすくする）
MARKER_CLAHE = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16))

# 測定・統計のしきい値
MIN_CONTOUR_AREA_PX = 5
MAJOR_AXIS_LARGE_MM = 50
MAJOR_AXIS_SMALL_MM = 10
DEFAULT_THRESHOLD = 70
# ヒステリシスしきい値: しきい値を超える濃い部分につながっていれば、
# 「しきい値 × この比率」までの薄い部分も同じ物体として含める (1本の中の濃淡で途切れないように)
HYSTERESIS_LOW_RATIO = 0.6

# 逆光撮影の前処理: 背景推定に使うカーネルサイズ (コセットの幅より十分大きくする)
BACKGROUND_KERNEL_PX = 51
# 鳥瞰図の外周で測定対象から除外する幅 (パネルの縁の影を拾わないため)
BORDER_MARGIN_PX = 10

# --- 交差（重なり）の分離 ---
# 長さの係数はすべて「典型的なコセットの幅」に対する倍率 (幅は画像から自動推定)
JUNCTION_MERGE_FACTOR = 1.0   # この範囲内の分岐点は1つの交差点にまとめる
BRIDGE_MAX_FACTOR = 1.5       # 2つの分岐点を結ぶこれより短い枝は交差点の一部とみなす
SPUR_MAX_FACTOR = 1.0         # これより短い端の枝はノイズ（輪郭のギザギザ）として除去する
DIRECTION_SAMPLE_FACTOR = 2.0 # 交差点からこの長さまでの枝で向きを求める
MAX_HOLE_AREA_FACTOR = 1.0    # 物体内部の「幅^2 × この値」以下の穴は埋める
WIDE_OBJECT_FACTOR = 1.8      # 幅がこれ以上太い物体は横並びの重なりを疑う
PAIR_MAX_ANGLE_DEG = 40       # 交差点で枝どうしをつなぐときに許容する曲がり角

# --- 画面表示 (live.py / main.py 共通) ---
DISPLAY_SIZE = (800, 480)           # 画面サイズ (ラズパイ公式7インチディスプレイ)
DISPLAY_FULLSCREEN = True

# --- ライブプレビュー (live.py) ---
LIVE_CAMERA_INDEX = 0               # Picamera2が使えない場合に使うUSBカメラの番号
LIVE_CAPTURE_SIZE = (1536, 864)     # プレビュー用の撮影解像度 (Camera Module 3 の16:9モード)
LIVE_SAVE_DIR = "photo"             # 's' / SAVE で撮影した画像の保存先
