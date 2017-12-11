import numpy as np
from os import listdir, path, makedirs
from tqdm import tqdm
import cv2
import shutil
import json
import random
from sklearn.model_selection import train_test_split

from .data_baseclass import DataBaseclass
from .synthia import SYNTHIA_BASEPATH, \
    one_channel_image_reader


# Set label information according to synthia README
LABELINFO = {
   0: {'name': 'void', 'color': [0, 0, 0]},
   1: {'name': 'sky', 'color': [128, 128, 128]},
   2: {'name': 'building', 'color': [128, 0, 0]},
   3: {'name': 'road', 'color': [128, 64, 128]},
   4: {'name': 'sidewalk', 'color': [0, 0, 192]},
   5: {'name': 'fence', 'color': [64, 64, 128]},
   6: {'name': 'vegetation', 'color': [128, 128, 0]},
   7: {'name': 'pole', 'color': [192, 192, 128]},
   8: {'name': 'car', 'color': [64, 0, 128]},
   9: {'name': 'traffic sign', 'color': [192, 128, 128]},
   10: {'name': 'pedestrian', 'color': [64, 64, 0]},
   11: {'name': 'bicycle', 'color': [0, 128, 192]},
   12: {'name': 'lanemarking', 'color': [0, 192, 0]}
}


class SynthiaCityscapes(DataBaseclass):
    """Driver for SYNTHIA dataset (http://synthia-dataset.net/).
    Preprocessing resizes images to 640x368 and performs a static 20% test-split for all
    given sequences."""

    def __init__(self, base_path=SYNTHIA_BASEPATH, force_preprocessing=False,
                 batchsize=1, **data_config):

        config = {
            'augmentation': {
                'crop': 480,
                'scale': [0.7, 1.5],
                'vflip': True,
                'hflip': False,
                'gamma': [0.3, 2]
            }
        }
        config.update(data_config)
        self.config = config

        if not path.exists(base_path):
            message = 'ERROR: Path to SYNTHIA dataset does not exist.'
            print(message)
            raise IOError(1, message, base_path)

        self.basepath = path.join(base_path, 'RAND_CITYSCAPES')

        # Every sequence got their own train/test split during preprocessing. According
        # to the loaded sequences, we now collect all files from all sequence-subsets
        # into one list.
        with open(path.join(self.basepath, 'train_test_split.json'), 'r') as f:
                split = json.load(f)
                trainset = [{'image_name': filename} for filename in split['trainset']]
                testset = [{'image_name': filename} for filename in split['testset']]
        # Intitialize Baseclass
        DataBaseclass.__init__(self, trainset, testset, batchsize,
                               ['rgb', 'depth', 'labels'], LABELINFO)

    def _preprocessing(self, sequence):
        rootpath = path.join(self.base_path, sequence, 'GT')

        for direction in ['F', 'B', 'L', 'R']:
            inpath, outpath = (path.join(rootpath, pref,
                                         'Stereo_Right/Omni_{}'.format(direction))
                               for pref in ['LABELS', 'LABELS_NPY'])

            if path.exists(outpath):
                shutil.rmtree(outpath)
            makedirs(outpath)
            for filename in tqdm(listdir(inpath)):
                array = one_channel_image_reader(path.join(inpath, filename),
                                                 np.uint8)
                np.save(path.join(outpath, filename.split('.')[0]), array)

            if sequence == 'RAND_CITYSCAPES':
                # There are no different directions for this sequence.
                break

        # create train-test-split if necessary
        if not path.exists(path.join(self.base_path, sequence, 'train_test_split.json')):
            print("INFO: Creating Train-Test-Split")
            filenames = [filename.split('.')[0] for filename
                         in listdir(path.join(rootpath, 'LABELS/Stereo_Right/Omni_F'))]
            trainset, testset = train_test_split(filenames, test_size=0.2)
            with open(path.join(self.base_path, sequence, '/train_test_split.json'),
                      'w') as f:
                json.dump({'trainset': trainset, 'testset': testset}, f)

    def _get_data(self, image_name, training_format=True):
        """Returns data for one given image number from the specified sequence."""
        filetype = {'rgb': 'png', 'depth': 'png', 'labels': 'npy'}

        rgb_filename, depth_filename, groundtruth_filename = (
            path.join(self.basepath, '{}/Stereo_Right/Omni_F/{}.{}'
                      .format(pref, image_name, filetype[modality]))
            for pref, modality in zip(['RGB', 'Depth', 'GT/LABELS_NPY'],
                                      ['rgb', 'depth', 'labels']))

        blob = {}
        blob['rgb'] = cv2.imread(rgb_filename)
        blob['depth'] = cv2.imread(depth_filename, 2)  # flag 2 -> read image with 16bit depth
        labels = np.load(groundtruth_filename)
        # Dirty fix for the class mappings as in adapnet paper
        labels[labels == 12] = 11  # motorcycle -> bicycle
        labels[labels == 13] = 12  # parking spot -> lanemarking
        labels[labels == 14] = 0   # road_work -> void
        labels[labels == 15] = 7   # traffic light -> pole
        labels[labels == 16] = 0   # terrain -> void
        labels[labels == 17] = 11  # rider -> bicycle
        labels[labels == 18] = 8   # truck -> car
        labels[labels == 19] = 8   # bus -> car
        labels[labels == 20] = 0   # train -> void
        labels[labels == 21] = 0   # wall -> void
        labels[labels == 22] = 12  # lanemarking

        blob['labels'] = labels

        if training_format:
            scale = self.config['augmentation']['scale']
            crop = self.config['augmentation']['crop']
            hflip = self.config['augmentation']['hflip']
            vflip = self.config['augmentation']['vflip']
            gamma = self.config['augmentation']['gamma']

            if scale and crop:
                h, w, _ = blob['rgb'].shape
                min_scale = crop / float(min(h, w))
                k = random.uniform(max(min_scale, scale[0]), scale[1])
                blob['rgb'] = cv2.resize(blob['rgb'], None, fx=k, fy=k)
                blob['depth'] = cv2.resize(blob['depth'], None, fx=k, fy=k,
                                           interpolation=cv2.INTER_NEAREST)
                blob['labels'] = cv2.resize(blob['labels'], None, fx=k, fy=k,
                                            interpolation=cv2.INTER_NEAREST)

            if crop:
                h, w, _ = blob['rgb'].shape
                h_c = random.randint(0, h - crop)
                w_c = random.randint(0, w - crop)
                for m in ['rgb', 'depth', 'labels']:
                    blob[m] = blob[m][h_c:h_c+crop, w_c:w_c+crop, ...]

            if hflip and np.random.choice([0, 1]):
                for m in ['rgb', 'depth', 'labels']:
                    blob[m] = np.flip(blob[m], axis=0)

            if vflip and np.random.choice([0, 1]):
                for m in ['rgb', 'depth', 'labels']:
                    blob[m] = np.flip(blob[m], axis=1)

            if gamma:
                k = random.uniform(gamma[0], gamma[1])
                lut = np.array([((i / 255.0) ** (1/k)) * 255
                                for i in np.arange(0, 256)]).astype("uint8")
                blob['rgb'] = lut[blob['rgb']]

            # Format labels into one-hot
            blob['labels'] = np.array(one_hot_lookup ==
                                      blob['labels'][:, :, None]).astype(int)

        # We have to add a dimension for the channels, as there is only one and the
        # dimension is omitted.
        blob['depth'] = np.expand_dims(blob['depth'], 3)

        # Force the image dimension to be multiple of 16
        h, w, _ = blob['rgb'].shape
        h_c, w_c = [d - (d % 16) for d in [h, w]]
        if h_c != h or w_c != w:
            for m in ['rgb', 'depth', 'labels']:
                blob[m] = blob[m][:h_c, :w_c, ...]

        return blob
