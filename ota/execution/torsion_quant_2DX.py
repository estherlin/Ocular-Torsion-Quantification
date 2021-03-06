import numpy as np

from ota.video import video as vid
from ota import presets
from ota.torsion import xcorr2d
from ota.pupil import pupil
from ota.iris import iris, eyelid_removal
from ota import presets as pre
from tqdm import tqdm
import matplotlib.pylab as plt

# TODO: Add to docs
def quantify_torsion(
    WINDOW_RADIUS,
    RESOLUTION,
    torsion_mode,
    transform_mode,
    video,
    start_frame,
    reference_frame,
    end_frame,
    pupil_list,
    blink_list,
    threshold,
    alternate,
    WINDOW_THETA = None,
    SEGMENT_THETA = None,
    upper_iris = None,
    lower_iris = None,
    feature_coords = None):

    '''
    Utilizes the 2D cross correlation algorithm xcorr2d to measure and return torsion using the settings given.

    Inputs:
        WINDOW_RADIUS:
            Integer
            Mandatory input which sets the radial thickness of the iris transform.

        RESOLUTION:
            Double
            Mandatory input with sets the upsampling factor or the interpolation resolution depending on settings below.

        torsion_mode:
            String
            Mandatory input which determines whether interpolation or upsampling is used.
            if torsion_mode = 'interp', then interpolation is used and RESOLUTION is assumed to be interpolation resolution. Consequently an upsampling factor of 1 is used in the transform.
            if torsion_mode = 'upsample', then upsampling is used and RESOLUTION is assumed to be the upsampling factor.

        transform_mode:
            String
            Mandatory input which determines whether a subset of the iris is used or the full iris is used during correlation.
            if transform_mode = 'subset', a subset of the iris is used.
            if transform_mode = 'full', the full iris us used.

        video:
            Video object
            Mandatory input

        start_frame:
            Integer
            Mandatory input which is the index of the reference frame.

        end_frame:
            Integer
            Mandatory input which is the index of the last frame to analyze.

        pupil_list:
            dictionary of pupil objects
            key: (int) video frame
            value: pupil object

        blink_list:
            dictionary of whether or not a frame captures a blink
            key: (int) video frame
            value: 1 - blink
                   0 - no blink
                   None - None

        WINDOW_THETA:
            Integer
            Angle bounds above/below the feature that define the portion of the iris that is to be included in the reference iris window. This window should be smaller than the segment.
            Mandatory input if transform_mode = 'subset'.

        SEGMENT_THETA:
            Integer
            Angle bounds above/below the feature that define the portion of the iris that is to be included in each segment, for which the window is to be located in.
            Mandatory input if transform_mode = 'subset'.

        upper_iris_occ:
            dictionary, {'c': column index, 'r': row index}
            Holds the [row,column] coordinates of the upper boundary of the iris that is not occluded by eyelids or eyelashes.

        lower_iris_occ:
            dictionary, {'c': column index, 'r': row index}
            Holds the [row,column] coordinates of the lower boundary of the iris that is not occluded by eyelids or eyelashes.

        feature_coords:
            dictionary, {'c': column index, 'r': row index}
            Holds the dictionary of feature coordinates tracked during subset correlation.
            Mandatory input if transform_mode = 'subset'.

    Returns:

        torsion:
            Dictionary
            key = frame number
            value = rotation from reference frame
        torsion_deriative:
            Dictionary
            key = frame number
            value = rotation from previous frame
    '''

    upsample_factor = 1
    noise_replace = False

    if torsion_mode == 'interp':
        pass
    elif torsion_mode == 'upsample':
        upsample_factor = RESOLUTION

    if transform_mode == 'full':
        if upper_iris and lower_iris:
            noise_replace = True
        start = 0
        reference_bounds = (0, 360) # what are these? 360 degrees?
        comparison_bounds = (0, 360)

    elif transform_mode == 'subset':
        feature_r, feature_theta = iris.get_polar_coord(feature_coords['r'], feature_coords['c'], pupil_list[start_frame])
        reference_bounds = (feature_theta - WINDOW_THETA, feature_theta + WINDOW_THETA)
        comparison_bounds = (feature_theta - SEGMENT_THETA, feature_theta + SEGMENT_THETA)
        start = int((SEGMENT_THETA - WINDOW_THETA)/upsample_factor)

    # TODO: This is actually such a dumb way, copying and pasting code.
    elif transform_mode == 'alternate':
        # Get the aspects as if you were doing a full iris analysis
        if upper_iris and lower_iris:
            noise_replace = True
        start = 0
        reference_bounds = (0, 360) # what are these? 360 degrees?
        comparison_bounds = (0, 360)

        # Get the aspects as if you are doing the subset
        feature_r, feature_theta = iris.get_polar_coord(feature_coords['r'], feature_coords['c'], pupil_list[start_frame])
        reference_bounds_sr = (feature_theta - WINDOW_THETA, feature_theta + WINDOW_THETA)
        comparison_bounds_sr = (feature_theta - SEGMENT_THETA, feature_theta + SEGMENT_THETA)
        start_sr = int((SEGMENT_THETA - WINDOW_THETA)/upsample_factor)

    # get the reference window from the first frame of the video
    # this will be the base for all torsion ie. all rotation is relative to this window
    if start_frame == reference_frame:
        if alternate:
            first_window_sr = iris.iris_transform(video[start_frame],
                                                  pupil_list[start_frame],
                                                  WINDOW_RADIUS,
                                                  theta_resolution=upsample_factor,
                                                  theta_window=reference_bounds_sr)
        first_window = iris.iris_transform(video[start_frame],
                                           pupil_list[start_frame],
                                           WINDOW_RADIUS,
                                           theta_resolution = upsample_factor,
                                           theta_window = reference_bounds)
    else:
        ref_pupil = pupil.Pupil(video[reference_frame], threshold)
        if alternate:
            first_window_sr = iris.iris_transform(video[reference_frame],
                                                  ref_pupil,
                                                  WINDOW_RADIUS,
                                                  theta_resolution=upsample_factor,
                                                  theta_window=reference_bounds_sr)
        first_window = iris.iris_transform(video[reference_frame], ref_pupil, WINDOW_RADIUS, theta_resolution = upsample_factor, theta_window = reference_bounds)

    # TODO: If noise replace is selected, cannot select segment removal
    if noise_replace:

        # transform (column,row) into (theta,r) space about pupil centre
        # get the boundaries of usable iris in polar
        upper_iris_r, upper_iris_theta = iris.get_polar_coord(upper_iris['r'], upper_iris['c'], pupil_list[start_frame])
        lower_iris_r, lower_iris_theta = iris.get_polar_coord(lower_iris['r'], lower_iris['c'], pupil_list[start_frame])

        # mirrors the upper angular boundary across the vertical axis
        upper_occlusion_theta = (90 - np.absolute(upper_iris_theta - 90), 90 + np.absolute(upper_iris_theta - 90))

        # mirrors the lower angular boundary across the vertical axis
        # deal with the branch cut at 270
        if lower_iris_theta < 0:
            lower_occlusion_theta = (-90 - np.absolute(lower_iris_theta + 90), -90 + np.absolute(lower_iris_theta + 90))
        else:
            lower_occlusion_theta = (-90 - np.absolute(lower_iris_theta - 270), -90 + np.absolute(lower_iris_theta - 270))

        # replace occluded sections with noise
        first_window = eyelid_removal.noise_replace(first_window, upper_occlusion_theta, lower_occlusion_theta)

    # Nani is this? Why is it not with the other stuff above?
    if transform_mode == 'full' or transform_mode == 'alternate':
        # extend iris window
        first_window = eyelid_removal.iris_extension(first_window, theta_resolution = upsample_factor, lower_theta = -pre.MAX_ANGLE, upper_theta=pre.MAX_ANGLE)

    # TODO: Add a button to show iris segments

    torsion = {}
    torsion_derivative = {}
    # find torsion between start_frame+1:last_frame
    for i, frame in tqdm(enumerate(video[start_frame:end_frame])):
        frame_loc = i + start_frame
        # check if a pupil exists, or if there is a blink
        if not pupil_list[frame_loc] or blink_list[frame_loc] is None:
            # if there is no pupil, torsion cannot be calculated
            torsion[frame_loc] = None
            torsion_derivative[frame_loc] = None
            print('WARNING: No pupil in frame: %d \n Torsion cannot be calculated' % (frame_loc))
        else:
            # unwrap the iris (convert into polar)
            #current_frame = iris.iris_transform(frame, pupil_list[frame_loc], WINDOW_RADIUS, theta_resolution = upsample_factor, theta_window = comparison_bounds)

            # TODO: add when eyelid is not found???
            if alternate and blink_list[frame_loc] == 1:
                # TODO: Need to add detection, this method of checking if 0 exists is too much of a gong show
                current_frame = iris.iris_transform(frame, pupil_list[frame_loc],
                                                    WINDOW_RADIUS,
                                                    theta_resolution=upsample_factor,
                                                    theta_window=comparison_bounds_sr)
                # get the degree of rotation of the current frame based on reference frame
                deg = xcorr2d.xcorr2d(current_frame,
                                      first_window_sr,
                                      start=start_sr,
                                      prev_deg=None,
                                      torsion_mode=torsion_mode,
                                      resolution=RESOLUTION,
                                      threshold=0,
                                      max_angle=pre.MAX_ANGLE)
                if i > 0:
                    # Calculate torsion based off of previous window
                    previous_window_sr = iris.iris_transform(video[frame_loc-1],
                                                          pupil_list[frame_loc-1],
                                                          WINDOW_RADIUS,
                                                          theta_resolution=upsample_factor,
                                                          theta_window=reference_bounds_sr)
                    # get the degree of rotation of the current frame based on previous frame
                    previous_deg = xcorr2d.xcorr2d(current_frame,
                                                  previous_window_sr,
                                                  start=start_sr,
                                                  prev_deg=None,
                                                  torsion_mode=torsion_mode,
                                                  resolution=RESOLUTION,
                                                  threshold=0,
                                                  max_angle=pre.MAX_ANGLE)
                else:
                    previous_deg = None
            else:
                current_frame = iris.iris_transform(frame, pupil_list[frame_loc], WINDOW_RADIUS,
                                                    theta_resolution=upsample_factor, theta_window=comparison_bounds)
                # get the degree of rotation of the current frame based on reference frame
                deg = xcorr2d.xcorr2d(current_frame, first_window, start=start, prev_deg=None,
                                      torsion_mode=torsion_mode, resolution=RESOLUTION, threshold=0,
                                      max_angle=pre.MAX_ANGLE)
                if i > 0:
                    # get the previous frame
                    previous_window = iris.iris_transform(video[frame_loc-1],
                                                       pupil_list[frame_loc-1],
                                                       WINDOW_RADIUS,
                                                       theta_resolution=upsample_factor,
                                                       theta_window=reference_bounds)
                    previous_window = eyelid_removal.iris_extension(previous_window, theta_resolution=upsample_factor,
                                                                 lower_theta=-pre.MAX_ANGLE, upper_theta=pre.MAX_ANGLE)

                    # get the degree of rotation of the current frame based on previous frame
                    previous_deg = xcorr2d.xcorr2d(current_frame, previous_window, start=start, prev_deg=None,
                                          torsion_mode=torsion_mode, resolution=RESOLUTION, threshold=0,
                                          max_angle=pre.MAX_ANGLE)
                else:
                    previous_deg = None
            # save the torsion3
            torsion[frame_loc] = deg
            torsion_derivative[frame_loc] = previous_deg

            '''
            # Get the change in angle compared to previous frame
            if frame_loc != start_frame :
                if deg is None or torsion[frame_loc-1] is None:
                    torsion_derivative[frame_loc] = None
                else:
                    torsion_derivative[frame_loc] = deg - torsion[frame_loc-1]
            else:
                torsion_derivative[frame_loc] = None
            '''

    return torsion, torsion_derivative















# import cv2
# import numpy as np
#
# from ota import presets
# from ota.torsion import xcorr2d
# from ota.video import video as vid
# from ota.pupil import pupil
# from ota.iris import iris, eyelid_removal
# from ota.data import data as dat
#
# def quantify_torsion(gui, controller):
#     # PRESETS
#     WINDOW_RADIUS = gui.radial_thickness.get() # how thick the window is in the radial direction
#     THETA_RESOLUTION = gui.theta_resolution.get() # sampling resolution in transform
#
#     # get the video from the GUI
#     video = controller.video
#
#     # store the starting and ending frame location
#     start_frame = controller.start_frame.get()
#     last_frame = controller.end_frame.get()
#
#     # dictionaries to store results
#     pupil_list = controller.pupil_list
#     # torsion
#     torsion = {}
#     feature_location_list = {} # (column,row) coordinates of maximum correlation
#
#     # try to find pupil at index start_frame
#
#     # get the user inputted bounds for extreme limits of usable iris
#     upper_iris = gui.upper_iris_occ
#     lower_iris = gui.lower_iris_occ
#
#     # transform (colum,row) into (theta,r) space about pupil centre
#     # get the boundaries of usable iris in polar
#     upper_iris_r, upper_iris_theta = iris.get_polar_coord(upper_iris['r'], upper_iris['c'], pupil_list[start_frame])
#     lower_iris_r, lower_iris_theta = iris.get_polar_coord(lower_iris['r'], lower_iris['c'], pupil_list[start_frame])
#
#     # mirrors the upper angular boundary across the vertical axis
#     upper_occlusion_theta = (90 - np.absolute(upper_iris_theta - 90), 90 + np.absolute(upper_iris_theta - 90))
#
#     # mirrors the lower angular boundary across the vertical axis
#     # deal with the branch cut at 270
#     if lower_iris_theta < 0:
#         lower_occlusion_theta = (-90 - np.absolute(lower_iris_theta + 90), -90 + np.absolute(lower_iris_theta + 90))
#     else:
#         lower_occlusion_theta = (-90 - np.absolute(lower_iris_theta - 270), -90 + np.absolute(lower_iris_theta - 270))
#
#     # get the reference window from the first frame of the video
#     # this will be the base for all torsion ie. all rotation is relative to this window
#     first_window = iris.iris_transform(video[start_frame], pupil_list[start_frame], WINDOW_RADIUS, theta_resolution = THETA_RESOLUTION, theta_window = (0, 360))
#
#     # replace occluded sections with noise
#     first_window = eyelid_removal.noise_replace(first_window, upper_occlusion_theta, lower_occlusion_theta)
#
#     # extend iris window
#     first_window = eyelid_removal.iris_extension(current_frame, theta_resolution = THETA_RESOLUTION, lower_theta = -MAX_ANGLE, upper_theta=MAX_ANGLE)
#
#
#     # find torsion between start_frame+1:last_frame
#     for i, frame in enumerate(video[start_frame:last_frame]):
#         frame_loc = i + start_frame
#         # check if a pupil exists
#         if not pupil_list[frame_loc]:
#             # if there is no pupil, torsion cannot be calculated
#             torsion[frame_loc] = None
#             print('WARNING: No pupil in frame: %d \n Torsion cannot be calculated' % (frame_loc))
#         else:
#             # unwrap the iris (convert into polar)
#             current_frame = iris.iris_transform(frame, pupil_list[frame_loc], WINDOW_RADIUS, theta_resolution = THETA_RESOLUTION, theta_window=theta_window)
#             # get the degree of rotation of the current frame
#             deg = xcorr2d.xcorr2d(current_frame, first_window, shift_first, prev_deg=None, mode='upsample', resolution=THETA_RESOLUTION, threshold=0, max_angle=MAX_ANGLE)
#             # save the torsion
#             torsion[frame_loc] = deg
#
#     # Create dictionary of time values corresponding to the frames in frame_index_list
#
#     # Initialize data object
#     # TODO add video parameters to metadata as dictionary
#     data = dat.Data()
#
#     # set the data object with the results
#     data.set(
#         start_frame = start_frame,
#         torsion = torsion,
#         metadata = {
#             'VIDEO_PATH': controller.video_path,
#             'VIDEO_FPS': video.fps
#         }
#     )
#     # data.frame_index_list = frame_index_list
#     # data.frame_time = frame_time
#     # data.torsion = torsion
#     # data.video_str = settings.VIDEO_PATH
#     # data.video_fps = video.fps
#     # TODO
#
#     return data
