"""カメラの読み込み。ラズパイ用カメラモジュール (CSI) とUSBカメラの両方に対応する。

- CSIカメラ: Picamera2 で開く
- USBカメラ: OpenCV (VideoCapture) で開く
  (libcamera はUSBカメラも認識するが、Picamera2 経由だとBGR形式・任意の解像度で取れないため)

open_camera() が CAMERA_BACKEND の設定に従って適切な方を返す。
どちらも read() でプレビュー用のBGR画像、capture_still() で測定用の高解像度BGR画像を返す。
"""
import glob
import os
import sys

import cv2

from config import (
    CAMERA_BACKEND,
    LIVE_CAMERA_INDEX,
    LIVE_CAPTURE_SIZE,
    USB_STILL_SIZE,
)

USB_SETTLE_FRAMES = 5  # USBカメラで解像度を切り替えた直後に捨てるフレーム数（露出が安定するまで）


class PiCamera:
    """ラズパイ用カメラモジュール (CSI) を Picamera2 で使う。"""

    def __init__(self, camera_num):
        from picamera2 import Picamera2

        self._picam = Picamera2(camera_num)
        # "RGB888" はメモリ上BGR順なのでOpenCVでそのまま扱える
        self._preview_config = self._picam.create_preview_configuration(
            main={"size": LIVE_CAPTURE_SIZE, "format": "RGB888"})
        self._still_config = self._picam.create_still_configuration(main={"format": "RGB888"})
        self._picam.configure(self._preview_config)
        self._picam.start()
        print(f"カメラ: Picamera2 (CSI, カメラ番号 {camera_num})")

    def read(self):
        return self._picam.capture_array()

    def capture_still(self):
        """最大解像度の静止画を撮影する（撮影後はプレビュー設定に戻る）。"""
        return self._picam.switch_mode_and_capture_array(self._still_config)

    def close(self):
        self._picam.stop()
        self._picam.close()


class UsbCamera:
    """USBカメラを OpenCV で使う。撮影時だけ高解像度に切り替える。"""

    def __init__(self, index):
        backend = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(index, backend)
        if not self._cap.isOpened():
            raise IOError(f"USBカメラ {index} を開けませんでした。")
        # 高解像度でもフレームレートを保てるよう、MJPEGで受け取る
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._set_size(LIVE_CAPTURE_SIZE)
        print(f"カメラ: USB (OpenCV, 番号 {index}), プレビュー {self._actual_size()}")

    def _set_size(self, size):
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])

    def _actual_size(self):
        return int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def read(self):
        ok, frame = self._cap.read()
        return frame if ok else None

    def capture_still(self):
        """USB_STILL_SIZE（カメラが対応する最も近い解像度）で静止画を撮影し、プレビュー解像度に戻す。"""
        self._set_size(USB_STILL_SIZE)
        for _ in range(USB_SETTLE_FRAMES):
            self._cap.read()
        frame = self.read()
        if frame is not None:
            print(f"撮影解像度: {frame.shape[1]}x{frame.shape[0]}")
        self._set_size(LIVE_CAPTURE_SIZE)
        return frame

    def close(self):
        self._cap.release()


def _find_csi_camera():
    """Picamera2 で使えるCSIカメラの番号を返す。無ければ None。"""
    try:
        from picamera2 import Picamera2
    except ImportError:
        return None
    for num, info in enumerate(Picamera2.global_camera_info()):
        # USBカメラも libcamera 経由で一覧に出るので除外する
        if "usb" not in info.get("Id", "").lower():
            return num
    return None


def _find_usb_camera_index():
    """LinuxでUSBカメラの /dev/videoN の番号を探す。見つからなければ LIVE_CAMERA_INDEX。

    ラズパイ5では /dev/video0 がUSBカメラとは限らない（ISPなどのデバイスもあるため）。
    """
    if LIVE_CAMERA_INDEX is not None:
        return LIVE_CAMERA_INDEX
    candidates = []
    for path in glob.glob("/sys/class/video4linux/video*"):
        if "/usb" in os.path.realpath(os.path.join(path, "device")):
            candidates.append(int(os.path.basename(path)[len("video"):]))
    # UVCカメラは映像用とメタデータ用の2つを作るので、番号の小さい方（映像用）を使う
    return min(candidates) if candidates else 0


def open_camera():
    """CAMERA_BACKEND ("auto" / "picamera2" / "opencv") に従ってカメラを開く。"""
    if CAMERA_BACKEND not in ("auto", "picamera2", "opencv"):
        raise ValueError(f"CAMERA_BACKEND の値が不正です: {CAMERA_BACKEND!r}")

    if CAMERA_BACKEND in ("auto", "picamera2"):
        csi = _find_csi_camera()
        if csi is not None:
            return PiCamera(csi)
        if CAMERA_BACKEND == "picamera2":
            raise IOError("Picamera2 で使えるカメラモジュールが見つかりませんでした。")

    return UsbCamera(_find_usb_camera_index())
