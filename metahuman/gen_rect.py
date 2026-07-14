"""Generate the person crop-rectangle PIFuHD needs, using the lightweight pose
estimator. Ported from PIFuHD's official demo/Colab `get_rect`, with the
deprecated `np.int` casts replaced by plain `int` so it works regardless of the
installed NumPy version.

Run as: python gen_rect.py /path/to/image.png
Writes /path/to/image_rect.txt next to the image.
"""
import sys

import cv2
import numpy as np
import torch

from models.with_mobilenet import PoseEstimationWithMobileNet
from modules.keypoints import extract_keypoints, group_keypoints
from modules.load_state import load_state
from modules.pose import Pose
from demo import infer_fast

CKPT = "/app/checkpoints/checkpoint_iter_370000.pth"


def get_rect(net, images, height_size):
    net = net.eval()
    stride = 8
    upsample_ratio = 4
    num_keypoints = Pose.num_kpts
    cpu = not torch.cuda.is_available()

    for image in images:
        rect_path = image.replace(".%s" % image.split(".")[-1], "_rect.txt")
        img = cv2.imread(image, cv2.IMREAD_COLOR)

        heatmaps, pafs, scale, pad = infer_fast(
            net, img, height_size, stride, upsample_ratio, cpu
        )

        total_keypoints_num = 0
        all_keypoints_by_type = []
        for kpt_idx in range(num_keypoints):
            total_keypoints_num += extract_keypoints(
                heatmaps[:, :, kpt_idx], all_keypoints_by_type, total_keypoints_num
            )

        pose_entries, all_keypoints = group_keypoints(all_keypoints_by_type, pafs)
        for kpt_id in range(all_keypoints.shape[0]):
            all_keypoints[kpt_id, 0] = (
                all_keypoints[kpt_id, 0] * stride / upsample_ratio - pad[1]
            ) / scale
            all_keypoints[kpt_id, 1] = (
                all_keypoints[kpt_id, 1] * stride / upsample_ratio - pad[0]
            ) / scale

        rects = []
        for n in range(len(pose_entries)):
            if len(pose_entries[n]) == 0:
                continue
            pose_keypoints = np.ones((num_keypoints, 2), dtype=np.int32) * -1
            valid_keypoints = []
            for kpt_id in range(num_keypoints):
                if pose_entries[n][kpt_id] != -1.0:
                    pose_keypoints[kpt_id, 0] = int(
                        all_keypoints[int(pose_entries[n][kpt_id]), 0]
                    )
                    pose_keypoints[kpt_id, 1] = int(
                        all_keypoints[int(pose_entries[n][kpt_id]), 1]
                    )
                    valid_keypoints.append(
                        [pose_keypoints[kpt_id, 0], pose_keypoints[kpt_id, 1]]
                    )
            valid_keypoints = np.array(valid_keypoints)

            if pose_entries[n][10] != -1.0 or pose_entries[n][13] != -1.0:
                # ankles present -> full body is visible
                pmin = valid_keypoints.min(0)
                pmax = valid_keypoints.max(0)
                center = (0.5 * (pmax[:2] + pmin[:2])).astype(int)
                radius = int(0.65 * max(pmax[0] - pmin[0], pmax[1] - pmin[1]))
            elif pose_entries[n][8] != -1.0 and pose_entries[n][11] != -1.0:
                # legs missing -> crop from the pelvis
                center = (0.5 * (pose_keypoints[8] + pose_keypoints[11])).astype(int)
                radius = int(
                    1.45
                    * np.sqrt(((center[None, :] - valid_keypoints) ** 2).sum(1)).max(0)
                )
                center[1] += int(0.05 * radius)
            else:
                center = np.array([img.shape[1] // 2, img.shape[0] // 2])
                radius = max(img.shape[1] // 2, img.shape[0] // 2)

            x1 = center[0] - radius
            y1 = center[1] - radius
            rects.append([x1, y1, 2 * radius, 2 * radius])

        # Fallback: no person detected -> reconstruct the whole frame so the job
        # still returns a mesh instead of crashing on an empty rect file.
        if len(rects) == 0:
            h, w = img.shape[:2]
            side = max(h, w)
            rects.append([w // 2 - side // 2, h // 2 - side // 2, side, side])

        np.savetxt(rect_path, np.array(rects), fmt="%d")


if __name__ == "__main__":
    image_path = sys.argv[1]
    net = PoseEstimationWithMobileNet()
    checkpoint = torch.load(CKPT, map_location="cpu")
    load_state(net, checkpoint)
    if torch.cuda.is_available():
        net = net.cuda()
    get_rect(net, [image_path], 512)
