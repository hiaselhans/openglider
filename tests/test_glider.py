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
from openglider.Ribs import MiniRib
import os
import openglider.Graphics

__author__ = 'simon'
testfolder = os.path.dirname(os.path.abspath( __file__ ))
import unittest

from openglider import glider


class test_glider_class(unittest.TestCase):
    #def __init__(self):
    #    unittest.TestCase.__init__(self)

    def setUp(self):
        self.glider = glider.Glider()
        self.glider.import_from_file(testfolder+'/demokite.ods')

    def test_import_export_ods(self):
        path = '/tmp/daweil.ods'
        self.glider.export_to_file(path)
        #new_glider = glider.Glider()
        #self.assertTrue(new_glider.import_from_file(path))
        #self.assertEqual(new_glider, self.glider)

    def test_export_obj(self):
        path = '/tmp/Booya.obj'
        self.glider.export_obj(path, 5)



if __name__ == '__main__':
        unittest.main(verbosity=2)