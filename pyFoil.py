"""
pyFoil
--------

Contains a class for creating, modifying and exporting airfoils.


Questions:
- Modes?!? Should we provide any functionality for that?
- Do we want twist in deg or rad?
"""
from __future__ import print_function
from __future__ import division

import warnings
import numpy as np
import pyspline as pySpline
from scipy.optimize import fsolve, brentq
from pyfoil import sampling
import os
import pygeo
import matplotlib.pyplot as plt

class Error(Exception):
    """
    Format the error message in a box to make it clear this
    was a explicitly raised exception.
    """
    def __init__(self, message):
        msg = '\n+' + '-'*78 + '+' + '\n' + '| pyFoil Error: '
        i = 17
        for word in message.split():
            if len(word) + i + 1 > 78: # Finish line and start new one
                msg += ' '*(78-i)+'|\n| ' + word + ' '
                i = 1 + len(word)+1
            else:
                msg += word + ' '
                i += len(word)+1
        msg += ' '*(78-i) + '|\n' + '+'+'-'*78+'+'+'\n'
        print(msg)
        Exception.__init__()


def _readCoordFile(filename, headerlines=0):
    """ Load the airfoil file"""
    f = open(filename, 'r')
    line  = f.readline() # Read (and ignore) the first line
    r = []
    try:
        r.append([float(s) for s in line.split()])
    except:
        r = []

    while True:
        line = f.readline()
        if not line:
            break # end of file
        if line.isspace():
            break # blank line
        r.append([float(s) for s in line.split()])

    X = np.array(r)
    return X

def _cleanup_pts(X):
    '''
    DO NOT USE THIS, IT CURRENTLY DOES NOT WORK
    For now this just removes points which are too close together. In the future we may need to add further
    functionalities. This is just a generic cleanup tool which is called as part of preprocessing.
    '''
    uniquePts, link = pygeo.geo_utils.pointReduce(X, nodeTol=1e-12)
    nUnique = len(uniquePts)

    # Create the mask for the unique data:
    mask = np.zeros(nUnique, 'intc')
    for i in range(len(link)):
        mask[link[i]] = i

    # De-duplicate the data
    data = X[mask, :]
    return data


def _reorder(coords):
    '''
    This function serves two purposes. First, it makes sure the points are oriented in counter-clockwise
    direction. Second, it makes sure the points start at the TE.
    '''
    pass

def _genNACACoords(name):
    pass

def _cleanup_TE(X,tol):
    TE = np.mean(X[[-1,0],:],axis=0)
    return X, TE

def _writePlot3D(filename,x,y):
    filename += '.fmt'
    f = open(filename, 'w')
    f.write('1\n')
    f.write('%d %d %d\n'%(len(x), 2, 1))
    for iDim in range(3):
        for j in range(2):
            for i in range(len(x)):
                if iDim == 0:
                    f.write('%g\n'%x[i])
                elif iDim == 1:
                    f.write('%g\n'%y[i])
                else:
                    f.write('%g\n'%(float(j)))
    f.close()

def _writeDat(filename,x,y):
    filename += '.dat'
    f = open(filename, 'w')

    for i in range(0, len(x)):
        f.write(str(round(x[i], 12)) + "\t\t"
                + str(round(y[i], 12)) + '\n'
                )
    f.close()

def _translateCoords(X,dX):
    """shifts the input coordinates by dx and dy"""
    return X + dX


def _rotateCoords(X, angle, origin):
    """retruns the coordinates rotated about the specified origin by angle (in deg)"""
    c, s = np.cos(angle), np.sin(angle)
    R = np.array(((c,-s), (s, c)))
    shifted_X = X - origin
    shifted_rotated_X = np.dot(shifted_X,R.T)
    rotated_X = shifted_rotated_X + origin
    return rotated_X


def _scaleCoords(X, scale, origin):
    """scales the coordinates in both dimension by the scaling factor"""
    shifted_X = X - origin
    shifted_scaled_X = shifted_X * scale
    scaled_X = shifted_scaled_X + origin
    return scaled_X

def checkCellRatio(X,ratio_tol=1.2):
    X_diff = X[1:,:] - X[:-1,:]
    cell_size = np.sqrt(X_diff[:,0]**2 + X_diff[:,1]**2)
    crit_cell_size = np.flatnonzero(cell_size<1e-10)
    for i in crit_cell_size:
        print("critical I", i)
    cell_ratio = cell_size[1:]/cell_size[:-1]
    exc = np.flatnonzero(cell_ratio > ratio_tol)

    if exc.size > 0:
        print('WARNING: There are ', exc.size, ' elements which exceed '
                                               'suggested cell ratio: ',
              exc)

    max_cell_ratio = np.max(cell_ratio, 0)
    avg_cell_ratio = np.average(cell_ratio, 0)
    print('Max cell ratio: ', max_cell_ratio)
    print('Average cell ratio', avg_cell_ratio)

    return cell_ratio, max_cell_ratio, avg_cell_ratio, exc


class Airfoil(object):
    """
    A class for manipulating airfoil geometry.

    Create an instance of an airfoil. There are two ways of instantiating
    this object: by passing in a set of points, or by reading in a coordinate
    file. The points need not start at the TE nor go ccw around the airfoil,
    but they must be ordered such that they form a continuous airfoil surface.
    If they are not (due to MPI or otherwise), use the order() function within
    tecplotFileParser.

    Parameters
    ----------
    coords : ndarray[N,3]
        Full array of airfoil coordinates

    some additional option:

    k : int
        Order of the spline
    nCtl : int
        Number of control points
    name : str
        The name of the airfoil.

    def recompute(self):
        if self.nCtl is None:
            self.spline = Curve(X=self.X,k=self.k)
        else:
            self.spline = Curve(X=self.X,k=self.k,nCtl=self.nCtl)

    Examples
    --------
    The general sequence of operations for using pyfoil is as follows::
      >>> from pygeo import *
    """
    def __init__(self,coords, spline_order=3, normalize=False): #, **kwargs):

        self.spline_order = spline_order
        # for arg in kwargs.keys():
        #     setattr(self, arg, kwargs[arg])

        ## initialize geometric information
        self.recompute(coords)

        if normalize:
            self.normalize()

    def recompute(self, coords):
        self.spline = pySpline.Curve(X=coords,k=self.spline_order)

        self.TE = self.getTE()
        self.LE, self.s_LE  = self.getLE()
        self.chord = self.getChord()
        self.twist =  self.getTwist()


## Geometry Information

    def getTE(self):
        TE = (self.spline.getValue(0) + self.spline.getValue(1))/2
        return TE

    def getLE(self):
        '''
        Calculates the leading edge point on the spline, which is defined as the point furthest away from the TE. The spline is assumed to start at the TE. The routine uses a root-finding algorithm to compute the LE.
        Let the TE be at point :math:`x_0, y_0`, then the Euclidean distance between the TE and any point on the airfoil spline is :math:`\ell(s) = \sqrt{\Delta x^2 + \Delta y^2}`, where :math:`\Delta x = x(s)-x_0` and :math:`\Delta y = y(s)-y_0`. We know near the LE, this quantity is concave. Therefore, to find its maximum, we differentiate and use a root-finding algorithm on its derivative.
        :math:`\\frac{\mathrm{d}\ell}{\mathrm{d}s} = \\frac{\Delta x\\frac{\mathrm{d}x}{\mathrm{d}s} + \Delta y\\frac{\mathrm{d}y}{\mathrm{d}s}}{\ell}`

        The function dellds computes the quantity :math:`\Delta x\\frac{\mathrm{d}x}{\mathrm{d}s} + \Delta y\\frac{\mathrm{d}y}{\mathrm{d}s}` which is then used by brentq to find its root, with an initial bracket at [0.3, 0.7].

        TODO
        Use a Newton solver, employing 2nd derivative information and use 0.5 as the initial guess.
        '''

        def dellds(s,spline,TE):
            pt = spline.getValue(s)
            deriv = spline.getDerivative(s)
            dx = pt[0] - TE[0]
            dy = pt[1] - TE[1]
            return dx * deriv[0] + dy * deriv[1]

        s_LE = brentq(dellds,0.3,0.7,args=(self.spline,self.TE))
        LE = self.spline.getValue(s_LE)

        return LE, s_LE

    def getTwist(self):
        chord_vec = (self.TE - self.LE)
        twist = np.arctan2(chord_vec[1], chord_vec[0]) * 180 / np.pi
        # twist = np.arccos(normalized_chord.dot(np.array([1., 0.]))) * np.sign(normalized_chord[1])
        return twist

    def getChord(self):
        chord = np.linalg.norm(self.TE - self.LE)
        return chord

    def getPts(self):
        """alias for returning the points that make the airfoil spline"""
        return self.spline.X

  ##TODO write tests

    def getTEThickness(self):
        top = self.spline.getValue(0)
        bottom = self.spline.getValue(1)
        TE_thickness = np.array([top[0] + bottom[0], top[1] - bottom[1]])/2
        return TE_thickness


    def getLERadius(self):
        '''
        Computes the leading edge radius of the airfoil. Note that this is heavily dependent on the initialization points, as well as the spline order/smoothing.
        '''
        # if self.s_LE is None:
        #     self.getLE()

        first = self.spline.getDerivative(self.s_LE)
        second = self.spline.getSecondDerivative(self.s_LE)
        LE_rad = np.linalg.norm(first)**3 / np.linalg.norm(first[0]*second[1] - first[1]*second[0])
        return LE_rad

    def getCTDistribution(self):
        '''
        Return the coordinates of the camber points, as well as the thicknesses (this is with british convention).
        '''
        self._splitAirfoil()

        num_chord_pts = 100

        # Compute the chord
        chord_pts = np.vstack([self.LE,self.TE])
        chord = pySpline.line(chord_pts)

        cos_sampling = np.linspace(0,1,num_chord_pts+1,endpoint=False)[1:]
        #cos_sampling = smp.conical(num_chord_pts+2,coeff=1)[1:-1]

        chord_pts = chord.getValue(cos_sampling)
        camber_pts = np.zeros((num_chord_pts,2))
        thickness_pts = np.zeros((num_chord_pts,2))
        for j in range(chord_pts.shape[0]):
            direction = np.array([np.cos(np.pi/2 - self.twist), np.sin(np.pi/2 - self.twist)])
            direction = direction/np.linalg.norm(direction)
            top = chord_pts[j,:] + 0.5*self.chord * direction
            bottom = chord_pts[j,:] - 0.5*self.chord * direction
            temp = np.vstack((top,bottom))
            normal = pySpline.line(temp)
            s_top,t_top,D = self.top.projectCurve(normal,nIter=5000,eps=1e-16)
            s_bottom,t_bottom,D = self.bottom.projectCurve(normal,nIter=5000,eps=1e-16)
            intersect_top = self.top.getValue(s_top)
            intersect_bottom = self.bottom.getValue(s_bottom)

            # plt.plot(temp[:,0],temp[:,1],'-og')
            # plt.plot(intersect_top[0],intersect_top[1],'or')
            # plt.plot(intersect_bottom[0],intersect_bottom[1],'ob')

            camber_pts[j,:] = (intersect_top + intersect_bottom)/2
            thickness_pts[j,0] = (intersect_top[0] + intersect_bottom[0])/2
            thickness_pts[j,1] = (intersect_top[1] - intersect_bottom[1])/2
        # plt.plot(camber_pts[:,0],camber_pts[:,1],'ok')

        self.camber_pts = np.vstack((self.LE,camber_pts,self.TE)) # Add TE and LE to the camber points.
        self.getTEThickness()
        self.thickness_pts = np.vstack((np.array((self.LE[0],0)),thickness_pts,self.TE_thickness))

        return self.camber_pts, self.thickness_pts

    def getTEAngle(self):
        '''
        Computes the trailing edge angle of the airfoil. We assume here that the spline goes from top to bottom, and that s=0 and s=1 corresponds to the
        top and bottom trailing edge points. Whether or not the airfoil is closed is irrelevant.
        '''
        top = self.spline.getDerivative(0)
        top = top/np.linalg.norm(top)
        bottom = self.spline.getDerivative(1)
        bottom = bottom/np.linalg.norm(bottom)
        # print(np.dot(top,bottom))
        TE_angle = np.pi - np.arccos(np.dot(top,bottom))
        return np.rad2deg(self.TE_angle)

  ##TODO write
    def getMaxThickness(self,method):
        '''
        method : str
            Can be one of 'british', 'american', or 'projected'
        '''
        pass

    def getMaxCamber(self):
        pass


    def isReflex(self):
        '''
        An airfoil is reflex if the derivative of the camber line at the trailing edge is positive.
        #TODO this has not been tested
        '''
        if self.camber is None:
            self.getCamber()

        if self.camber.getDerivative(1)[1] > 0:
            return True
        else:
            return False

    def isSymmetric(self, tol=1e-6):
        # test camber and thickness dist
        pass




## Geometry Modification

    def rotate(self,angle,origin=np.zeros(2)):
        new_coords = _rotateCoords(self.spline.X,np.deg2rad(angle),origin)

        # reset initialize with the new set of coordinates
        self.__init__(new_coords, spline_order=self.spline.k)
        # self.update(new_coords, spline_order=self.spline.k)

    def derotate(self,origin=np.zeros(2)):
        self.rotate(-1.0*self.twist,origin=origin)


    def scale(self,factor,origin=np.zeros(2)):
        new_coords = _scaleCoords(self.spline.X,factor,origin)
        self.__init__(new_coords, spline_order=self.spline.k)

        # if self.chord is not None:
        #     self.chord *= factor

    def normalizeChord(self,origin=np.zeros(2)):
        if self.spline is None:
            self.recompute()
        elif self.chord == 1:
            return
        self.scale(1.0/self.chord,origin=origin)

    def translate(self,delta):
        sample_pts = self._getDefaultSampling()
        self.X = _translateCoords(sample_pts,delta)
        self.recompute()
        if self.LE is not None:
            self.LE += delta

    def center(self):
        if self.spline is None:
            self.recompute()
        if self.LE is None:
            self.getChord()
        elif np.all(self.LE == np.zeros(2)):
            return
        self.translate(-1.0*self.LE)

    def splitAirfoil(self):
        # if self.s_LE is None:
            # self.getLE()
        top, bottom = self.spline.splitCurve(self.s_LE)
        return top, bottom

    def normalizeAirfoil(self, derotate=True, normalize=True, center=True):
        if derotate or normalize or center:
            origin = np.zeros(2)
            sample_pts = self.spline.X


            # Order of operation here is important, even though all three operations are linear, because
            # we rotate about the origin for simplicity.
            if center:
                delta = -1.0*self.LE
                sample_pts = _translateCoords(sample_pts,delta)
            if derotate:
                angle = -1.0*self.twist
                sample_pts = _rotateCoords(sample_pts,angle,origin)
            if normalize:
                factor = 1.0/self.chord
                sample_pts = _scaleCoords(sample_pts,factor,origin)


            self.recompute(sample_pts)

    def thickenTE(self):
        pass

    def sharpenTE(self):
        pass

    def roundTE(self):
        pass

    def _removeTEPts(self):
        pass

## Sampling
    def getSampledPts(self, nPts, spacingFunc=sampling.polynomial, func_args={}, nTEPts=0):
        '''
        This function defines the point sampling along airfoil surface.
        An example dictionary is reported below:

        >>> sample_dict = {'distribution' : 'conical',
        >>>        'coeff' : 1,
        >>>        'npts' : 50,
        >>>        'bad_edge': False}

        The point distribution currently implemented are:
            - *Cosine*:
            - *Conical*:
            - *Parabolic*:
            - *Polynomial*:

        :param upper: dictionary
                Upper surface sampling dictionary
        :param lower: dictionary
                Lower surface sampling dictionary
        :param npts_TE: float
                Number of points along the **blunt** trailing edge
        :return: Coordinates array, anticlockwise, from trailing edge
        '''
        s = sampling.joinedSpacing(nPts, spacingFunc=spacingFunc, func_args=func_args)
        coords = self.spline.getValue(s)

        if nTEPts:
            coords_TE = np.zeros((nTEPts, coords.shape[1]))
            for idim in range(coords.shape[1]):
                coords_TE[:, idim] = np.linspace(self.spline.getValue(1)[idim], self.spline.getValue(0)[idim], nTEPts)
            coords = np.vstack((coords,coords_TE))


        ##TODO
            # - reintagrate cell check

        # if cell_check is True:
        #     checkCellRatio(coords)
        # self.sampled_X = coords

        # # To be updated later on if new point add/remove operations are included
        # # x.size-1 because of the last point added for "closure"
        # if single_distr is True and x.size-1 != points_init:
        #     print('WARNING: The number of sampling points has been changed \n'
        #             '\t\tCurrent points number: %i' % (x.size))

        return coords


## Output
    def writeCoords(self, coords,  filename, fmt='plot3d'):
        '''
        We have to discuss which types of printfiles we want to get and how
        to handle them (does this class print the last "sampled" x,y or do
        we want more options?)
        '''

        if fmt == 'plot3d':
            _writePlot3D(filename, coords[:,0], coords[:,1])
        elif fmt == 'dat':
            _writeDat(filename, coords[:,0], coords[:,1])
        else:
            raise Error(fmt + ' is not a supported output format!')

## Utils
# maybe remove and put into a separate location?
    def plot(self):
        import matplotlib.pyplot as plt
        fig = plt.figure()
        # pts = self._getDefaultSampling(npts=1000)
        plt.plot(self.spline.X[:,0],self.spline.X[:,1],'-r')
        plt.axis('equal')
        # if self.sampled_X is not None:
        plt.plot(self.spline.X[:,0],self.spline.X[:,1],'o')


        ##TODO
        # if self.camber_pts is not None:
        #     fig2 = plt.figure()
        #     plt.plot(self.camber_pts[:,0],self.camber_pts[:,1],'-og',label='camber')
        #     plt.plot(self.thickness_pts[:,0],self.thickness_pts[:,1],'-ob',label='thickness')
        #     plt.legend(loc='best')
        #     plt.title(self.name)
        return fig