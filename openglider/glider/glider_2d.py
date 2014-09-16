from __future__ import division
import copy

import scipy.interpolate
import numpy
from openglider.vector import norm, normalize, rotation_2d, mirror2D_x
from openglider.utils.bezier import BezierCurve, SymmetricBezier
from openglider.utils import sign
from openglider.airfoil import Profile2D


class Glider_2D(object):
    """
        a glider 2D object used for gui inputs
    """

    def __init__(self,
                 front=None,    back=None,      cell_dist=None,
                 arc=None,      aoa=None,       cell_num=21,
                 profiles=None, balls=None,      parametric=False):
        self.parametric = parametric    #set to False if you change glider 3d manually
        self.cell_num = cell_num  # updates cell pos
        self.front = front or SymmetricBezier()
        self.back = back or SymmetricBezier()
        self.cell_dist = cell_dist or BezierCurve()
        self.arc = arc or BezierCurve()
        self.aoa = aoa or BezierCurve()
        self.profiles = profiles or []
        self.balls = balls or []

    def __json__(self):
        return {
            "front": self.front,
            "back": self.back,
            "cell_dist": self.cell_dist
        }

    def arc_pos(self, num=50):
        # calculating the transformed arc
        dist = numpy.array(self.cell_dist_interpolation).T[0] #array of scalars
        arc_arr = [self.arc(0.5)]
        length_arr = [0.]
        for i in numpy.linspace(0.5 + 1 / num, 1, num):
            arc_arr.append(self.arc(i))
            length_arr.append(length_arr[-1] + norm(arc_arr[-2] - arc_arr[-1]))
        int_func = scipy.interpolate.interp1d(length_arr, numpy.array(arc_arr).T)
        normed_dist = [i / dist[-1] * length_arr[-1] for i in dist]
        z_pos = [int_func(i)[1] for i in normed_dist]
        y_pos_temp = [int_func(i)[0] for i in normed_dist]
        y_pos = [0.] if dist[0] == 0 else [y_pos_temp[0]]
        for i, _ in enumerate(z_pos[1:]):
            direction = sign (y_pos_temp[i + 1] - y_pos_temp[i]) #TODO: replace with a better methode
            y_pos.append(y_pos[-1] + direction * numpy.sqrt((normed_dist[i+1] - normed_dist[i]) ** 2 - (z_pos[i + 1] - z_pos[i]) ** 2))
        # return the list of the arc positions and a scale factor to transform back to the real span
        return numpy.array(zip(y_pos, z_pos)).tolist()


    def arc_pos_angle(self, num=50):
        arc_pos = self.arc_pos(num=num)
        arc_pos_copy = copy.copy(arc_pos)
        dist = numpy.array(self.cell_dist_interpolation).T[0]
        # calculating the rotation of the ribs
        if arc_pos[0][0] == 0.:
            arc_pos = [[-arc_pos[1][0], arc_pos[1][1]]] + arc_pos
        else:
            arc_pos = [[0., arc_pos[0][1]]] + arc_pos
        arc_pos = numpy.array(arc_pos)
        arc_angle = []
        rot = rotation_2d(-numpy.pi / 2)
        for i, pos in enumerate(arc_pos[1:-1]):
            direction = rot.dot(normalize(pos - arc_pos[i])) + rot.dot(normalize(arc_pos[i + 2] - pos))
            arc_angle.append(numpy.arctan2(*direction))
        temp = arc_pos[-1] - arc_pos[-2]
        arc_angle.append(- numpy.arctan2(temp[1], temp[0]))

        # transforming the start_pos back to the original distribution
        arc_pos = numpy.array(arc_pos_copy)
        if arc_pos_copy[0][0] != 0.:
            arc_pos_copy = [[0., arc_pos_copy[0][1]]] + arc_pos_copy
        arc_pos_copy = numpy.array(arc_pos_copy)
        arc_normed_length = 0.
        # recalc actuall length
        for i, pos in enumerate(arc_pos_copy[1:]):
            arc_normed_length += norm(arc_pos_copy[i] - pos)
        trans = - numpy.array(arc_pos_copy[0])
        scal = dist[-1] / arc_normed_length
        # first translate the middle point to [0, 0]
        arc_pos += trans
        #scale to the original distribution
        arc_pos *= scal
        arc_pos = arc_pos.tolist()

        return arc_pos, arc_angle

    def shape(self, num=30):
        """ribs, front, back"""
        return self.interactive_shape(num)[:-1]

    def interactive_shape(self, num=30):
        front_int = self.front.interpolate_3d(num=num)
        back_int = self.back.interpolate_3d(num=num)
        dist_line = self.cell_dist_interpolation
        dist = [i[0] for i in dist_line]
        front = map(front_int, dist)
        front = mirror2D_x(front)[::-1] + front
        back = map(back_int, dist)
        back = mirror2D_x(back)[::-1] + back
        ribs = zip(front, back)
        return [ribs, front, back, dist_line]

    @property
    def cell_dist_controlpoints(self):
        return self.cell_dist.controlpoints[1:-1]

    @cell_dist_controlpoints.setter
    def cell_dist_controlpoints(self, arr):
        self.cell_dist.controlpoints = [[0, 0]] + arr + [[self.front.controlpoints[-1][0], 1]]

    @property
    def cell_dist_interpolation(self):
        interpolation = self.cell_dist.interpolate_3d(num=20, which=1)
        start = (self.cell_num % 2) / self.cell_num
        return [interpolation(i) for i in numpy.linspace(start, 1, num=self.cell_num // 2 + 1)]

    def depth_integrated(self, num=100):
        l = numpy.linspace(0, self.front.controlpoints[-1][0], num)
        front_int = self.front.interpolate_3d(num=num)
        back_int = self.back.interpolate_3d(num=num)
        integrated_depth = [0.]
        for i in l[1:]:
            integrated_depth.append(integrated_depth[-1] + 1. / (front_int(i)[1] - back_int(i)[1]))
        return zip(l, [i / integrated_depth[-1] for i in integrated_depth])

    @property
    def span(self):
        return self.cell_dist_interpolation[-1][0] * 2

    @classmethod
    def fit_glider(cls, glider, numpoints=3):
        # todo: create glider2d from glider obj (fit bezier)
        def mirror_x(polyline):
            mirrored = [[-p[0], p[1]] for p in polyline[1:]]
            return mirrored[::-1] + polyline[glider.has_center_cell:]

        front, back = glider.shape_simple
        arc = [rib.pos[1:] for rib in glider.ribs]
        aoa = [[front[i][0], rib.aoa_relative] for i, rib in enumerate(glider.ribs)]

        front_bezier = SymmetricBezier.fit(mirror_x(front), numpoints=numpoints)
        back_bezier = SymmetricBezier.fit(mirror_x(back), numpoints=numpoints)
        arc_bezier = SymmetricBezier.fit(mirror_x(arc), numpoints=numpoints)
        aoa_bezier = SymmetricBezier.fit(mirror_x(aoa), numpoints=numpoints)

        cell_num = len(glider.cells) * 2 - glider.has_center_cell
        # if glider.has_center_cell:
        #     cell_num -= 1
        front[0][0] = 0  # for midribs
        start = (2 - (cell_num % 2)) / cell_num
        const_arr = [0.] + numpy.linspace(start, 1, len(front) - 1).tolist()
        rib_pos = [0.] + [p[0] for p in front[1:]]
        rib_pos_int = scipy.interpolate.interp1d(rib_pos, [rib_pos, const_arr])
        rib_distribution = [rib_pos_int(i) for i in numpy.linspace(0, rib_pos[-1], 30)]
        rib_distribution = BezierCurve.fit(rib_distribution, numpoints=numpoints + 3)
        gl2d = cls(front=front_bezier,
                   back=back_bezier,
                   cell_dist=rib_distribution,
                   cell_num=cell_num,
                   arc=arc_bezier,
                   aoa=aoa_bezier,
                   parametric=True)
        return gl2d

    def glider_3d(self, glider, num=50):
        """returns a new glider from parametric values"""
        ribs = []
        cells = []


        # TODO airfoil, ballooning, arc-------
        from openglider.airfoil import Profile2D
        airfoil = glider.ribs[0].profile_2d
        glide = 8.
        aoa = numpy.deg2rad(13.)
        #--------------------------------------

        from openglider.glider import Rib, Cell
        dist = [i[0] for i in self.cell_dist_interpolation]
        front_int = self.front.interpolate_3d(num=num)
        back_int = self.back.interpolate_3d(num=num)
        arc_pos, arc_angle = self.arc_pos_angle(num=num)
        aoa_cp = self.aoa.controlpoints
        self.aoa.controlpoints = [[p[0] / aoa_cp[-1][0] * dist[-1], p[1]] for p in aoa_cp]
        aoa = self.aoa.interpolate_3d(num=num)
        if dist[0] != 0.:
            # adding the mid cell
            dist = [-dist[0]] + dist
            arc_pos = [[-arc_pos[0][0], arc_pos[0][1]]] + arc_pos
            arc_angle = [-arc_angle[0]] + arc_angle

        for i, pos in enumerate(dist):
            fr = front_int(pos)
            ba = back_int(pos)
            ar = arc_pos[i]
            ribs.append(Rib(
                profile_2d=airfoil,
                startpoint=numpy.array([-fr[1], ar[0], ar[1]]),
                chord=norm(fr - ba),
                arcang=arc_angle[i],
                glide=glide,
                aoa=aoa(pos)[1]
                ))
        for i, rib in enumerate(ribs[1:]):
            cells.append(Cell(ribs[i], rib, []))
            glider.cells = cells


class ParaFoil(Profile2D):
    #TODO make new fit bezier methode to set the second x value of the controllpoints to zero.
    def __init__(self, data=None, name=None, normalize_root=True,
                 upper_spline=None, lower_spline=None):
        super(ParaFoil, self).__init__(data=data, name=name,
                                       normalize_root=normalize_root)
        self.upper_spline = upper_spline or self.fit_upper()
        self.lower_spline = lower_spline or self.fit_lower()

    def fit_upper(self, num=100, dist=None, control_num=6):
        if self.data is None:
            return BezierCurve()
        upper = self.data[:self.noseindex + 1]
        upper_smooth = self.make_smooth_dist(upper, num, dist)
        return BezierCurve.fit(upper_smooth, numpoints=control_num)

    def fit_lower(self, num=100, dist=None, control_num=6):
        if self.data is None:
            return BezierCurve()
        lower = self.data[self.noseindex:]
        lower_smooth = self.make_smooth_dist(lower, num, dist, upper=False)
        return BezierCurve.fit(lower_smooth, numpoints=control_num)

    def apply_splines(self, num=70):
        upper = self.upper_spline.get_sequence(num).T
        lower = self.lower_spline.get_sequence(num).T
        self.data = numpy.array(upper.tolist() + lower[1:].tolist())

    def make_smooth_dist(self, points, num=70, dist=None, upper=True):
        # make array [[lenght, x, y], ...]
        length = [0]
        for i, point in enumerate(points[1:]):
            length.append(length[-1] + norm(point - points[i]))
        interpolation = scipy.interpolate.interp1d(length, numpy.array(points).T)
        if dist == "const":
            dist = numpy.linspace(0, length[-1], num)
        elif dist == "sin":
            if upper:
                dist = [numpy.sin(i) * length[-1] for i in numpy.linspace(0, numpy.pi / 2, num)]
            else:
                dist = [abs(1 - numpy.sin(i)) * length[-1] for i in numpy.linspace(0, numpy.pi / 2, num)]
        elif dist == "hardcore":
            # berechne kruemmung in den punkten
            pass
        else:
            return points
        return [interpolation(i) for i in dist]



if __name__ == "__main__":
    a = ParaFoil.compute_naca()
    import openglider.graphics as g
    g.Graphics3D([
        g.Line(a.upper_spline.get_sequence().T),
        g.Line(a.upper_spline.controlpoints),
        g.Line(a.lower_spline.get_sequence().T),
        g.Line(a.lower_spline.controlpoints),
        g.Point(a.data)
        ])