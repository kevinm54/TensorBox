import numpy as np
import random
import json
import os
from scipy.misc import imread, imresize
from utils import (annotation_jitter, image_to_h5,
                   annotation_to_h5, load_data_mean)
from utils.annolist import AnnotationLib as al
from itertools import islice

def rescale_boxes(anno, target_width, target_height):
    I = imread(anno.imageName)
    x_scale = target_width / float(I.shape[1])
    y_scale = target_height / float(I.shape[0])
    for r in anno.rects:
        assert r.x1 < r.x2
        r.x1 *= x_scale
        r.x2 *= x_scale
        assert r.x1 < r.x2
        r.y1 *= y_scale
        r.y2 *= y_scale
    return I

def make_sparse(n, d):
    v = np.zeros((d,), dtype=np.float32)
    v[n] = 1.
    return v

def load_idl_tf(idlfile, net_config, jitter):
    """Take the idlfile and net configuration and create a generator
    that outputs a jittered version of a random image from the annolist
    that is mean corrected."""

    annolist = al.parse(idlfile)
    annos = [x for x in annolist]
    for anno in annos:
        anno.imageName = os.path.join(
            os.path.dirname(os.path.realpath(idlfile)), anno.imageName)
    random.seed(0)
    while True:
        random.shuffle(annos)
        for anno in annos:
            I = rescale_boxes(anno, net_config["image_width"], net_config["image_height"])
            if jitter:
                jit_image, jit_anno = annotation_jitter(I,
                    anno, target_width=net_config["image_width"],
                    target_height=net_config["image_height"])
            else:
                jit_image = I
                jit_anno = anno
            boxes, box_flags = annotation_to_h5(
                anno, net_config["grid_width"], net_config["grid_height"],
                net_config["region_size"], net_config["rnn_len"])
            yield {"imname": anno.imageName, "raw": [], "image": jit_image,
                   "boxes": boxes, "box_flags": box_flags}

def load_data_gen(H, phase, val_or_test):
    net_config = H["net"]
    grid_size = net_config['grid_width'] * net_config['grid_height']

    data = load_idl_tf('%s/data/brainwash/brainwash_%s.idl' % (
        os.path.dirname(os.path.realpath(__file__)), val_or_test), net_config, jitter={'train': True, 'test': False}[phase])

    for d in data:
        output = {}
        
        rnn_len = net_config["rnn_len"]
        box_flags = d['box_flags'][0,:,0,0:rnn_len,0]
        boxes = np.transpose(d['boxes'][0,:,:,0:rnn_len,0], (0,2,1))
        assert(box_flags.shape == (grid_size, rnn_len))
        assert(boxes.shape == (grid_size, rnn_len, 4))

        output['image'] = d['image']
        output['confs'] = np.array([make_sparse(row[0], d=2) for row in box_flags])
        output['boxes'] = boxes
        output['flags'] = box_flags
        
        yield output
