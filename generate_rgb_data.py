"""
## CycleISP: Real Image Restoration Via Improved Data Synthesis
## Syed Waqas Zamir, Aditya Arora, Salman Khan, Munawar Hayat, Fahad Shahbaz Khan, Ming-Hsuan Yang, and Ling Shao
## CVPR 2020
## https://arxiv.org/abs/2003.07761
"""

import os
import argparse
from tqdm import tqdm

import torch.nn as nn
from torch.utils.data import DataLoader

from networks.cycleisp import Rgb2Raw, Raw2Rgb, CCM
from dataloaders.data_rgb import get_rgb_data
from utils.noise_sampling import random_noise_levels_sidd, add_noise
import utils
import cv2
from skimage import img_as_ubyte
from utils.Transforms import *

parser = argparse.ArgumentParser(description='From clean RGB images, generate {RGB_clean, RGB_noisy} pairs')
parser.add_argument('--input_dir', default='./FlickrDataset',
                    type=str, help='Directory of clean RGB images')
parser.add_argument('--result_dir', default='./datasets/flickr/',
                    type=str, help='Directory for results')
parser.add_argument('--weights_rgb2raw', default='./pretrained_models/isp/rgb2raw_joint.pth',
                    type=str, help='weights rgb2raw branch')
parser.add_argument('--weights_raw2rgb', default='./pretrained_models/isp/raw2rgb_joint.pth',
                    type=str, help='weights raw2rgb branch')
parser.add_argument('--weights_ccm', default='./pretrained_models/isp/ccm_joint.pth',
                    type=str, help='weights ccm branch')
parser.add_argument('--gpus', default='0', type=str, help='CUDA_VISIBLE_DEVICES')
parser.add_argument('--use_gpu', action='store_true', help='CUDA_VISIBLE_DEVICES')
parser.add_argument('--num_workers', default=4, type=int, help='CUDA_VISIBLE_DEVICES')

args = parser.parse_args()

use_cuda = args.use_gpu and torch.cuda.is_available()
device = 'cuda' if use_cuda else 'cpu'
print(device)

os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = args.gpus

utils.mkdir(args.result_dir+'clean')
utils.mkdir(args.result_dir+'noisy')

test_dataset = get_rgb_data(args.input_dir, transforms=RandomCropWb(64))
test_loader = DataLoader(dataset=test_dataset, batch_size=4, shuffle=False, num_workers=args.num_workers,
                         drop_last=False)

model_rgb2raw = Rgb2Raw()
model_ccm = CCM()
model_raw2rgb = Raw2Rgb()

utils.load_checkpoint(model_rgb2raw, args.weights_rgb2raw, map_location=device)
utils.load_checkpoint(model_ccm, args.weights_ccm, map_location=device)
utils.load_checkpoint(model_raw2rgb, args.weights_raw2rgb, map_location=device)

model_rgb2raw.to(device)
model_ccm.to(device)
model_raw2rgb.to(device)

if use_cuda:
    model_rgb2raw = nn.DataParallel(model_rgb2raw)
    model_ccm = nn.DataParallel(model_ccm)
    model_raw2rgb = nn.DataParallel(model_raw2rgb)

model_rgb2raw.eval()
model_ccm.eval()
model_raw2rgb.eval()

with torch.no_grad():
    for ii, data in enumerate(tqdm(test_loader), 0):
        rgb_gt = data[0].to(device)
        filenames = data[1]

        ## Convert clean rgb image to clean raw image
        raw_gt = model_rgb2raw(rgb_gt)  # raw_gt is in RGGB format
        raw_gt = torch.clamp(raw_gt, 0, 1)
        
        ########## Add noise to clean raw images ##########
        for j in range(raw_gt.shape[0]):  # Use loop to add different noise to different images.
            filename = filenames[j]
            shot_noise, read_noise = random_noise_levels_sidd()
            shot_noise, read_noise = shot_noise.to(device), read_noise.to(device)
            raw_noisy = add_noise(raw_gt[j], use_cuda=use_cuda)
            raw_noisy = torch.clamp(raw_noisy, 0, 1)  # CLIP NOISE
            
            #### Convert raw noisy to rgb noisy ####
            ccm_tensor = model_ccm(rgb_gt[j].unsqueeze(0))
            rgb_noisy = model_raw2rgb(raw_noisy.unsqueeze(0), ccm_tensor)
            rgb_noisy = torch.clamp(rgb_noisy, 0, 1)

            rgb_noisy = rgb_noisy.permute(0, 2, 3, 1).squeeze().cpu().detach().numpy()

            rgb_clean = rgb_gt[j].permute(1, 2, 0).cpu().detach().numpy()

            cv2.imwrite(args.result_dir+'clean/'+filename[:-4]+'.png', img_as_ubyte(rgb_clean))
            cv2.imwrite(args.result_dir+'noisy/'+filename[:-4]+'.png', img_as_ubyte(rgb_noisy))
