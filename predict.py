"""
This file is designed for prediction of bounding boxes for a single image.
Predictions could be made in two ways: command line style or service style. Command line style denotes that one can
run this script from the command line and configure all options right in the command line. Service style allows
to call :func:`initialize` function once and call :func:`hot_predict` function as many times as it needed to.

"""

import tensorflow as tf
import os, json, subprocess
from optparse import OptionParser


from scipy.misc import imread, imresize
#from PIL import Image, ImageDraw

from train import build_forward
from utils.annolist import AnnotationLib as al
from utils.train_utils import add_rectangles, rescale_boxes


# define map scale for diam calculation
SCALE = 0.01 # km/pix, output from USGS ISIS

def initialize(weights_path, hypes_path, options=None):
    """Initialize prediction process.

    All long running operations like TensorFlow session start and weights loading are made here.

    Args:
        weights_path (string): The path to the model weights file.
        hypes_path (string): The path to the hyperparameters file.
        options (dict): The options dictionary with parameters for the initialization process.
    Returns (dict):
        The dict object which contains `sess` - TensorFlow session, `pred_boxes` - predicted boxes Tensor,
          `pred_confidences` - predicted confidences Tensor, `x_in` - input image Tensor,
          `hypes` - hyperparametets dictionary.
    """

    H = prepare_options(hypes_path, options)

    tf.reset_default_graph()
    x_in = tf.placeholder(tf.float32, name='x_in', shape=[H['image_height'], H['image_width'], 3])
    if H['use_rezoom']:
        pred_boxes, pred_logits, pred_confidences, pred_confs_deltas, pred_boxes_deltas \
            = build_forward(H, tf.expand_dims(x_in, 0), 'test', reuse=None)
        grid_area = H['grid_height'] * H['grid_width']
        pred_confidences = tf.reshape(
            tf.nn.softmax(tf.reshape(pred_confs_deltas, [grid_area * H['rnn_len'], H['num_classes']])),
            [grid_area, H['rnn_len'], H['num_classes']])
        if H['reregress']:
            pred_boxes = pred_boxes + pred_boxes_deltas
    else:
        pred_boxes, pred_logits, pred_confidences = build_forward(H, tf.expand_dims(x_in, 0), 'test', reuse=None)

    saver = tf.train.Saver()
    sess = tf.Session()
    sess.run(tf.initialize_all_variables())
    saver.restore(sess, weights_path)
    return {'sess': sess, 'pred_boxes': pred_boxes, 'pred_confidences': pred_confidences, 'x_in': x_in, 'hypes': H}


def hot_predict(image_path, init_params, to_json=True):
    """Makes predictions when all long running preparation operations are made.

    Args:
        image_path (string): The path to the source image.
        init_params (dict): The parameters produced by :func:`initialize`.
    Returns (Annotation):
        The annotation for the source image.
    """

    H = init_params['hypes']
    options = H['evaluate']  # The options for more precise prediction of bounding boxes.

    # predict
    orig_img = imread(image_path)[:, :, :3]
    img = imresize(orig_img, (H['image_height'], H['image_width']), interp='cubic')
    (np_pred_boxes, np_pred_confidences) = init_params['sess'].\
        run([init_params['pred_boxes'], init_params['pred_confidences']], feed_dict={init_params['x_in']: img})
    pred_anno = al.Annotation()
    pred_anno.imageName = image_path
    _, rects = add_rectangles(H, [img], np_pred_confidences, np_pred_boxes, use_stitching=True,
                              rnn_len=H['rnn_len'], min_conf=options['min_conf'], tau=options['tau'],
                              show_suppressed=False)

    pred_anno.rects = [r for r in rects if r.x1 < r.x2 and r.y1 < r.y2]
    pred_anno.imagePath = os.path.abspath(image_path)
    pred_anno = rescale_boxes((H['image_height'], H['image_width']), pred_anno, orig_img.shape[0], orig_img.shape[1])
    result = [r.writeJSON() for r in pred_anno if r.score > options['min_conf']] if to_json else pred_anno
    return result


def prepare_options(hypes_path='hypes.json', options=None):
    """Sets parameters of the prediction process.

    Args:
        hypes_path (string): The path to model hyperparameters file.
        options (dict): The command line options to set before start predictions.
    Returns (dict):
        The model hyperparameters dictionary.
    """

    with open(hypes_path, 'r') as f:
        H = json.load(f)



    # set default options values if they were not provided
    if options is None:
        if 'evaluate' in H:
            options = H['evaluate']
        else:
            print ('Evaluate parameters were not found! You can provide them through hyperparameters json file '
                   'or hot_predict options parameter.')
            return None
    else:
        for key, val in options.items():
            H['evaluate'][key] = val

    os.environ['CUDA_VISIBLE_DEVICES'] = str(options['gpu'])

    return H


def save_results(image_path, anno):
    """Saves results of the prediction.

    Args:
        image_path (string): The path to source image to predict bounding boxes.
        anno (Annotation): The predicted annotations for source image.
    Returns:
        Nothing.
    """

    import cv2 as cv
    # draw - old pil
    # new_img = Image.open(image_path)
    # d = ImageDraw.Draw(new_img)

    # draw - new opencv
    new_img = imread(image_path)

    # open diameters file for writing
    diamfile = open('/media/chris/data1/cda/cda/tensorbox/data/cda/ctx_output/' + 'result-' + os.path.basename(image_path) + '.txt','w')

    rects = anno['rects'] if type(anno) is dict else anno.rects
    for r in rects:
        if r.score > 0.8:
            # draw circles
            centre = (int(round(r.left()+(r.right()-r.left())/2)), int(round(r.bottom()+(r.top()-r.bottom())/2)))
            print centre;
            print 'r.left ', r.left()
            print 'r.right ', r.right()
            print 'r.top ', r.top()
            print 'r.bottom ', r.bottom()
            # radius is the average of box height and width, halved
            radius = int(round(((r.right()-r.left())/2 + (r.bottom()-r.top())/2)/2))
            print 'radius = ', radius

            cv.circle(new_img,
                      centre,
                      radius,
                      (0, 0, 255), -2, 8, 0)

            cv.line(new_img, (centre[0]-3, centre[1]), (centre[0]+3, centre[1]),
                    (0, 0, 255), 2, 8, 0)

            cv.line(new_img, (centre[0], centre[1]-3), (centre[0], centre[1]+3),
                    (0, 0, 255), 2, 8, 0)

            # find diameter in m
            diam = (((r.right()-r.left())/2 + (r.bottom()-r.top())/2)/2) * SCALE

            # write diameter to file
            diamfile.write(str(diam) + '\n')

            # draw thick rectangles
            # cor = (r.left(), r.top(), r.right(), r.bottom())
            # width = 3
            # for i in range(width):
            #    d.rectangle(cor, outline="red")
            #    cor = (cor[0]+1,cor[1]+1, cor[2]+1,cor[3]+1)

        #d.rectangle([r.left(), r.top(), r.right(), r.bottom()], outline=(255, 0, 0), 2, 8, 0)

    # save
    #fpath = os.path.join(os.path.dirname(image_path), 'result-' + os.path.basename(image_path) + '.png')
    fpath = os.path.join('/media/chris/data1/cda/cda/tensorbox/data/cda/ctx_output/', 'result-' + os.path.basename(image_path) + '.png')

    # new_img.save(fpath)
    cv.imwrite(fpath, new_img)
    subprocess.call(['chmod', '777', fpath])

    #fpath = os.path.join(os.path.dirname(image_path), 'result-' + os.path.basename(image_path) + '.json')
    fpath = os.path.join('/media/chris/data1/cda/cda/tensorbox/data/cda/ctx_output/', 'result-' + os.path.basename(image_path) + '.json')

    if type(anno) is dict:
        with open(fpath, 'w') as f:
            json.dump(anno, f)
    else:
        al.saveJSON(fpath, anno)
    subprocess.call(['chmod', '777', fpath])


def main():
    parser = OptionParser(usage='usage: %prog [options] <image> <weights> <hypes>')
    parser.add_option('--gpu', action='store', type='int', default=0)
    parser.add_option('--tau', action='store', type='float',  default=0.25)
    parser.add_option('--min_conf', action='store', type='float', default=0.2)

    (options, args) = parser.parse_args()
    if len(args) < 3:
        print ('Provide image, weights and hypes paths')
        return

    init_params = initialize(args[1], args[2], options.__dict__)
    pred_anno = hot_predict(args[0], init_params, False)
    save_results(args[0], pred_anno)


if __name__ == '__main__':
    main()
