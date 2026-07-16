from typing import *
from transformers import AutoModelForImageSegmentation
import torch
from torchvision import transforms
from PIL import Image


class BiRefNet:
    def __init__(self, model_name: str = "ZhengPeng7/BiRefNet"):
        self.model = AutoModelForImageSegmentation.from_pretrained(
            model_name, trust_remote_code=True
        )
        self.model.eval()
        self.transform_image = transforms.Compose(
            [
                transforms.Resize((1024, 1024)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
    
    def to(self, device: str):
        self.model.to(device)

    def cuda(self):
        self.model.cuda()

    def cpu(self):
        self.model.cpu()
        
    def __call__(self, image: Image.Image) -> Image.Image:
        image_size = image.size
        # WORKER CHANGE: match the model's parameter dtype. briaai/RMBG-2.0
        # ships fp32 so upstream never casts, but ZhengPeng7/BiRefNet (the
        # non-gated substitute) ships fp16 — feeding it fp32 crashes with
        # "Input type (float) and bias type (c10::Half)" (live-confirmed).
        model_dtype = next(self.model.parameters()).dtype
        input_images = self.transform_image(image).unsqueeze(0).to("cuda", dtype=model_dtype)
        # Prediction
        with torch.no_grad():
            preds = self.model(input_images)[-1].sigmoid().float().cpu()
        pred = preds[0].squeeze()
        pred_pil = transforms.ToPILImage()(pred)
        mask = pred_pil.resize(image_size)
        image.putalpha(mask)
        return image
    