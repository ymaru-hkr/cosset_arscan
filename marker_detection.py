from dataclasses import dataclass

import cv2
import numpy as np

from config import (
    CORNER_MARKER_IDS,
    DETECTOR,
    MARKER_CLAHE,
    MARKER_DISTANCE_X_MM,
    MARKER_DISTANCE_Y_MM,
    TARGET_HEIGHT_PX,
    TARGET_WIDTH_PX,
)


@dataclass
class MarkerDetectionResult:
    success: bool
    bird_eye_view: np.ndarray
    mm_per_pixel: float | None
    ar_marker_mask: np.ndarray


def detect_and_transform(frame):
    """ARマーカーを検出し、鳥瞰図への射影変換・mm/pixelスケール算出・マーカー除外マスク作成を行う。"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = DETECTOR.detectMarkers(MARKER_CLAHE.apply(gray))

    bird_eye_view = np.zeros((TARGET_HEIGHT_PX, TARGET_WIDTH_PX, 3), dtype=np.uint8)
    ar_marker_mask = np.zeros((TARGET_HEIGHT_PX, TARGET_WIDTH_PX), dtype=np.uint8)

    if ids is None:
        return MarkerDetectionResult(False, bird_eye_view, None, ar_marker_mask)

    cv2.aruco.drawDetectedMarkers(frame, corners, ids)
    # OpenCVのバージョンによって ids の形状が (N, 1) または (N,) になるため平坦化する
    detected_markers = {int(marker_id): corner for marker_id, corner in zip(np.asarray(ids).flatten(), corners)}

    if not CORNER_MARKER_IDS.issubset(detected_markers.keys()):
        return MarkerDetectionResult(False, bird_eye_view, None, ar_marker_mask)

    src_pts = np.float32([
        detected_markers[0][0][0], detected_markers[1][0][1],
        detected_markers[2][0][2], detected_markers[3][0][3]
    ])
    dst_pts = np.float32([
        [0, 0], [TARGET_WIDTH_PX - 1, 0],
        [TARGET_WIDTH_PX - 1, TARGET_HEIGHT_PX - 1], [0, TARGET_HEIGHT_PX - 1]
    ])
    matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)

    # --- スケール（mm/pixel）の動的計算 ---
    marker_centers_src = np.float32(
        [np.mean(detected_markers[i][0], axis=0) for i in range(4)]
    ).reshape(-1, 1, 2)
    marker_centers_dst = cv2.perspectiveTransform(marker_centers_src, matrix)

    dist_px_x = (np.linalg.norm(marker_centers_dst[0] - marker_centers_dst[1]) +
                 np.linalg.norm(marker_centers_dst[3] - marker_centers_dst[2])) / 2.0
    dist_px_y = (np.linalg.norm(marker_centers_dst[0] - marker_centers_dst[3]) +
                 np.linalg.norm(marker_centers_dst[1] - marker_centers_dst[2])) / 2.0

    mm_per_pixel = (MARKER_DISTANCE_X_MM / dist_px_x + MARKER_DISTANCE_Y_MM / dist_px_y) / 2.0

    bird_eye_view = cv2.warpPerspective(frame, matrix, (TARGET_WIDTH_PX, TARGET_HEIGHT_PX))

    # --- ARマーカー領域を鳥瞰図から除外するためのマスクを作成 ---
    for i in range(len(ids)):
        transformed_marker_corners = cv2.perspectiveTransform(corners[i], matrix)[0]
        cv2.fillPoly(ar_marker_mask, [np.int32(transformed_marker_corners)], 255)

    # ARマーカーマスクを膨張させて、周囲数ピクセルも除外対象に含める
    kernel = np.ones((15, 15), np.uint8)
    ar_marker_mask = cv2.dilate(ar_marker_mask, kernel, iterations=1)

    return MarkerDetectionResult(True, bird_eye_view, mm_per_pixel, ar_marker_mask)
