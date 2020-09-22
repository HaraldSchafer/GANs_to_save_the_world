import numpy as np
import torch
from torch import nn
from PIL import Image
from torch.utils import data
from xx.uncommon.cache import cache_gen
import tensorflow as tf
import torchvision
from torchvision import transforms
from functools import partial
from random import random


def convert_rgb_to_transparent(image):
    if image.mode == 'RGB':
        return image.convert('RGBA')
    return image


def convert_transparent_to_rgb(image):
    if image.mode == 'RGBA':
        return image.convert('RGB')
    return image


def resize_to_minimum_size(min_size, image):
    if max(*image.size) < min_size:
        return torchvision.transforms.functional.resize(image, min_size)
    return image


class RandomApply(nn.Module):
    def __init__(self, prob, fn, fn_else=lambda x: x):
        super().__init__()
        self.fn = fn
        self.fn_else = fn_else
        self.prob = prob

    def forward(self, x):
        fn = self.fn if random() < self.prob else self.fn_else
        return fn(x)



class expand_greyscale(object):
    def __init__(self, transparent):
        self.transparent = transparent

    def __call__(self, tensor):
        channels = tensor.shape[0]
        num_target_channels = 4 if self.transparent else 3

        if channels == num_target_channels:
            return tensor

        alpha = None
        if channels == 1:
            color = tensor.expand(3, -1, -1)
        elif channels == 2:
            color = tensor[:1].expand(3, -1, -1)
            alpha = tensor[1:]
        else:
            raise Exception(f'image with invalid number of channels given {channels}')

        if alpha is None and self.transparent:
            alpha = torch.ones(1, *tensor.shape[1:], device=tensor.device)

        return color if not self.transparent else torch.cat((color, alpha))


class Dataset(data.Dataset):
    def __init__(self, folder, image_size, transparent=False,
                 aug_prob=0., max_zoom=8, size=1000000):
        super().__init__()
        self.size = size
        self.samples = np.random.uniform(0.0, 1.0, size=(self.size, 3))
        self.samples[:,2] = np.floor(max_zoom*self.samples[:,2]) + 1.0
        self.image_size = image_size


        # Set CPU as available physical device
        my_devices = tf.config.experimental.list_physical_devices(device_type='CPU')
        tf.config.experimental.set_visible_devices(devices=my_devices, device_type='CPU')
        tf.config.set_visible_devices([], 'GPU')
        self.g = cache_gen('/raid.nvme/caches/unvision/train', shuffle_size=50000)
        self.in_batch_idx = 0
        convert_image_fn = convert_transparent_to_rgb if not transparent else convert_rgb_to_transparent
        num_channels = 3 if not transparent else 4

        self.transform = transforms.Compose([
            transforms.Lambda(convert_image_fn),
            transforms.Lambda(partial(resize_to_minimum_size, image_size)),
            transforms.Resize(image_size),
            RandomApply(aug_prob, transforms.RandomResizedCrop(image_size, scale=(0.5, 1.0), ratio=(0.98, 1.02)), transforms.CenterCrop(image_size)),
            transforms.ToTensor(),
            transforms.Lambda(expand_greyscale(transparent))
        ])

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        if self.in_batch_idx == 0:
            self.in_batch_idx = 0
            a = next(self.g)
            self.imgs = a[1]['img'].numpy()
            self.features = a[0]['input_features'].numpy()
        img = np.zeros((512,512,3), dtype=np.uint8)
        img[:256,:,:] = ((self.imgs[self.in_batch_idx, :, :, :3] + 1.0)*128.0).astype(np.uint8)
        img[256:,:,:] = ((self.imgs[self.in_batch_idx, :, :, 3:] + 1.0)*128.0).astype(np.uint8)
        feature_vector = self.features[self.in_batch_idx]

        img = Image.fromarray(img)
        self.in_batch_idx = (self.in_batch_idx + 1) % 512
        '''
        sample = self.samples[idx]
        img = Image.fromarray(get_custom_tile(*sample))
        '''
        return self.transform(img), feature_vector
