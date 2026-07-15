"""Alam 3D multi-view upgrade for Trellis2ImageTo3DPipeline.

Adds run_multi_image(): true multi-photo conditioning. get_cond() natively
encodes a LIST of images to DINO tokens [N, T, D]; the flow DiTs cross-attend
to a token sequence, so concatenating all views into [1, N*T, D] conditions
every denoising step on every photo at once — front, sides and rear all
constrain the shape instead of one view + hallucination.

Mirrors upstream run() (MIT) stage-for-stage; only the conditioning differs.
"""
import torch


def _multi_cond(pipeline, images, resolution):
    cond = pipeline.get_cond(images, resolution, include_neg_cond=False)['cond']
    if isinstance(cond, torch.Tensor) and cond.dim() == 3 and cond.shape[0] > 1:
        cond = cond.reshape(1, -1, cond.shape[-1])          # [1, N*T, D]
    return {'cond': cond, 'neg_cond': torch.zeros_like(cond)}


@torch.no_grad()
def run_multi_image(pipeline, images, seed=42,
                    sparse_structure_sampler_params={}, shape_slat_sampler_params={},
                    tex_slat_sampler_params={}, preprocess_image=True,
                    pipeline_type=None, max_num_tokens=49152, num_samples=1):
    pipeline_type = pipeline_type or pipeline.default_pipeline_type
    if preprocess_image:
        images = [pipeline.preprocess_image(im) for im in images]
    torch.manual_seed(seed)
    cond_512 = _multi_cond(pipeline, images, 512)
    cond_1024 = _multi_cond(pipeline, images, 1024) if pipeline_type != '512' else None
    ss_res = {'512': 32, '1024': 64, '1024_cascade': 32, '1536_cascade': 32}[pipeline_type]
    coords = pipeline.sample_sparse_structure(cond_512, ss_res, num_samples,
                                              sparse_structure_sampler_params)
    if pipeline_type == '512':
        shape_slat = pipeline.sample_shape_slat(
            cond_512, pipeline.models['shape_slat_flow_model_512'], coords,
            shape_slat_sampler_params)
        tex_slat = pipeline.sample_tex_slat(
            cond_512, pipeline.models['tex_slat_flow_model_512'], shape_slat,
            tex_slat_sampler_params)
        res = 512
    elif pipeline_type == '1024':
        shape_slat = pipeline.sample_shape_slat(
            cond_1024, pipeline.models['shape_slat_flow_model_1024'], coords,
            shape_slat_sampler_params)
        tex_slat = pipeline.sample_tex_slat(
            cond_1024, pipeline.models['tex_slat_flow_model_1024'], shape_slat,
            tex_slat_sampler_params)
        res = 1024
    else:
        hi = 1024 if pipeline_type == '1024_cascade' else 1536
        shape_slat, res = pipeline.sample_shape_slat_cascade(
            cond_512, cond_1024,
            pipeline.models['shape_slat_flow_model_512'],
            pipeline.models['shape_slat_flow_model_1024'],
            512, hi, coords, shape_slat_sampler_params, max_num_tokens)
        tex_slat = pipeline.sample_tex_slat(
            cond_1024, pipeline.models['tex_slat_flow_model_1024'], shape_slat,
            tex_slat_sampler_params)
    torch.cuda.empty_cache()
    return pipeline.decode_latent(shape_slat, tex_slat, res)
