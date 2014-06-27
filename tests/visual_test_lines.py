import unittest
import os

from openglider.lines.import_text import import_lines
from openglider.lines import LineSet
import openglider.graphics as graph


test_dir = os.path.dirname(os.path.abspath(__file__))


class TestLines(unittest.TestCase):
    def setUp(self):
        pass

    def runcase(self, path):
        key_dict = import_lines(path)

        thalines = LineSet(
            key_dict["LINES"][2], key_dict["CALCPAR"][2]["V_INF"])
        strt = thalines.lowest_lines
        thalines.calc_geo(strt)

        thalines.calc_sag(strt)
        objects = map(lambda line: graph.Line(line.get_line_points()), thalines.lines)
        graph.Graphics3D(objects)

    def test_case_1(self):
        self.runcase(test_dir+"/lines/TEST_INPUT_FILE_1.txt")

    def test_case_2(self):
        self.runcase(test_dir+"/lines/TEST_INPUT_FILE_2.txt")

    def test_case_3(self):
        self.runcase(test_dir+"/lines/TEST_INPUT_FILE_3.txt")


if __name__ == '__main__':
    unittest.main(verbosity=2)