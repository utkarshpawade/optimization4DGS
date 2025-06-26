



#Original file is located at
    #https://colab.research.google.com/drive/17vIV6rFnVnvpkoznZbTiROEDWknIAUYl


# Commented out IPython magic to ensure Python compatibility.
# %cd /content
!git clone https://github.com/utkarshpawade/4DGaussians.git

# Commented out IPython magic to ensure Python compatibility.
# %cd 4DGaussians
!git submodule update --init --recursive

!pip install mmcv==1.6.0
!pip install matplotlib
!pip install argparse

!pip install lpips
!pip install plyfile
!pip install pytorch_msssim
!pip install open3d
!pip install imageio[ffmpeg]
!sudo apt-get install libglm-dev
!pip3 install torch torchvision torchaudio

!pip install -e /content/4DGaussians/submodules/depth-diff-gaussian-rasterization

#include<cfloat> to simple knn cu

!pip install -e /content/4DGaussians/submodules/simple-knn

# Commented out IPython magic to ensure Python compatibility.
!mkdir /content/test
# %cd /content/test
!wget https://huggingface.co/camenduru/4DGaussians/resolve/main/data/data.zip
!unzip data.zip

# Commented out IPython magic to ensure Python compatibility.
# %cd /content/4DGaussians
!python train.py -s /content/test/data/bouncingballs --port 6017 --expname "dnerf/bouncingballs" --configs arguments/dnerf/bouncingballs.py

import imageio
import numpy as np
import torch
from scene import Scene
import os
import cv2
from tqdm import tqdm
from gaussian_renderer import render
import torchvision
from utils.general_utils import safe_state
from argparse import ArgumentParser
from arguments import ModelParams, PipelineParams, ModelHiddenParams, get_combined_args
from gaussian_renderer import GaussianModel
from time import time
import concurrent.futures
import mmcv
from utils.params_utils import merge_hparams
import copy

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
to8b = lambda x : (255*np.clip(x.cpu().numpy(),0,1)).astype(np.uint8)

try:
    from torch.utils.tensorboard import SummaryWriter
    TENSORBOARD_FOUND = True
except ImportError:
    TENSORBOARD_FOUND = False

def multithread_write(image_list, path):
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=None)
    def write_image(image, count, path):
        try:
            torchvision.utils.save_image(image, os.path.join(path, '{0:05d}'.format(count) + ".png"))
            return count, True
        except:
            return count, False

    tasks = []
    for index, image in enumerate(image_list):
        tasks.append(executor.submit(write_image, image, index, path))
    executor.shutdown()
    for index, status in enumerate(tasks):
        if status == False:
            write_image(image_list[index], index, path)

to8b = lambda x: (255 * np.clip(x.cpu().numpy(), 0, 1)).astype(np.uint8)

def render_set(model_path, name, iteration, views, gaussians, pipeline, background, cam_type):
    render_path = os.path.join(model_path, name, "ours_{}".format(iteration), "renders")
    gts_path = os.path.join(model_path, name, "ours_{}".format(iteration), "gt")

    os.makedirs(render_path, exist_ok=True)
    os.makedirs(gts_path, exist_ok=True)
    render_images = []
    gt_list = []
    render_list = []
    print("point nums:", gaussians._xyz.shape[0])
    for idx, view in enumerate(tqdm(views, desc="Rendering progress")):
        if idx == 0:
            time1 = time()

        rendering = render(view, gaussians, pipeline, background, cam_type=cam_type)["render"]
        render_images.append(to8b(rendering).transpose(1, 2, 0))
        render_list.append(rendering)
        if name in ["train", "test"]:
            if cam_type != "PanopticSports":
                gt = view.original_image[0:3, :, :]
            else:
                gt = view['image'].cuda()
            gt_list.append(gt)

    time2 = time()

    multithread_write(gt_list, gts_path)
    multithread_write(render_list, render_path)

    imageio.mimwrite(os.path.join(model_path, name, "ours_{}".format(iteration), 'video_rgb.mp4'), render_images, fps=30)

def render_sets(dataset, hyperparam, iteration, pipeline, skip_train, skip_test, skip_video):
    with torch.no_grad():
        gaussians = GaussianModel(dataset.sh_degree, hyperparam)
        scene = Scene(dataset, gaussians, load_iteration=iteration, shuffle=False)
        cam_type = scene.dataset_type
        bg_color = [1, 1, 1] if dataset.white_background else [0, 0, 0]
        background = torch.tensor(bg_color, dtype=torch.float32, device="cuda")

        if not skip_train:
            render_set(dataset.model_path, "train", scene.loaded_iter, scene.getTrainCameras(), gaussians, pipeline, background, cam_type)

        if not skip_test:
            render_set(dataset.model_path, "test", scene.loaded_iter, scene.getTestCameras(), gaussians, pipeline, background, cam_type)

        if not skip_video:
            render_set(dataset.model_path, "video", scene.loaded_iter, scene.getVideoCameras(), gaussians, pipeline, background, cam_type)

parser = ArgumentParser(description="Testing script parameters")
model = ModelParams(parser, sentinel=True)
pipeline = PipelineParams(parser)
hyperparam = ModelHiddenParams(parser)
parser.add_argument("--iteration", type=int, default=-1)
parser.add_argument("--skip_train", action="store_true")
parser.add_argument("--skip_test", action="store_true")
parser.add_argument("--skip_video", action="store_true")
parser.add_argument("--quiet", action="store_true")
parser.add_argument("--configs", type=str, default="/content/4DGaussians/arguments/dnerf/bouncingballs.py")
parser.add_argument("--expname", type=str, default="dnerf/bouncingballs")
args, _ = parser.parse_known_args()
setattr(args, 'source_path', "/content/test/data/bouncingballs")
setattr(args, 'model_path', "/content/4DGaussians/output/dnerf/bouncingballs")
setattr(args, 'extension', ".png")
setattr(args, 'sh_degree', 3)
setattr(args, 'expname', "dnerf/bouncingballs")

if args.configs and os.path.exists(args.configs):
    config = mmcv.Config.fromfile(args.configs)
    args = merge_hparams(args, config)
    print("Config loaded. sh_degree:", getattr(args, 'sh_degree', 'Not set'))
else:
    print("Warning: Configuration file not found or invalid. Using fallback defaults.")
    setattr(args, 'sh_degree', 3)
    setattr(args, 'images', "images")
    setattr(args, 'resolution', -1)
    setattr(args, 'white_background', False)
    setattr(args, 'data_device', "cuda")
    setattr(args, 'eval', False)
    setattr(args, 'render_process', False)
    setattr(args, 'add_points', False)
    setattr(args, 'extension', ".png")
    setattr(args, 'llffhold', 8)
    setattr(args, 'convert_SHs_python', False)
    setattr(args, 'compute_cov3D_python', False)
    setattr(args, 'debug', False)
    setattr(args, 'timebase_pe', 4)
    setattr(args, 'posebase_pe', 10)
    setattr(args, 'defor_depth', 2)
    setattr(args, 'net_width', 64)
    setattr(args, 'scale_rotation_pe', 2)
    setattr(args, 'opacity_pe', 2)
    setattr(args, 'timenet_width', 64)
    setattr(args, 'timenet_output', 32)
    setattr(args, 'bounds', 1.0)
    setattr(args, 'plane_tv_weight', 0.0001)
    setattr(args, 'time_smoothness_weight', 0.001)
    setattr(args, 'l1_time_planes', 0.0001)
    setattr(args, 'kplanes_config', "")
    setattr(args, 'multires', 8)
    setattr(args, 'no_dx', False)
    setattr(args, 'no_grid', False)
    setattr(args, 'no_ds', False)
    setattr(args, 'no_dr', False)
    setattr(args, 'no_do', False)
    setattr(args, 'no_dshs', False)
    setattr(args, 'empty_voxel', False)
    setattr(args, 'grid_pe', 2)
    setattr(args, 'static_mlp', False)
    setattr(args, 'apply_rotation', False)

safe_state(args.quiet)
print("Rendering ", args.model_path)
print(f"Dataset path: {args.source_path}")
print(f"sh_degree: {getattr(args, 'sh_degree', 'Not set')}")
print(f"extension: {getattr(args, 'extension', 'Not set')}")
print(f"expname: {getattr(args, 'expname', 'Not set')}")
transforms_file = os.path.join(args.source_path, "transforms.json")
if os.path.exists(transforms_file):
    with open(transforms_file, 'r') as f:
        import json
        transforms = json.load(f)
        print("Transforms.json frames:", [frame.get("file_path") for frame in transforms.get("frames", [])])
else:
    print(f"Error: transforms.json not found at {transforms_file}")
render_sets(model.extract(args), hyperparam.extract(args), args.iteration, pipeline.extract(args), args.skip_train, args.skip_test, args.skip_video)

from IPython.display import HTML
from base64 import b64encode
def display_video(video_path):
  mp4 = open(video_path,'rb').read()
  data_url = "data:video/mp4;base64," + b64encode(mp4).decode()
  return HTML("""
  <video width=1000 controls>
    <source src="%s" type="video/mp4">
  </video>
  """ % data_url)

save_dir = '/content/4DGaussians/output/dnerf/bouncingballs/video/ours_20000/video_rgb.mp4'

import os
import glob
display_video(save_dir)

# Commented out IPython magic to ensure Python compatibility.
# %cd /content/4DGaussians
!python train.py -s /content/test/data/mutant --port 6017 --expname "dnerf/mutant" --configs arguments/dnerf/mutant.py

import imageio
import numpy as np
import torch
from scene import Scene
import os
import cv2
from tqdm import tqdm
from gaussian_renderer import render
import torchvision
from utils.general_utils import safe_state
from argparse import ArgumentParser
from arguments import ModelParams, PipelineParams, ModelHiddenParams, get_combined_args
from gaussian_renderer import GaussianModel
from time import time
import concurrent.futures
import mmcv
from utils.params_utils import merge_hparams

def multithread_write(image_list, path):
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=None)
    def write_image(image, count, path):
        try:
            torchvision.utils.save_image(image, os.path.join(path, '{0:05d}'.format(count) + ".png"))
            return count, True
        except:
            return count, False

    tasks = []
    for index, image in enumerate(image_list):
        tasks.append(executor.submit(write_image, image, index, path))
    executor.shutdown()
    for index, status in enumerate(tasks):
        if status == False:
            write_image(image_list[index], index, path)

to8b = lambda x: (255 * np.clip(x.cpu().numpy(), 0, 1)).astype(np.uint8)

def render_set(model_path, name, iteration, views, gaussians, pipeline, background, cam_type):
    render_path = os.path.join(model_path, name, "ours_{}".format(iteration), "renders")
    gts_path = os.path.join(model_path, name, "ours_{}".format(iteration), "gt")

    os.makedirs(render_path, exist_ok=True)
    os.makedirs(gts_path, exist_ok=True)
    render_images = []
    gt_list = []
    render_list = []
    print("point nums:", gaussians._xyz.shape[0])
    for idx, view in enumerate(tqdm(views, desc="Rendering progress")):
        if idx == 0:
            time1 = time()

        rendering = render(view, gaussians, pipeline, background, cam_type=cam_type)["render"]
        render_images.append(to8b(rendering).transpose(1, 2, 0))
        render_list.append(rendering)
        if name in ["train", "test"]:
            if cam_type != "PanopticSports":
                gt = view.original_image[0:3, :, :]
            else:
                gt = view['image'].cuda()
            gt_list.append(gt)

    time2 = time()

    multithread_write(gt_list, gts_path)
    multithread_write(render_list, render_path)

    imageio.mimwrite(os.path.join(model_path, name, "ours_{}".format(iteration), 'video_rgb.mp4'), render_images, fps=30)

def render_sets(dataset, hyperparam, iteration, pipeline, skip_train, skip_test, skip_video):
    with torch.no_grad():
        gaussians = GaussianModel(dataset.sh_degree, hyperparam)
        scene = Scene(dataset, gaussians, load_iteration=iteration, shuffle=False)
        cam_type = scene.dataset_type
        bg_color = [1, 1, 1] if dataset.white_background else [0, 0, 0]
        background = torch.tensor(bg_color, dtype=torch.float32, device="cuda")

        if not skip_train:
            render_set(dataset.model_path, "train", scene.loaded_iter, scene.getTrainCameras(), gaussians, pipeline, background, cam_type)

        if not skip_test:
            render_set(dataset.model_path, "test", scene.loaded_iter, scene.getTestCameras(), gaussians, pipeline, background, cam_type)

        if not skip_video:
            render_set(dataset.model_path, "video", scene.loaded_iter, scene.getVideoCameras(), gaussians, pipeline, background, cam_type)

parser = ArgumentParser(description="Testing script parameters")
model = ModelParams(parser, sentinel=True)
pipeline = PipelineParams(parser)
hyperparam = ModelHiddenParams(parser)
parser.add_argument("--iteration", type=int, default=-1)
parser.add_argument("--skip_train", action="store_true")
parser.add_argument("--skip_test", action="store_true")
parser.add_argument("--skip_video", action="store_true")
parser.add_argument("--quiet", action="store_true")
parser.add_argument("--configs", type=str, default="/content/4DGaussians/arguments/dnerf/mutant.py")
parser.add_argument("--expname", type=str, default="dnerf/mutant")
args, _ = parser.parse_known_args()
setattr(args, 'source_path', "/content/test/data/mutant")
setattr(args, 'model_path', "/content/4DGaussians/output/dnerf/mutant")
setattr(args, 'extension', ".png")
setattr(args, 'sh_degree', 3)
setattr(args, 'expname', "dnerf/mutant")
if args.configs and os.path.exists(args.configs):
    config = mmcv.Config.fromfile(args.configs)
    args = merge_hparams(args, config)
    print("Config loaded. sh_degree:", getattr(args, 'sh_degree', 'Not set'))
else:
    print("Warning: Configuration file not found or invalid. Using fallback defaults.")
    setattr(args, 'sh_degree', 3)
    setattr(args, 'images', "images")
    setattr(args, 'resolution', -1)
    setattr(args, 'white_background', False)
    setattr(args, 'data_device', "cuda")
    setattr(args, 'eval', False)
    setattr(args, 'render_process', False)
    setattr(args, 'add_points', False)
    setattr(args, 'extension', ".png")
    setattr(args, 'llffhold', 8)
    setattr(args, 'convert_SHs_python', False)
    setattr(args, 'compute_cov3D_python', False)
    setattr(args, 'debug', False)
    setattr(args, 'timebase_pe', 4)
    setattr(args, 'posebase_pe', 10)
    setattr(args, 'defor_depth', 2)
    setattr(args, 'net_width', 64)
    setattr(args, 'scale_rotation_pe', 2)
    setattr(args, 'opacity_pe', 2)
    setattr(args, 'timenet_width', 64)
    setattr(args, 'timenet_output', 32)
    setattr(args, 'bounds', 1.0)
    setattr(args, 'plane_tv_weight', 0.0001)
    setattr(args, 'time_smoothness_weight', 0.001)
    setattr(args, 'l1_time_planes', 0.0001)
    setattr(args, 'kplanes_config', "")
    setattr(args, 'multires', 8)
    setattr(args, 'no_dx', False)
    setattr(args, 'no_grid', False)
    setattr(args, 'no_ds', False)
    setattr(args, 'no_dr', False)
    setattr(args, 'no_do', False)
    setattr(args, 'no_dshs', False)
    setattr(args, 'empty_voxel', False)
    setattr(args, 'grid_pe', 2)
    setattr(args, 'static_mlp', False)
    setattr(args, 'apply_rotation', False)
safe_state(args.quiet)
print("Rendering ", args.model_path)
print(f"Dataset path: {args.source_path}")
print(f"sh_degree: {getattr(args, 'sh_degree', 'Not set')}")
print(f"extension: {getattr(args, 'extension', 'Not set')}")
print(f"expname: {getattr(args, 'expname', 'Not set')}")
transforms_file = os.path.join(args.source_path, "transforms.json")
if os.path.exists(transforms_file):
    with open(transforms_file, 'r') as f:
        import json
        transforms = json.load(f)
        print("Transforms.json frames:", [frame.get("file_path") for frame in transforms.get("frames", [])])
else:
    print(f"Error: transforms.json not found at {transforms_file}")
render_sets(model.extract(args), hyperparam.extract(args), args.iteration, pipeline.extract(args), args.skip_train, args.skip_test, args.skip_video)

from IPython.display import HTML
from base64 import b64encode
def display_video(video_path):
  mp4 = open(video_path,'rb').read()
  data_url = "data:video/mp4;base64," + b64encode(mp4).decode()
  return HTML("""
  <video width=1000 controls>
    <source src="%s" type="video/mp4">
  </video>
  """ % data_url)

save_dir = '/content/4DGaussians/output/dnerf/mutant/video/ours_20000/video_rgb.mp4'
import os
import glob
display_video(save_dir)

