import openglider.rs
from openglider.lines.line import Line
from openglider.lines.lineset import LineSet
from openglider.lines.node import Node


def test_get_lines_for_riser_returns_only_selected_tree() -> None:
    vector = openglider.rs.vector.Vector3D
    v_inf = vector([0, 0, 0])

    lower = Node(node_type=Node.NODE_TYPE.LOWER, position=vector([0, 0, 0]), name="MAIN")
    knot_a = Node(node_type=Node.NODE_TYPE.KNOT, position=vector([0, 0, 1]), name="A")
    knot_b = Node(node_type=Node.NODE_TYPE.KNOT, position=vector([1, 0, 1]), name="B")
    knot_b_mid = Node(node_type=Node.NODE_TYPE.KNOT, position=vector([1, 0, 2]), name="B-mid")
    upper_a = Node(node_type=Node.NODE_TYPE.UPPER, position=vector([0, 0, 2]), name="a1")
    upper_b = Node(node_type=Node.NODE_TYPE.UPPER, position=vector([1, 0, 3]), name="b1")

    def line(name: str, lower_node: Node, upper_node: Node) -> Line:
        return Line(
            lower_node=lower_node,
            upper_node=upper_node,
            target_length=None,
            v_inf=v_inf,
            name=name,
        )

    riser_a = line("riser-a", lower, knot_a)
    a_gallery = line("a-gallery", knot_a, upper_a)
    riser_b = line("riser-b", lower, knot_b)
    b_middle = line("b-middle", knot_b, knot_b_mid)
    b_gallery = line("b-gallery", knot_b_mid, upper_b)

    lineset = LineSet([riser_a, a_gallery, riser_b, b_middle, b_gallery])

    assert {id(line) for line in lineset.get_lines_for_riser(0)} == {
        id(riser_a),
        id(a_gallery),
    }
    assert {id(line) for line in lineset.get_lines_for_riser(1)} == {
        id(riser_b),
        id(b_middle),
        id(b_gallery),
    }
    assert lineset.get_lines_for_riser(-1) == []
    assert lineset.get_lines_for_riser(2) == []
