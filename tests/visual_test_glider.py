#! /usr/bin/python2
# -*- coding: utf-8; -*-
#
# (c) 2013 booya (http://booya.at)
#
# This file is part of the OpenGlider project.
#
# OpenGlider is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# OpenGlider is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with OpenGlider.  If not, see <http://www.gnu.org/licenses/>.
import math
import os
import random
import sys

try:
    import openglider
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0]))))
    import openglider
import openglider.Graphics
import unittest

testfolder = os.path.dirname(os.path.abspath(__file__))
importpath = testfolder + '/demokite.ods'


class GliderTestClass(unittest.TestCase):
    def setUp(self, complete=True):
        self.glider = openglider.Glider()
        self.glider.import_geometry(path=importpath)
        self.glider.recalc()


class TestGlider(GliderTestClass):
    def test_show_3d(self, num=5):
        thaglider = self.glider.copy_complete()
        thaglider.recalc()
        polygons, points = thaglider.return_polygons(num)
        objects = [openglider.Graphics.Polygon(polygon) for polygon in polygons]
        objects.append(openglider.Graphics.Axes(size=1.2))
        openglider.Graphics.Graphics3D(objects, points)

    def test_show_shape(self):
        self.glider = self.glider.copy_complete()
        self.glider.recalc()
        left, right = self.glider.shape()
        left.rotate(math.pi/2)
        right.rotate(math.pi/2, [0, 0])
        data = [left.data,
                right.data]
        data += [[left.data[i], right.data[i]] for i in range(len(left.data))]
        openglider.Graphics.Graphics2D([openglider.Graphics.Line(obj) for obj in data])

    @unittest.skip("skipped")
    def test_midrib_projection(self):
        num = 3
        data = []
        for i in range(num):
            cell = self.glider.cells[random.randint(0, len(self.glider.cells)-1)]
            prof = cell.midrib(random.random())
            prof.projection()
            data += [prof.data,
                     [prof.data[0], prof.data[0]+prof.xvect],
                     [prof.data[0], prof.data[0]+prof.yvect]]

        openglider.Graphics.Graphics([openglider.Graphics.Line(obj) for obj in data])

    def test_midrib_flattened(self):
        num = 2
        cell = self.glider.cells[random.randint(0, len(self.glider.cells)-1)]
        profs = [cell.rib1.profile_2d.data]
        profs += [cell.midrib(random.random()).flatten().data + [0, (i+1)*0.] for i in range(num)]
        openglider.Graphics.Graphics2D([openglider.Graphics.Line(prof) for prof in profs])