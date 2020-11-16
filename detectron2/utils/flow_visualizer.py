# -*- encoding: utf-8 -*-
"""
@File          :   visualizer.py
@Time          :   2020/06/27 6:08:58
@Author        :   Chen-Jianhu (jhchen.mail@gmail.com)
@Last Modified :   2020/07/01 10:29:22
@License       :   Copyright(C), USTC
@Desc          :   None
"""

import numpy as np
import cv2
import detectron2.data.detection_utils as utils
from detectron2.data.flow_utils import read_flow


def make_color_wheel():
    """
    Generate color wheel according Middlebury color code
    :return: Color wheel
    """
    RY = 15
    YG = 6
    GC = 4
    CB = 11
    BM = 13
    MR = 6

    ncols = RY + YG + GC + CB + BM + MR

    colorwheel = np.zeros([ncols, 3])

    col = 0

    # RY
    colorwheel[0:RY, 0] = 255
    colorwheel[0:RY, 1] = np.transpose(np.floor(255 * np.arange(0, RY) / RY))
    col += RY

    # YG
    colorwheel[col:col + YG, 0] = 255 - np.transpose(np.floor(255 * np.arange(0, YG) / YG))
    colorwheel[col:col + YG, 1] = 255
    col += YG

    # GC
    colorwheel[col:col + GC, 1] = 255
    colorwheel[col:col + GC, 2] = np.transpose(np.floor(255 * np.arange(0, GC) / GC))
    col += GC

    # CB
    colorwheel[col:col + CB, 1] = 255 - np.transpose(np.floor(255 * np.arange(0, CB) / CB))
    colorwheel[col:col + CB, 2] = 255
    col += CB

    # BM
    colorwheel[col:col + BM, 2] = 255
    colorwheel[col:col + BM, 0] = np.transpose(np.floor(255 * np.arange(0, BM) / BM))
    col += + BM

    # MR
    colorwheel[col:col + MR, 2] = 255 - np.transpose(np.floor(255 * np.arange(0, MR) / MR))
    colorwheel[col:col + MR, 0] = 255

    return colorwheel


def compute_color(u, v):
    """
    compute optical flow color map
    :param u: horizontal optical flow
    :param v: vertical optical flow
    :return:
    """

    height, width = u.shape
    img = np.zeros((height, width, 3))

    NAN_idx = np.isnan(u) | np.isnan(v)
    u[NAN_idx] = v[NAN_idx] = 0

    colorwheel = make_color_wheel()
    ncols = np.size(colorwheel, 0)

    rad = np.sqrt(u ** 2 + v ** 2)

    a = np.arctan2(-v, -u) / np.pi

    fk = (a + 1) / 2 * (ncols - 1) + 1

    k0 = np.floor(fk).astype(int)

    k1 = k0 + 1
    k1[k1 == ncols + 1] = 1
    f = fk - k0

    for i in range(0, np.size(colorwheel, 1)):
        tmp = colorwheel[:, i]
        col0 = tmp[k0 - 1] / 255
        col1 = tmp[k1 - 1] / 255
        col = (1 - f) * col0 + f * col1

        idx = rad <= 1
        col[idx] = 1 - rad[idx] * (1 - col[idx])
        notidx = np.logical_not(idx)

        col[notidx] *= 0.75
        img[:, :, i] = np.uint8(np.floor(255 * col * (1 - NAN_idx)))

    return img


def flow2img(flow_data):
    """
    convert optical flow into color image
    :param flow_data:
    :return: color image
    """
    # print(flow_data.shape)
    # print(type(flow_data))
    u = flow_data[:, :, 0]
    v = flow_data[:, :, 1]

    UNKNOW_FLOW_THRESHOLD = 1e7
    pr1 = abs(u) > UNKNOW_FLOW_THRESHOLD
    pr2 = abs(v) > UNKNOW_FLOW_THRESHOLD
    idx_unknown = (pr1 | pr2)
    u[idx_unknown] = v[idx_unknown] = 0

    # get max value in each direction
    maxu = -999.
    maxv = -999.
    minu = 999.
    minv = 999.
    maxu = max(maxu, np.max(u))
    maxv = max(maxv, np.max(v))
    minu = min(minu, np.min(u))
    minv = min(minv, np.min(v))

    rad = np.sqrt(u ** 2 + v ** 2)
    maxrad = max(-1, np.max(rad))
    u = u / maxrad + np.finfo(float).eps
    v = v / maxrad + np.finfo(float).eps

    img = compute_color(u, v)

    idx = np.repeat(idx_unknown[:, :, np.newaxis], 3, axis=2)
    img[idx] = 0

    return np.uint8(img)


def visualize_sample_from_array(image1, image2, flow_map, img_format="BGR", save=False):
    img_format = img_format.upper()
    assert img_format in ["RGB", "BGR"], "Only support 'RGB' and 'BGR' image format."
    assert image1.shape[:2] == image2.shape[:2] == flow_map.shape[:2], (
        "Different shape between image and flow: img1({}), img2({}), flow({})".format(
            image1.shape[:2], image2.shape[:2], flow_map.shape[:2]
        )
    )

    flow_map = flow2img(flow_map)
    if img_format == "RGB":
        image1 = image1[:, :, ::-1]
        image2 = image2[:, :, ::-1]
        flow_map = flow_map[:, :, ::-1]

    img = np.concatenate([image1, image2, flow_map], axis=0)

    if save:
        cv2.imwrite("visualize_sample_from_array.jpg", img)
    else:
        cv2.imshow("visualize_sample_from_array", img)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


def visualize_sample_from_file(image_file1=None, image_file2=None, flow_map_file=None, save=False):
    print("sample infos:")
    print("  image file 1: {}".format(image_file1))
    print("  image file 2: {}".format(image_file2))
    print("  flow map file: {}".format(flow_map_file))

    image1 = utils.read_image(image_file1, format="BGR")
    image2 = utils.read_image(image_file2, format="BGR")
    flow_map = flow2img(read_flow(flow_map_file))

    img = np.concatenate([image1, image2, flow_map], axis=0)

    if save:
        cv2.imwrite("visualize_sample_from_file.jpg", img)
    else:
        cv2.imshow("visualize_sample_from_file", img)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
