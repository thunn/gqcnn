# -*- coding: utf-8 -*-
"""
Copyright ©2017. The Regents of the University of California (Regents). All Rights Reserved.
Permission to use, copy, modify, and distribute this software and its documentation for educational,
research, and not-for-profit purposes, without fee and without a signed licensing agreement, is
hereby granted, provided that the above copyright notice, this paragraph and the following two
paragraphs appear in all copies, modifications, and distributions. Contact The Office of Technology
Licensing, UC Berkeley, 2150 Shattuck Avenue, Suite 510, Berkeley, CA 94720-1620, (510) 643-
7201, otl@berkeley.edu, http://ipira.berkeley.edu/industry-info for commercial licensing opportunities.

IN NO EVENT SHALL REGENTS BE LIABLE TO ANY PARTY FOR DIRECT, INDIRECT, SPECIAL,
INCIDENTAL, OR CONSEQUENTIAL DAMAGES, INCLUDING LOST PROFITS, ARISING OUT OF
THE USE OF THIS SOFTWARE AND ITS DOCUMENTATION, EVEN IF REGENTS HAS BEEN
ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

REGENTS SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE. THE SOFTWARE AND ACCOMPANYING DOCUMENTATION, IF ANY, PROVIDED
HEREUNDER IS PROVIDED "AS IS". REGENTS HAS NO OBLIGATION TO PROVIDE
MAINTENANCE, SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
"""
"""
Displays robust grasps planned using a GQ-CNN-based policy on a set of saved RGB-D images.
The default configuration is cfg/examples/policy.yaml.

Author
------
Jeff Mahler

YAML Configuration File Parameters
----------------------------------
sensor/image_dir : str
    directory to the sample images, specified relative to /path/to/your/gqcnn/ (change this to try your own images!)
sensor/type : str
    type of sensor to use (virtual_primesense by default to use pre-stored images)
sensor/frame : str
    name of the sensor frame of references

calib_dir : str
    directory to the sample camera calibration files, specified relative to /path/to/your/gqcnn/

policy/gqcnn_model : str
    path to a directory containing a GQ-CNN model (change this to try your own networks!)
policy/num_seed_samples : int
    number of initial samples to take in the cross-entropy method (CEM) optimizer (smaller means faster grasp planning, lower-quality grasps)
policy/num_gmm_samples : int
    number of samples to take from the Gaussian Mixture Models on each iteration of the CEM optimizer
policy/num_iters : int
    number of sample-and-refit iterations of CEM
policy/gmm_refit_p : flota
    percentage of samples to use in the elite set on each iteration of CEM
policy/gmm_component_frac : float
    number of GMM components to use as a fraction of the sample size
policy/gmm_reg_covat : float
    regularization constant to ensure GMM sample diversity
policy/deterministic : bool
    True (1) if execution should be deterministic (via setting a random seed) and False (0) otherwise
policy/gripper_width : float
    distance between the jaws, in meters
policy/crop_height : int
    height of bounding box to use for cropping the image around a grasp candidate before passing it into the GQ-CNN
policy/crop_width : int
    width of bounding box to use for cropping the image around a grasp candidate before passing it into the GQ-CNN
policy/sampling/type : str
    grasp sampling type (use antipodal_depth to sample antipodal pairs in image space)
policy/sampling/friction_coef : float
    friction coefficient to use in sampling
policy/sampling/depth_grad_thresh : float
    threshold on depth image gradients for edge detection
policy/sampling/depth_grad_gaussian_sigma : float
    variance for gaussian filter to smooth image before taking gradients
policy/sampling/downsample_rate : float
    factor by which to downsample the image when detecting edges (larger number means edges are smaller images, which speeds up performance)
policy/sampling/max_rejection_samples : int
    maximum number of samples to take when sampling antipodal candidates (larger means potentially longer runtimes)
policy/sampling/max_dist_from_center : int
    maximum distance, in pixels, from the image center allowed in grasp sampling
policy/sampling/min_dist_from_boundary : int
    minimum distance, in pixels, of a grasp from the image boundary
policy/sampling/min_grasp_dist : float
    minimum distance between grasp vectors allowed in sampling (larger means greater sample diversity but potentially lower precision)
policy/sampling/angle_dist_weight : float
    weight for the distance between grasp axes in radians (we recommend keeping the default)
policy/sampling/depth_samples_per_grasp : int
    number of depth samples to take per independent antipodal grasp sample in image space
policy/sampling/depth_sample_win_height: int
    height of window used to compute the minimum depth for grasp depth sampling
policy/sampling/depth_sample_win_width: int
    width of window used to compute the minimum depth for grasp depth sampling
policy/sampling/min_depth_offset : float
    offset, in cm, from the min depth
policy/sampling/max_depth_offset : float
    offset, in cm, from the max depth

policy/vis/grasp_sampling : bool
    True (1) if grasp sampling should be displayed (for debugging)
policy/vis/tf_images : bool
    True (1) if transformed images should be displayed (for debugging)
policy/vis/grasp_candidates : bool
    True (1) if grasp candidates should be displayed (for debugging)
policy/vis/elite_grasps : bool
    True (1) if the elite set should be displayed (for debugging)
policy/vis/grasp_ranking : bool
    True (1) if the ranked grasps should be displayed (for debugging)
policy/vis/grasp_plan : bool
    True (1) if the planned grasps should be displayed (for debugging)
policy/vis/final_grasp : bool
    True (1) if the final planned grasp should be displayed (for debugging)
policy/vis/k : int
    number of grasps to display

inpaint_rescale_factor : float
    scale factor to resize the image by before inpainting (smaller means faster performance by less precise)

"""
import argparse
import logging
import IPython
import numpy as np
import os
import sys
import time

from autolab_core import RigidTransform, YamlConfig
from perception import BinaryImage, CameraIntrinsics, ColorImage, DepthImage, RgbdImage
from visualization import Visualizer2D as vis

from gqcnn import CrossEntropyRobustGraspingPolicy, RgbdImageState

if __name__ == '__main__':
    # set up logger
    logging.getLogger().setLevel(logging.DEBUG)

    # parse args
    parser = argparse.ArgumentParser(description='Run a grasping policy on an example image')
    parser.add_argument('--depth_image', type=str, default=None, help='path to a test depth image stored as a .npy file')
    parser.add_argument('--segmask', type=str, default=None, help='path to an optional segmask to use')
    parser.add_argument('--camera_intrinsics', type=str, default=None, help='path to the camera intrinsics')
    parser.add_argument('--model_dir', type=str, default=None, help='path to a trained model to run')
    parser.add_argument('--config_filename', type=str, default=None, help='path to configuration file to use')
    args = parser.parse_args()
    depth_im_filename = args.depth_image
    segmask_filename = args.segmask
    camera_intr_filename = args.camera_intrinsics
    model_dir = args.model_dir
    config_filename = args.config_filename

    if depth_im_filename is None:
        depth_im_filename = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                         '..',
                                         'data/rgbd/multiple_objects/depth_0.npy')
    if camera_intr_filename is None:
        camera_intr_filename = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                            '..',
                                            'data/rgbd/multiple_objects/primesense_overhead_ir.intr')    
    if config_filename is None:
        config_filename = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                       '..',
                                       'cfg/examples/dex-net_2.0.yaml')
    
    # read config
    config = YamlConfig(config_filename)
    inpaint_rescale_factor = config['inpaint_rescale_factor']
    policy_config = config['policy']

    # make relative paths absolute
    if model_dir is not None:
        policy_config['metric']['gqcnn_model'] = model_dir
    if not os.path.isabs(policy_config['metric']['gqcnn_model']):
        policy_config['metric']['gqcnn_model'] = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                              '..',
                                                              policy_config['metric']['gqcnn_model'])

    # setup sensor
    camera_intr = CameraIntrinsics.load(camera_intr_filename)
        
    # read images
    depth_im = DepthImage.open(depth_im_filename, frame=camera_intr.frame)
    depth_im = depth_im.inpaint(rescale_factor=inpaint_rescale_factor)
    color_im = ColorImage(np.zeros([depth_im.height, depth_im.width, 3]).astype(np.uint8),
                          frame=camera_intr.frame)
    
    # optionally read a segmask
    segmask = None
    if segmask_filename is not None:
        segmask = BinaryImage.open(segmask_filename)
    
    # create state
    rgbd_im = RgbdImage.from_color_and_depth(color_im, depth_im)
    state = RgbdImageState(rgbd_im, camera_intr, segmask=segmask)

    # init policy
    policy = CrossEntropyRobustGraspingPolicy(policy_config)
    policy_start = time.time()
    action = policy(state)
    logging.info('Planning took %.3f sec' %(time.time() - policy_start))

    # vis final grasp
    if policy_config['vis']['final_grasp']:
        vis.figure(size=(10,10))
        vis.imshow(rgbd_im.depth, vmin=0.6, vmax=0.9)
        vis.grasp(action.grasp, scale=1.5, show_center=False, show_axis=True)
        vis.title('Planned grasp on depth (Q=%.3f)' %(action.q_value))
        vis.show()
