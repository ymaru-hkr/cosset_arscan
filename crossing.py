"""骨格線（スケルトン）を使って、重なり・交差したコセットを1本ずつに分離する。

1. 二値画像を細線化して骨格線を得る
2. 骨格線の分岐点を交差点とみなし、交差点で骨格線を枝に分割する
3. 各交差点で、向きがまっすぐ続く枝どうしをつなぎ直す
4. つないだ枝ごとに、元の幅で太らせてコセット1本分の領域を復元する

交差を含まない物体は、元の輪郭をそのまま使う。
"""
from collections import defaultdict
from dataclasses import dataclass

import cv2
import numpy as np

from config import (
    BRIDGE_MAX_FACTOR,
    DIRECTION_SAMPLE_FACTOR,
    JUNCTION_MERGE_FACTOR,
    MAX_HOLE_AREA_FACTOR,
    PAIR_MAX_ANGLE_DEG,
    SPUR_MAX_FACTOR,
    WIDE_OBJECT_FACTOR,
)

_NEIGHBOR_KERNEL = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], np.float32)
_KERNEL_3X3 = np.ones((3, 3), np.uint8)


@dataclass
class SeparationResult:
    contours: list               # 測定対象の輪郭（交差は分離済み。reconstruct=Falseなら空）
    crossings: list              # 交差点の座標 [(x, y), ...]
    crossing_mask: np.ndarray    # 交差を含む物体の領域 (255)
    wide_mask: np.ndarray        # 交差点は無いが幅が太すぎる物体の領域 (255)。横並びの重なりの疑い


def _ellipse(diameter):
    d = max(3, int(round(diameter)) | 1)
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))


def _neighbor_count(skel):
    return cv2.filter2D(skel, -1, _NEIGHBOR_KERNEL, borderType=cv2.BORDER_CONSTANT)


def _skeletonize(binary):
    return (cv2.ximgproc.thinning(binary, thinningType=cv2.ximgproc.THINNING_GUOHALL) > 0).astype(np.uint8)


def _fill_small_holes(binary, max_area):
    """半透明部分でできる小さな穴を埋める（穴があると骨格線が輪になり、偽の交差点になる）。"""
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    filled = binary.copy()
    if hierarchy is None:
        return filled
    for cnt, h in zip(contours, hierarchy[0]):
        if h[3] >= 0 and cv2.contourArea(cnt) <= max_area:
            cv2.drawContours(filled, [cnt], 0, 255, -1)
    return filled


def _prune_spurs(skel, max_len, iterations=3):
    """輪郭のギザギザから生える短いヒゲ（端点から分岐点までの短い枝）を除去する。"""
    skel = skel.copy()
    for _ in range(iterations):
        nb = _neighbor_count(skel)
        junctions = (skel == 1) & (nb >= 3)
        endpoints = (skel == 1) & (nb == 1)
        branches = skel.copy()
        branches[junctions] = 0
        n, labels, stats, _ = cv2.connectedComponentsWithStats(branches, connectivity=8)

        touches_junction = cv2.dilate(junctions.astype(np.uint8), _KERNEL_3X3) > 0
        remove = np.zeros(n, bool)
        remove[np.intersect1d(labels[endpoints], labels[touches_junction & (branches == 1)])] = True
        remove &= stats[:, cv2.CC_STAT_AREA] < max_len
        remove[0] = False
        if not remove.any():
            break
        skel[remove[labels]] = 0
        skel = _skeletonize(skel * 255)
    return skel


def _split_edges(skel, node_region):
    """骨格線を交差点領域で切り、枝ごとのピクセル座標 (x, y) の配列リストを返す。"""
    edges_img = skel.copy()
    edges_img[node_region > 0] = 0
    n_edges, edge_labels = cv2.connectedComponents(edges_img, connectivity=8)

    ys, xs = np.nonzero(edge_labels)
    labs = edge_labels[ys, xs]
    order = np.argsort(labs, kind="stable")
    pts = np.stack([xs[order], ys[order]], axis=1)
    starts = np.searchsorted(labs[order], np.arange(1, n_edges))
    return np.split(pts, starts[1:]) if n_edges > 1 else []


def _build_graph(skel, node_region):
    """交差点（ノード）と枝（エッジ）を求め、各ノードに接する枝の接続情報を返す。"""
    n_nodes, node_labels, _, centroids = cv2.connectedComponentsWithStats(node_region, connectivity=8)
    edges = _split_edges(skel, node_region)
    node_touch = cv2.dilate(node_labels.astype(np.uint16), _KERNEL_3X3)

    # node_id -> [(edge_id, 接続点, 交差点から離れる向きの単位ベクトル)]
    attachments = defaultdict(list)
    for e, pts in enumerate(edges):
        touched = node_touch[pts[:, 1], pts[:, 0]]
        for node in np.unique(touched[touched > 0]):
            attachments[int(node)].append((e, pts[touched == node].mean(axis=0)))
    return node_labels, centroids, edges, attachments


def _absorb_short_bridges(skel, node_region, max_len):
    """近接した2つの分岐点を結ぶ短い枝を交差点領域に取り込む。

    幅のある2本が交差すると、骨格線は1点ではなく短い橋でつながった2つのY字になるため。
    """
    node_labels, _, edges, attachments = _build_graph(skel, node_region)
    nodes_of_edge = defaultdict(set)
    for node, atts in attachments.items():
        for e, _ in atts:
            nodes_of_edge[e].add(node)

    bridges = np.zeros_like(node_region)
    for e, nodes in nodes_of_edge.items():
        if len(nodes) >= 2 and len(edges[e]) <= max_len:
            bridges[edges[e][:, 1], edges[e][:, 0]] = 1
    if not bridges.any():
        return node_region
    return node_region | cv2.dilate(bridges, _KERNEL_3X3)


def _edge_direction(pts, attach, sample_len):
    """接続点の近くの枝ピクセルから、交差点から離れる向きを求める。"""
    near = pts[np.linalg.norm(pts - attach, axis=1) <= sample_len]
    direction = near.mean(axis=0) - attach
    norm = np.linalg.norm(direction)
    return direction / norm if norm > 1e-6 else np.zeros(2)


def _reconstruct(binary, pts, lines, radius):
    """骨格線と接続線を半径radiusで太らせ、二値画像と重なる部分の輪郭リストを返す。"""
    all_pts = np.vstack([pts] + [np.array(line) for line in lines]) if lines else pts
    margin = radius + 2
    x0, y0 = np.maximum(np.floor(all_pts.min(axis=0)).astype(int) - margin, 0)
    x1, y1 = np.ceil(all_pts.max(axis=0)).astype(int) + margin + 1
    x1, y1 = min(x1, binary.shape[1]), min(y1, binary.shape[0])

    canvas = np.zeros((y1 - y0, x1 - x0), np.uint8)
    canvas[pts[:, 1] - y0, pts[:, 0] - x0] = 255
    for p, q in lines:
        cv2.line(canvas, (int(p[0]) - x0, int(p[1]) - y0), (int(q[0]) - x0, int(q[1]) - y0), 255, 1)
    canvas = cv2.dilate(canvas, _ellipse(2 * radius + 1))
    canvas &= binary[y0:y1, x0:x1]

    cnts, _ = cv2.findContours(canvas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE, offset=(x0, y0))
    return list(cnts)


def separate_strips(binary, reconstruct=True):
    """二値画像中の物体を、交差を分離したうえで輪郭のリストにする。

    reconstruct=False のときは交差点の検出だけを行う（ライブプレビュー用に軽量）。
    """
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, _KERNEL_3X3)
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    skel = _skeletonize(binary)
    empty = np.zeros_like(binary)
    if not skel.any():
        return SeparationResult([], [], empty, empty)

    # 典型的なコセットの幅を基準に各パラメータを決める（解像度に依存しないように）
    width = max(2.0, 2.0 * float(np.median(dist[skel > 0])))
    binary = _fill_small_holes(binary, MAX_HOLE_AREA_FACTOR * width ** 2)
    skel = _prune_spurs(_skeletonize(binary), SPUR_MAX_FACTOR * width)

    nb = _neighbor_count(skel)
    junctions = ((skel == 1) & (nb >= 3)).astype(np.uint8)
    node_region = cv2.dilate(junctions, _ellipse(JUNCTION_MERGE_FACTOR * width))
    node_region = _absorb_short_bridges(skel, node_region, BRIDGE_MAX_FACTOR * width)
    node_labels, centroids, edges, attachments = _build_graph(skel, node_region)

    # 3本以上の枝が集まる点を交差点とする（2本なら単なる曲がり・ノイズ）
    crossing_nodes = [node for node, atts in attachments.items() if len(atts) >= 3]
    crossings = [tuple(centroids[node]) for node in crossing_nodes]

    n_comps, comp_labels = cv2.connectedComponents(binary, connectivity=8)
    on_crossing = np.isin(node_labels, crossing_nodes) & (binary > 0)
    is_crossing_comp = np.zeros(n_comps, bool)
    is_crossing_comp[np.unique(comp_labels[on_crossing])] = True
    is_crossing_comp[0] = False

    # 交差点が無いのに太すぎる物体は、横並びに重なっている疑いがある
    comp_width = np.zeros(n_comps)
    sk_y, sk_x = np.nonzero(skel)
    sk_comp = comp_labels[sk_y, sk_x]
    for c in np.unique(sk_comp):
        comp_width[c] = 2.0 * np.median(dist[sk_y[sk_comp == c], sk_x[sk_comp == c]])
    is_wide_comp = (comp_width > WIDE_OBJECT_FACTOR * width) & ~is_crossing_comp
    is_wide_comp[0] = False

    crossing_mask = np.where(is_crossing_comp[comp_labels], 255, 0).astype(np.uint8)
    wide_mask = np.where(is_wide_comp[comp_labels], 255, 0).astype(np.uint8)
    if not reconstruct:
        return SeparationResult([], crossings, crossing_mask, wide_mask)

    # --- 交差点で向きが続く枝どうしをつなぐ ---
    parent = list(range(len(edges)))

    def find(e):
        while parent[e] != e:
            parent[e] = parent[parent[e]]
            e = parent[e]
        return e

    lines = defaultdict(list)  # edge_id -> 交差点をまたぐ接続線 [(p, q)]
    cos_limit = np.cos(np.radians(PAIR_MAX_ANGLE_DEG))
    sample_len = DIRECTION_SAMPLE_FACTOR * width
    for node, atts in attachments.items():
        dirs = [_edge_direction(edges[e], attach, sample_len) for e, attach in atts]
        candidates = sorted(
            ((-float(np.dot(dirs[i], dirs[j])), i, j)
             for i in range(len(atts)) for j in range(i + 1, len(atts))),
            reverse=True,
        )
        used = set()
        for cos, i, j in candidates:
            if cos < cos_limit:
                break
            if i in used or j in used:
                continue
            used |= {i, j}
            parent[find(atts[i][0])] = find(atts[j][0])
            lines[atts[i][0]].append((atts[i][1], atts[j][1]))
        # 相手が見つからない枝（T字の縦棒など）は交差点の中心まで伸ばす
        if len(atts) >= 2:
            for i, (e, attach) in enumerate(atts):
                if i not in used:
                    lines[e].append((attach, centroids[node]))

    groups = defaultdict(list)
    for e, pts in enumerate(edges):
        if is_crossing_comp[comp_labels[pts[0, 1], pts[0, 0]]]:
            groups[find(e)].append(e)

    contours = []
    for members in groups.values():
        pts = np.vstack([edges[e] for e in members])
        group_lines = [line for e in members for line in lines[e]]
        radius = max(1, int(round(np.median(dist[pts[:, 1], pts[:, 0]]))))
        contours.extend(_reconstruct(binary, pts, group_lines, radius))

    # 交差を含まない物体は元の輪郭をそのまま使う
    simple = np.where(is_crossing_comp[comp_labels] | (comp_labels == 0), 0, 255).astype(np.uint8)
    simple_cnts, _ = cv2.findContours(simple, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours.extend(simple_cnts)

    return SeparationResult(contours, crossings, crossing_mask, wide_mask)
