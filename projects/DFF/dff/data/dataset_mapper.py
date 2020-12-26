# -*- encoding: utf-8 -*-
"""
@File         : /detectron2/projects/DFF/dff/data/dataset_mapper.py
@Time         : 2020-11-28 16:27:23
@Author       : Facebook, Inc. and its affiliates.
@Last Modified: 2020-12-03 22:47:15
@Modified By  : Chen-Jianhu (jhchen.mail@gmail.com)
@License      : Copyright(C), USTC
@Desc         : None
"""

import logging
import os
import copy
import numpy as np
import torch
import random

from typing import List, Union
from PIL import Image

from detectron2.config import configurable
from detectron2.data import detection_utils as utils
from detectron2.data import transforms as T
from detectron2.data import MetadataCatalog
from detectron2.utils.file_io import PathManager
from detectron2.data.detection_utils import convert_PIL_to_numpy


"""
This file contains the default mapping that's applied to "dataset dicts".
"""

__all__ = ["DFFDatasetMapper"]

logger = logging.getLogger(__name__)


def read_image(file_name, format=None):
    """
    Read an image into the given format.
    Will apply rotation and flipping if the image has such exif information.

    Args:
        file_name (str): image file path
        format (str): one of the supported image modes in PIL, or "BGR" or "YUV-BT.601".

    Returns:
        image (np.ndarray): an HWC image in the given format, which is 0-255, uint8 for
            supported image modes in PIL or "BGR"; float (0-1 for Y) for YUV-BT.601.
    """
    with PathManager.open(file_name, "rb") as f:
        image = Image.open(f)

        # # capture and ignore this bug: https://github.com/python-pillow/Pillow/issues/3973
        # try:
        #     image = ImageOps.exif_transpose(image)
        # except Exception:
        #     pass

        return convert_PIL_to_numpy(image, format)


class DFFDatasetMapper:

    @configurable
    def __init__(
        self,
        is_train: bool,
        *,
        augmentations: List[Union[T.Augmentation, T.Transform]],
        image_format: str,
        frame_offset_min: int,
        frame_offset_max: int,
        key_frame_duration: int,
        vid_image_root: str
    ):
        """
        NOTE: this interface is experimental.
              this dataset mapper only support ILSVRC2015 VID dataset.
        """
        self.is_train = is_train
        self.augmentations = T.AugmentationList(augmentations)
        self.image_format = image_format
        self.frame_offset_min = frame_offset_min
        self.frame_offset_max = frame_offset_max
        self.key_frame_duration = key_frame_duration
        self.vid_image_root = vid_image_root

        # For testing
        self.key_frame_img = None
        self.key_frame_seg_id = None

        logger = logging.getLogger(__name__)
        mode = "training" if is_train else "inference"
        logger.info(f"[DatasetMapper] Augmentations used in {mode}: {augmentations}")

    @classmethod
    def from_config(cls, cfg, is_train: bool = True):
        augs = utils.build_augmentation(cfg, is_train)
        if cfg.INPUT.CROP.ENABLED and is_train:
            augs.insert(0, T.RandomCrop(cfg.INPUT.CROP.TYPE, cfg.INPUT.CROP.SIZE))

        vid_image_root = None
        # Same over all ILSVRC VID dataset
        for set_name in cfg.DATASETS.TRAIN:
            if "vid" in set_name:
                vid_image_root = MetadataCatalog.get(set_name).img_dir

        assert vid_image_root is not None, cfg.DATASETS.TRAIN

        ret = {
            "is_train": is_train,
            "augmentations": augs,
            "image_format": cfg.INPUT.FORMAT,
            "frame_offset_min": cfg.MODEL.DFF.FRAME_OFFSET_RANGE[0],
            "frame_offset_max": cfg.MODEL.DFF.FRAME_OFFSET_RANGE[1],
            "key_frame_duration": cfg.MODEL.DFF.KEY_FRAME_DURATION,
            "vid_image_root": vid_image_root,
        }

        return ret

    def __call__(self, dataset_dict):
        """
        Args:
            dataset_dict (dict): Metadata of one image, in Detectron2 Dataset format.

        Returns:
            dict: a format that builtin models in detectron2 accept
        """
        dataset_dict = copy.deepcopy(dataset_dict)  # it will be modified by code below

        image_cur = read_image(dataset_dict["file_name"], format=self.image_format)
        utils.check_image_size(dataset_dict, image_cur)

        # =============== Train ===============
        if self.is_train:
            pattern = dataset_dict.pop("pattern", None)
            if pattern is None:
                # DET set
                image_ref = image_cur.copy()
            else:
                # VID set
                offset = random.randint(self.frame_offset_min, self.frame_offset_max + 1)
                ref_id = min(
                    max(dataset_dict["frame_seg_id"] + offset, 0),
                    dataset_dict["frame_seg_len"] - 1
                )
                ref_file_name = os.path.join(self.vid_image_root, pattern.format(ref_id))
                image_ref = read_image(ref_file_name, format=self.image_format)

        # =============== Test ===============
        else:
            dataset_dict.pop("annotations", None)

            frame_seg_id = dataset_dict["frame_seg_id"]
            if frame_seg_id % self.key_frame_duration == 0:
                image_ref = image_cur.copy()
                self.key_frame_img = image_cur.copy()
                self.key_frame_seg_id = frame_seg_id
            else:
                assert self.key_frame_img is not None
                assert 0 < frame_seg_id - self.key_frame_seg_id < self.key_frame_duration, (
                    "frame_seg_id is {}, key_frame_seg_id is {}.".format(
                        frame_seg_id, self.key_frame_seg_id
                    )
                )
                image_ref = self.key_frame_img

            if (frame_seg_id + 1) == dataset_dict["frame_seg_len"]:
                self.key_frame_img = None
                self.key_frame_seg_id = None

        utils.check_image_size(dataset_dict, image_ref)

        # do data augmentations
        aug_input = T.AugInput(image_cur)
        transforms = self.augmentations(aug_input)
        image_cur = aug_input.image
        image_ref = transforms.apply_image(image_ref)

        # Pytorch's dataloader is efficient on torch.Tensor due to shared-memory,
        # but not efficient on large generic data structures due to the use of pickle & mp.Queue.
        # Therefore it's important to use torch.Tensor.
        dataset_dict["image_cur"] = torch.as_tensor(
            np.ascontiguousarray(image_cur.transpose(2, 0, 1)))
        dataset_dict["image_ref"] = torch.as_tensor(
            np.ascontiguousarray(image_ref.transpose(2, 0, 1)))

        if "annotations" in dataset_dict:
            image_shape = image_cur.shape[:2]  # h, w
            # USER: Implement additional transformations if you have other types of data
            annos = [
                utils.transform_instance_annotations(obj, transforms, image_shape)
                for obj in dataset_dict.pop("annotations")
                if obj.get("iscrowd", 0) == 0
            ]
            instances = utils.annotations_to_instances(annos, image_shape)

            dataset_dict["instances"] = utils.filter_empty_instances(instances)

        return dataset_dict
