"""Reusable pixel-coordinate maps; every crop still samples its current image.
Rounding follows OpenCV 3.1 imgwarp.cpp's fixed-point affine interpolation grid:
https://raw.githubusercontent.com/opencv/opencv/3.1.0/modules/imgproc/src/imgwarp.cpp
"""
import cv2
import numpy as np


def affine_maps_224(transform):
    matrix=cv2.invertAffineTransform((transform*224).astype(np.float64))
    axis=np.arange(224,dtype=np.float64)
    coords=[]
    for row in matrix:
        horizontal=np.rint(row[0]*axis*1024).astype(np.int32)
        vertical=np.rint((row[1]*axis+row[2])*1024).astype(np.int32)
        coords.append((vertical[:,None]+horizontal[None,:]+16)>>5)
    x,y=coords
    integer=np.clip(np.stack((x>>5,y>>5),axis=2),-32768,32767).astype(np.int16)
    fraction=(((y&31)<<5)+(x&31)).astype(np.uint16)
    return integer,fraction
