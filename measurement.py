import cv2
import numpy as np

from config import (
    BACKGROUND_KERNEL_PX,
    BORDER_MARGIN_PX,
    HYSTERESIS_LOW_RATIO,
    MAJOR_AXIS_LARGE_MM,
    MAJOR_AXIS_SMALL_MM,
    MIN_CONTOUR_AREA_PX,
)
from crossing import separate_strips


def preprocess_backlit(gray_image, exclude_mask):
    """逆光撮影の画像を、照明ムラを補正したうえで「暗い背景に明るい物体」の画像に変換する。

    クロージングで物体を消して背景の明るさを推定し、背景に対する暗さの割合を0〜255で表す。
    exclude_mask (255=除外) の領域と鳥瞰図の外周は0にする。
    """
    gray = gray_image.astype(np.float32)
    # 背景は滑らかなので、縮小画像で推定して高速化する
    scale = 4
    small = cv2.resize(gray, None, fx=1 / scale, fy=1 / scale, interpolation=cv2.INTER_AREA)
    k = BACKGROUND_KERNEL_PX // scale | 1
    small_bg = cv2.morphologyEx(small, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    small_bg = cv2.GaussianBlur(small_bg, (0, 0), k / 3)
    background = cv2.resize(small_bg, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR)

    darkness = np.clip(255 * (1 - gray / np.maximum(background, 1)), 0, 255).astype(np.uint8)

    darkness[exclude_mask > 0] = 0
    m = BORDER_MARGIN_PX
    darkness[:m, :] = darkness[-m:, :] = 0
    darkness[:, :m] = darkness[:, -m:] = 0
    return darkness


def binarize(darkness, threshold_val):
    """ヒステリシスしきい値で二値化する。

    threshold_val を超える画素を1つでも含む領域について、
    threshold_val × HYSTERESIS_LOW_RATIO を超える範囲までを物体とする。
    """
    weak = (darkness > threshold_val * HYSTERESIS_LOW_RATIO).astype(np.uint8)
    n, labels = cv2.connectedComponents(weak, connectivity=8)
    keep = np.zeros(n, bool)
    keep[np.unique(labels[darkness > threshold_val])] = True
    keep[0] = False
    return np.where(keep[labels], 255, 0).astype(np.uint8)


def segment_objects(gray_image_masked, threshold_val):
    """二値化し、交差したコセットを分離した結果 (SeparationResult) を返す。"""
    return separate_strips(binarize(gray_image_masked, threshold_val))


def measure_contours(contours, mm_per_pixel):
    """輪郭ごとに長辺・短辺・面積を算出する。CSV用データと描画情報を分けて返す。"""
    dimensions_mm = []
    object_data = []
    drawings = []  # (box_points, color, major_axis_mm, minor_axis_mm, area_mm2)
    ignored_count = 0

    for cnt in contours:
        area_px = cv2.contourArea(cnt)
        if area_px < MIN_CONTOUR_AREA_PX:
            ignored_count += 1
            continue

        rect = cv2.minAreaRect(cnt)
        box = np.intp(cv2.boxPoints(rect))

        width_px, height_px = rect[1]
        major_axis_mm = max(width_px, height_px) * mm_per_pixel
        minor_axis_mm = min(width_px, height_px) * mm_per_pixel
        area_mm2 = area_px * (mm_per_pixel ** 2)

        dimensions_mm.append({'major': major_axis_mm, 'minor': minor_axis_mm})
        object_data.append({
            'ID': len(object_data) + 1,
            'Major_Axis_mm': f"{major_axis_mm:.2f}",
            'Minor_Axis_mm': f"{minor_axis_mm:.2f}",
            'Area_mm2': f"{area_mm2:.2f}"
        })

        color = (128, 128, 255)
        if major_axis_mm >= MAJOR_AXIS_LARGE_MM:
            color = (0, 0, 255)
        elif major_axis_mm < MAJOR_AXIS_SMALL_MM:
            color = (255, 0, 0)

        drawings.append((box, color, major_axis_mm, minor_axis_mm, area_mm2))

    return dimensions_mm, object_data, drawings, ignored_count


def compute_statistics(dimensions_mm):
    """長辺の分布からK1〜K3・AISwなどの統計量を算出する。オブジェクトが無ければNone。"""
    if not dimensions_mm:
        return None

    major_axes = np.array([d['major'] for d in dimensions_mm])
    object_count = len(major_axes)

    k1 = np.sum(np.square(major_axes)) / np.sum(major_axes)
    k2 = (np.sum(major_axes >= MAJOR_AXIS_LARGE_MM) / object_count) * 100

    mean_val, std_dev = np.mean(major_axes), np.std(major_axes)
    k3 = np.mean(((major_axes - mean_val) / std_dev) ** 3) if std_dev > 0 else 0

    sum_ge_50 = np.sum(major_axes[major_axes >= MAJOR_AXIS_LARGE_MM])
    sum_lt_10 = np.sum(major_axes[major_axes < MAJOR_AXIS_SMALL_MM])
    aisw = sum_ge_50 / sum_lt_10 if sum_lt_10 > 0 else float('inf')

    return {
        'total': np.sum(major_axes),
        'max': np.max(major_axes),
        'mean': np.mean(major_axes),
        'k1': k1,
        'k2': k2,
        'k3': k3,
        'aisw': aisw,
    }


def _format_report_lines(mm_per_pixel, threshold_val, file_name_with_ext, timestamp,
                          contours_count, crossings_count, drawings, ignored_count, stats):
    output_lines = [f"--- 測定開始: {timestamp.strftime('%Y-%m-%d %H:%M:%S')} ---"]
    output_lines.append(f"入力ファイル: {file_name_with_ext}")
    output_lines.append(f"使用スケール: {mm_per_pixel:.4f} mm/pixel")
    output_lines.append(f"二値化しきい値: {threshold_val}")

    for i, (_box, _color, major_axis_mm, minor_axis_mm, area_mm2) in enumerate(drawings, start=1):
        output_lines.append(
            f"  オブジェクト {i}: 長辺 {major_axis_mm:.2f} mm, 短辺 {minor_axis_mm:.2f} mm, 面積 {area_mm2:.2f} mm^2"
        )

    output_lines.append(f"\n検出された輪郭の総数: {contours_count}")
    output_lines.append(f"測定されたオブジェクト数: {len(drawings)}")
    output_lines.append(f"無視された輪郭の数: {ignored_count}")
    output_lines.append(f"検出された交差点の数: {crossings_count} (交差は分離して測定)")

    if stats:
        output_lines.append("\n=== 統計情報 (mm) ===")
        output_lines.append(f"  長辺の合計値: {stats['total']:.2f} mm")
        output_lines.append(f"  長辺の最大値: {stats['max']:.2f} mm")
        output_lines.append(f"  長辺の平均値: {stats['mean']:.2f} mm")
        output_lines.append(f"  K1 (加重平均長): {stats['k1']:.2f}")
        output_lines.append(f"  K2 (50mm以上の切片の割合): {stats['k2']:.2f}%")
        output_lines.append(f"  K3 (分布の歪度): {stats['k3']:.2f}")
        output_lines.append(f"  AISw (AIスウェーデン数): {stats['aisw']:.2f}")
        output_lines.append("==================")

    return output_lines


def process_frame(gray_image_masked, base_bird_eye_view, mm_per_pixel, threshold_val,
                   file_name_with_ext, timestamp):
    """指定しきい値で測定を実行し、(レポート行, CSV用データ, 輪郭描画済み画像) を返す。"""
    separation = segment_objects(gray_image_masked, threshold_val)
    dimensions_mm, object_data, drawings, ignored_count = measure_contours(separation.contours, mm_per_pixel)
    stats = compute_statistics(dimensions_mm)

    processed_bird_eye_view = base_bird_eye_view.copy()
    for box, color, *_ in drawings:
        cv2.drawContours(processed_bird_eye_view, [box], 0, color, 2)
    for x, y in separation.crossings:
        cv2.circle(processed_bird_eye_view, (int(x), int(y)), 6, (0, 255, 255), 2)

    output_lines = _format_report_lines(
        mm_per_pixel, threshold_val, file_name_with_ext, timestamp,
        len(separation.contours), len(separation.crossings), drawings, ignored_count, stats
    )

    return output_lines, object_data, processed_bird_eye_view
